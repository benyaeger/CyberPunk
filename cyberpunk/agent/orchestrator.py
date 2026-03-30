"""Agent orchestrator: LLM <-> tool loop with iteration cap, stealth enforcement, and live status."""

from __future__ import annotations

import platform
import socket
import time
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from cyberpunk.agent.llm_client import OllamaClient
from cyberpunk.agent.prompts import build_system_prompt, get_task_prompt
from cyberpunk.core.audit import AuditLogger
from cyberpunk.core.config import CyberPunkConfig
from cyberpunk.models import ToolCall, ToolCategory, ToolResult
from cyberpunk.tools import ToolRegistry
from cyberpunk.utils.system import get_platform


class StatusDisplay:
    """Claude Code-style live status display using Rich."""

    def __init__(self, console: Console, verbose: bool = False) -> None:
        self._console = console
        self._verbose = verbose
        self._live: Live | None = None
        self._phase = ""
        self._detail = ""
        self._token_buf = ""
        self._history: list[Text] = []
        self._start_time = time.monotonic()

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=12,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def set_phase(self, phase: str, detail: str = "") -> None:
        self._phase = phase
        self._detail = detail
        self._token_buf = ""
        self._refresh()

    def add_token(self, token: str) -> None:
        self._token_buf += token
        # Trim to last 120 chars for display
        if len(self._token_buf) > 120:
            self._token_buf = "…" + self._token_buf[-119:]
        self._refresh()

    def log_tool_result(self, tool_name: str, result: ToolResult, elapsed_ms: float) -> None:
        if result.success:
            line = Text.from_markup(
                f"  [green]✓[/green] [cyan]{escape(tool_name)}[/cyan] "
                f"[dim]({elapsed_ms:.0f}ms)[/dim]"
            )
        else:
            line = Text.from_markup(
                f"  [red]✗[/red] [cyan]{escape(tool_name)}[/cyan] "
                f"[dim]{escape(result.error or 'failed')}[/dim]"
            )
        self._history.append(line)
        self._refresh()

    def log_cached(self, tool_name: str) -> None:
        line = Text.from_markup(
            f"  [yellow]↺[/yellow] [cyan]{escape(tool_name)}[/cyan] [dim](cached)[/dim]"
        )
        self._history.append(line)
        self._refresh()

    def log_stealth_block(self, tool_name: str) -> None:
        line = Text.from_markup(
            f"  [red]⊘[/red] [cyan]{escape(tool_name)}[/cyan] [dim]blocked by stealth mode[/dim]"
        )
        self._history.append(line)
        self._refresh()

    def _elapsed(self) -> str:
        s = time.monotonic() - self._start_time
        if s < 60:
            return f"{s:.0f}s"
        return f"{s / 60:.1f}m"

    def _render(self) -> Panel:
        parts: list[Text | Spinner] = []

        # History lines (tool results, etc.)
        for line in self._history:
            parts.append(line)

        # Current activity spinner
        if self._phase:
            detail = f"  {self._detail}" if self._detail else ""
            spinner_text = f" {self._phase}{detail}"
            if self._token_buf:
                # Show streaming tokens as dim preview
                preview = self._token_buf.replace("\n", " ").strip()
                if preview:
                    spinner_text += f"\n  [dim]{escape(preview)}[/dim]"
            parts.append(Text(""))  # spacing
            parts.append(Spinner("dots", text=Text.from_markup(spinner_text), style="cyan"))

        elapsed = self._elapsed()
        return Panel(
            Group(*parts) if parts else Text("[dim]Starting...[/dim]"),
            title=f"[bold cyan]CyberPunk Agent[/bold cyan] [dim]{elapsed}[/dim]",
            border_style="dim cyan",
            padding=(0, 1),
        )

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())


