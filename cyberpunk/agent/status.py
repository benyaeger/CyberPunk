"""Streaming, scroll-back-friendly status output for agent runs.

Unlike a ``rich.Live`` panel (which re-renders in place and forces us to
truncate streamed tokens to fit a fixed box), this display writes every
event — tokens, tool invocations, tool results, errors — directly into
the console. Nothing gets overwritten, so the user can scroll back
through the agent's full chain of thought and every tool's full output.
"""

from __future__ import annotations

import json
import time
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax


class StatusDisplay:
    """Scrollable, streaming status log for a single agent run.

    Every method writes to the console and never rewinds. LLM token
    streaming goes through :meth:`add_token` — tokens are written as raw
    text with explicit flushing so they appear letter-by-letter in the
    terminal (same UX as a typewriter). Tool calls, results, cache hits,
    and stealth blocks become permanent log lines above whatever comes
    next.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._start_time = time.monotonic()
        # Whether we're mid-way through emitting an LLM token stream.
        # Used to know when to prepend an indent / terminate with a newline.
        self._streaming = False

    def start(self) -> None:
        """Mark the beginning of the run with a visual divider."""
        self._start_time = time.monotonic()
        self._console.rule("[bold cyan]CyberPunk Agent[/bold cyan]", style="cyan")

    def stop(self) -> None:
        """Close out the run. Safe to call even if ``start`` wasn't."""
        self._finish_stream()
        self._console.rule(f"[dim]Completed in {self._elapsed()}[/dim]", style="dim cyan")

    def set_phase(self, phase: str, detail: str = "") -> None:
        """Emit a phase header (e.g. ``Thinking (iteration 2)``)."""
        self._finish_stream()
        suffix = f" [dim]{detail}[/dim]" if detail else ""
        self._console.print()
        self._console.print(f"[bold cyan]▶ {escape(phase)}[/bold cyan]{suffix}")

    def add_token(self, token: str) -> None:
        """Stream one LLM token to the terminal, raw and flushed.

        Writes bypass Rich's renderer so markup inside generated text is
        not interpreted and tokens appear immediately (no buffering until
        a full line is complete).
        """
        if not token:
            return
        if not self._streaming:
            self._streaming = True
            self._console.file.write("  ")
        self._console.file.write(token)
        self._console.file.flush()

    def end_stream(self) -> None:
        """Called when an LLM turn finishes; terminates the token line."""
        self._finish_stream()

    def log_tool_start(self, tool_name: str, arguments: dict[str, Any]) -> None:
        """Announce that a tool is about to execute."""
        self._finish_stream()
        args_repr = ""
        if arguments:
            args_repr = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
            args_repr = f" [dim]({escape(args_repr)})[/dim]"
        self._console.print(
            f"  [cyan]→[/cyan] [bold cyan]{escape(tool_name)}[/bold cyan]{args_repr}"
        )

    def log_tool_success(
        self,
        tool_name: str,
        elapsed_ms: float,
        data: Any = None,
    ) -> None:
        """Record a successful tool execution and dump its full result."""
        self._finish_stream()
        self._console.print(
            f"  [green]✓[/green] [cyan]{escape(tool_name)}[/cyan] [dim]({elapsed_ms:.0f}ms)[/dim]"
        )
        if data is not None:
            self._print_result(data)

    def log_tool_error(self, tool_name: str, error: str) -> None:
        """Record a failed tool execution."""
        self._finish_stream()
        self._console.print(
            f"  [red]✗[/red] [cyan]{escape(tool_name)}[/cyan] [red]{escape(error)}[/red]"
        )

    def log_cached(self, tool_name: str) -> None:
        """Record a per-run cache hit."""
        self._finish_stream()
        self._console.print(
            f"  [yellow]↺[/yellow] [cyan]{escape(tool_name)}[/cyan] [dim](cached)[/dim]"
        )

    def log_stealth_block(self, tool_name: str) -> None:
        """Record a tool call refused by stealth mode."""
        self._finish_stream()
        self._console.print(
            f"  [red]⊘[/red] [cyan]{escape(tool_name)}[/cyan] [dim]blocked by stealth mode[/dim]"
        )

    def _print_result(self, data: Any) -> None:
        """Pretty-print a tool result payload inside a dim-bordered panel."""
        try:
            body = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            body = str(data)
        self._console.print(
            Panel(
                Syntax(
                    body,
                    "json",
                    theme="ansi_dark",
                    background_color="default",
                    word_wrap=True,
                ),
                border_style="dim",
                padding=(0, 1),
                expand=True,
            )
        )

    def _finish_stream(self) -> None:
        """End an in-progress token stream with a newline, if any."""
        if self._streaming:
            self._console.file.write("\n")
            self._console.file.flush()
            self._streaming = False

    def _elapsed(self) -> str:
        s = time.monotonic() - self._start_time
        return f"{s:.0f}s" if s < 60 else f"{s / 60:.1f}m"
