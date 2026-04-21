"""LangChain callback handler: streams LLM tokens to status + writes audit events."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

if TYPE_CHECKING:
    from cyberpunk.agent.status import StatusDisplay
    from cyberpunk.core.audit import AuditLogger


class AgentCallbacks(BaseCallbackHandler):
    """Bridge LangChain's callback protocol to ``StatusDisplay`` and ``AuditLogger``.

    Why this exists as a callback rather than a direct wire in the graph:
    the graph calls ``model.ainvoke`` / ``model.invoke`` indirectly through
    LangGraph's runtime, and LangGraph doesn't hand us the streamed tokens.
    Registering a callback is the supported extension point for capturing
    those tokens without re-implementing the graph's ``agent`` node.

    Audit events are also emitted here so the graph doesn't need to know
    about the log at all — the LLM call site is the correct place to record
    the request that went out and the response that came back.
    """

    def __init__(
        self,
        status: StatusDisplay,
        audit: AuditLogger,
        iteration_provider: Callable[[], int],
    ) -> None:
        """Initialize the handler.

        Args:
            status: The live status panel receiving streamed tokens.
            audit: The per-run audit logger.
            iteration_provider: Zero-arg callable returning the current
                agent iteration. The graph owns this counter, and we read
                it fresh on every LLM boundary so audit entries reflect the
                iteration in which they were actually emitted.
        """
        super().__init__()
        self._status = status
        self._audit = audit
        self._iteration = iteration_provider
        # One "run" in LangChain == one LLM invocation. Keyed buffers avoid
        # cross-talk if a future change invokes multiple LLMs in parallel.
        self._token_buffers: dict[UUID, list[str]] = {}
        self._starts: dict[UUID, float] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Record the outgoing chat request and start the timer."""
        self._token_buffers[run_id] = []
        self._starts[run_id] = time.time()

        flat: list[dict[str, Any]] = []
        for m in messages[0] if messages else []:
            flat.append(
                {
                    "role": getattr(m, "type", "unknown"),
                    "content": getattr(m, "content", ""),
                }
            )

        # LangChain bundles bound tools into ``invocation_params`` for chat
        # models. Surface them in the audit log when present so the log
        # retains the same "what was the model allowed to call" shape as
        # before.
        inv_params = kwargs.get("invocation_params") or {}
        tools = inv_params.get("tools") if isinstance(inv_params, dict) else None

        self._audit.log_llm_request(
            messages=flat,
            tools=tools,
            iteration=self._iteration(),
        )

    def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Forward a streamed token to the live panel and buffer it."""
        if token:
            self._token_buffers.setdefault(run_id, []).append(token)
            self._status.add_token(token)

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Write the full response (content, tool calls, timing) to the audit log."""
        elapsed_ms = (time.time() - self._starts.pop(run_id, time.time())) * 1000
        tokens = "".join(self._token_buffers.pop(run_id, []))
        iteration = self._iteration()
        # Terminate the streaming line so subsequent log entries sit on
        # their own line instead of being appended to the last token.
        self._status.end_stream()

        if tokens:
            self._audit.log_llm_tokens(tokens, iteration)

        content = ""
        tool_calls: list[dict[str, Any]] = []
        eval_count: int | None = None
        prompt_eval_count: int | None = None

        if response.generations and response.generations[0]:
            gen = response.generations[0][0]
            message = getattr(gen, "message", None)
            if message is not None:
                raw_content = getattr(message, "content", "") or ""
                content = raw_content if isinstance(raw_content, str) else str(raw_content)
                for tc in getattr(message, "tool_calls", []) or []:
                    tool_calls.append(
                        {
                            "tool_name": tc.get("name", ""),
                            "arguments": tc.get("args", {}),
                        }
                    )

        # ``langchain-ollama`` surfaces Ollama's eval counters in
        # ``llm_output`` when they're available.
        if response.llm_output:
            eval_count = response.llm_output.get("eval_count")
            prompt_eval_count = response.llm_output.get("prompt_eval_count")

        self._audit.log_llm_response(
            content=content,
            tool_calls=tool_calls,
            iteration=iteration,
            elapsed_ms=elapsed_ms,
            eval_count=eval_count,
            prompt_eval_count=prompt_eval_count,
        )