class AgentOrchestrator:
    """Runs the agent loop: sends prompts to LLM, executes tool calls, feeds results back."""

    def __init__(
        self,
        config: CyberPunkConfig,
        registry: ToolRegistry,
        console: Console,
        verbose: bool = False,
    ) -> None:
        self.config = config
        self.registry = registry
        self.console = console
        self.verbose = verbose
        self.audit = AuditLogger(config.safety.audit_log_path)
        self.llm = OllamaClient(
            model=config.llm.model,
            base_url=config.llm.base_url,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            timeout=config.llm.timeout,
        )
        self._tool_cache: dict[str, ToolResult] = {}

    def run(
        self,
        command: str = "analyze",
        stealth: bool = False,
        subnet: str | None = None,
    ) -> str:
        """Execute the agent loop for a given command.

        Args:
            command: CLI command name (analyze, diff, report).
            stealth: Whether stealth mode is active.
            subnet: Target subnet override.

        Returns:
            Final LLM text response.
        """
        max_iterations = self.config.safety.max_agent_iterations

        # Build messages
        system_prompt = build_system_prompt(
            hostname=socket.gethostname(),
            os_name=platform.system(),
            platform=get_platform(),
            stealth=stealth,
            subnet=subnet,
        )
        task_prompt = get_task_prompt(command, stealth=stealth)
        tools_schema = self.registry.get_ollama_tools(stealth=stealth)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
        ]

        self.audit.log_scan("scan_start", scan_type="stealth" if stealth else "full")

        # Live status display
        status = StatusDisplay(self.console, verbose=self.verbose)
        status.start()

        try:
            return self._agent_loop(
                messages, tools_schema, max_iterations, stealth, status,
            )
        finally:
            status.stop()

    def _agent_loop(
        self,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        max_iterations: int,
        stealth: bool,
        status: StatusDisplay,
    ) -> str:
        for iteration in range(1, max_iterations + 1):
            status.set_phase(
                f"Thinking",
                f"[dim](iteration {iteration}/{max_iterations})[/dim]",
            )

            # Call LLM with streaming token callback
            response = self.llm.chat(
                messages,
                tools=tools_schema,
                on_token=status.add_token,
            )

            # If no tool calls, this is the final response
            if not response.tool_calls:
                self.audit.log_scan(
                    "scan_end",
                    scan_type="stealth" if stealth else "full",
                    iterations=iteration,
                )
                return response.content

            # Process each tool call
            for tool_call in response.tool_calls:
                status.set_phase(
                    f"Running [bold]{escape(tool_call.tool_name)}[/bold]",
                    f"[dim]{self._format_args(tool_call.arguments)}[/dim]"
                    if tool_call.arguments else "",
                )

                result = self._execute_tool_call(tool_call, stealth, status)

                # Add assistant message with tool call, then tool result
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": tool_call.tool_name,
                            "arguments": tool_call.arguments,
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "content": self._format_tool_result(result),
                })

        # Hit iteration cap — ask LLM to summarize
        status.set_phase("Summarizing", "[dim](iteration cap reached)[/dim]")
        messages.append({
            "role": "user",
            "content": (
                "You have reached the maximum number of tool calls. "
                "Summarize your findings based on the data collected so far."
            ),
        })
        response = self.llm.chat(messages, tools=None, on_token=status.add_token)
        self.audit.log_scan(
            "scan_end",
            scan_type="stealth" if stealth else "full",
            iterations=max_iterations,
            capped=True,
        )
        return response.content

    def _execute_tool_call(
        self, tool_call: ToolCall, stealth: bool, status: StatusDisplay,
    ) -> ToolResult:
        """Execute a single tool call with safety checks and caching."""
        tool_name = tool_call.tool_name

        # Check cache
        cache_key = f"{tool_name}:{sorted(tool_call.arguments.items())}"
        if cache_key in self._tool_cache:
            status.log_cached(tool_name)
            return self._tool_cache[cache_key]

        tool = self.registry.get(tool_name)

        # Tool doesn't exist
        if tool is None:
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Unknown tool: {tool_name}",
            )
            self.audit.log_tool_call(
                tool=tool_name, category="unknown", arguments=tool_call.arguments,
                success=False, execution_time_ms=0, error=result.error,
            )
            status.log_tool_result(tool_name, result, 0)
            return result

        # Stealth gate (second layer — defense in depth)
        if stealth and tool.definition.category == ToolCategory.ACTIVE:
            self.audit.log_stealth_block(tool_name)
            status.log_stealth_block(tool_name)
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' blocked: stealth mode is active.",
            )

        # Execute
        result = tool.run(**tool_call.arguments)

        # Audit
        summary = ""
        if result.success and isinstance(result.data, dict):
            count = result.data.get("count")
            if count is not None:
                summary = f"Found {count} entries"
        self.audit.log_tool_call(
            tool=tool_name,
            category=tool.definition.category.value,
            arguments=tool_call.arguments,
            success=result.success,
            execution_time_ms=result.execution_time_ms,
            result_summary=summary,
            error=result.error,
        )

        # Cache
        self._tool_cache[cache_key] = result
        status.log_tool_result(tool_name, result, result.execution_time_ms)
        return result

    @staticmethod
    def _format_tool_result(result: ToolResult) -> str:
        """Format a ToolResult as a string for the LLM context."""
        if result.success:
            import json
            return json.dumps(result.data, default=str)
        return f"Error: {result.error}"

    @staticmethod
    def _format_args(args: dict[str, Any]) -> str:
        """Format tool arguments for display (compact)."""
        if not args:
            return ""
        parts = [f"{k}={v}" for k, v in args.items()]
        text = ", ".join(parts)
        return text[:60] + "…" if len(text) > 60 else text
