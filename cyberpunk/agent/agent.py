"""High-level entry point: build the graph + drive one agent run."""

from __future__ import annotations

import platform as py_platform
import socket
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from rich.console import Console

from cyberpunk.agent.callbacks import AgentCallbacks
from cyberpunk.agent.graph import AgentState, build_graph
from cyberpunk.agent.llm import build_chat_model
from cyberpunk.agent.observability import build_langfuse_handler, flush_langfuse
from cyberpunk.agent.prompts import build_system_prompt, get_task_prompt
from cyberpunk.agent.status import StatusDisplay
from cyberpunk.agent.tool_wrapper import wrap_tools_for_run
from cyberpunk.core.audit import AuditLogger
from cyberpunk.tools import available_tools
from cyberpunk.utils.system import get_platform

if TYPE_CHECKING:
    from cyberpunk.core.config import CyberPunkConfig


class AgentRunner:
    """Orchestrates a single CyberPunk agent invocation.

    One ``AgentRunner`` instance owns one ``AuditLogger`` (and therefore one
    per-run log file). Reusing an instance across runs is not supported and
    would mix events from multiple scans into the same audit file.
    """

    def __init__(self, config: CyberPunkConfig, console: Console) -> None:
        self.config = config
        self.console = console
        self.audit = AuditLogger(config.safety.audit_log_dir)
        self._model = build_chat_model(config)

    def run(
        self,
        command: str = "analyze",
        stealth: bool = False,
        subnet: str | None = None,
    ) -> str:
        """Execute one end-to-end agent run.

        Args:
            command: Task template key (``analyze``, ``diff``, ``report``).
            stealth: Whether to restrict to passive tools only.
            subnet: Optional explicit target subnet for active scans.

        Returns:
            The agent's final text output (Markdown, ready for rendering).
        """
        system_prompt = build_system_prompt(
            hostname=socket.gethostname(),
            os_name=py_platform.system(),
            platform=get_platform(),
            stealth=stealth,
            subnet=subnet,
        )
        task_prompt = get_task_prompt(command, stealth=stealth)

        status = StatusDisplay(self.console)
        status.start()

        try:
            available = available_tools(stealth=stealth)
            self.audit.log_scan(
                "scan_start",
                scan_type="stealth" if stealth else "full",
                tool_count=len(available),
                tool_names=[t.name for t in available],
            )

            # Per-run cache — scoped to this invocation. Keys are stable
            # strings built from (tool name + sorted argument tuple).
            cache: dict[str, str] = {}

            # Two-layer stealth enforcement:
            #   (1) ``available_tools`` filters active tools from the list
            #       that gets bound to the model, so the model never sees
            #       them.
            #   (2) ``wrap_tools_for_run`` still checks stealth inside each
            #       wrapper to catch hallucinated tool calls for names that
            #       weren't bound.
            tools = wrap_tools_for_run(
                available,
                stealth=stealth,
                cache=cache,
                status=status,
                audit=self.audit,
            )

            graph = build_graph(
                model=self._model,
                tools=tools,
                max_iterations=self.config.safety.max_agent_iterations,
            )

            # The agent node reads ``iteration`` off the state each call;
            # we hand the callbacks a closure that reflects whatever the
            # state currently says. ``final_state`` below captures it.
            state: AgentState = {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=task_prompt),
                ],
                "iteration": 0,
            }
            current_iteration = {"value": 0}

            def _iteration() -> int:
                return current_iteration["value"]

            callbacks: list[object] = [
                AgentCallbacks(
                    status=status,
                    audit=self.audit,
                    iteration_provider=_iteration,
                )
            ]
            langfuse_handler = build_langfuse_handler()
            if langfuse_handler is not None:
                callbacks.append(langfuse_handler)

            status.set_phase("Thinking", "(iteration 1)")
            last_phase_iteration = 0

            # ``stream`` so we can update the phase between agent turns.
            # Each yielded update is ``{node_name: state_delta}``.
            final_state: AgentState | None = None
            for update in graph.stream(
                state,
                config={
                    "callbacks": callbacks,
                    "run_name": f"cyberpunk-{command}-{'stealth' if stealth else 'full'}",
                    "tags": [
                        f"command:{command}",
                        f"mode:{'stealth' if stealth else 'full'}",
                        f"model:{self.config.llm.model}",
                    ],
                    # Allow enough node visits for max_iterations
                    # (agent + tools) plus the summarize path and a small
                    # buffer. LangGraph raises GraphRecursionError beyond
                    # this — we want to hit the ``should_continue``
                    # summarize branch first.
                    "recursion_limit": 2 * self.config.safety.max_agent_iterations + 4,
                },
                stream_mode="values",
            ):
                final_state = update  # type: ignore[assignment]
                current_iteration["value"] = update["iteration"]
                # Only print a new phase header when the iteration actually
                # advances — ``stream_mode="values"`` yields after every
                # node visit, which would otherwise cause duplicate
                # "Thinking (iteration N)" lines per turn.
                if (
                    update["iteration"] != last_phase_iteration
                    and update["iteration"] < self.config.safety.max_agent_iterations
                ):
                    last_phase_iteration = update["iteration"]
                    status.set_phase(
                        "Thinking",
                        f"(iteration {update['iteration'] + 1})",
                    )

            if final_state is None:  # pragma: no cover — guard
                raise RuntimeError("Agent produced no final state")

            self.audit.log_scan(
                "scan_end",
                scan_type="stealth" if stealth else "full",
                iterations=final_state["iteration"],
                capped=final_state["iteration"] >= self.config.safety.max_agent_iterations,
            )

            return _extract_final_text(final_state)
        finally:
            status.stop()
            # CLI is short-lived — flush Langfuse's background worker or
            # in-flight spans never make it to the server.
            flush_langfuse()


def _extract_final_text(state: AgentState) -> str:
    """Pull the final assistant text out of the graph's terminal state.

    The last message is always an ``AIMessage`` — either the natural end of
    a tool-calling turn (no more ``tool_calls``) or the summarization pass.
    """
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            # LangChain sometimes returns content as a list of parts for
            # multimodal models; coerce to string for the renderer.
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
    return ""
