"""Claude-Code-style live status panel for agent runs."""

from __future__ import annotations

import time

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text


class StatusDisplay:
    """Rich ``Live`` panel showing agent phase, streamed tokens, and tool history.

    The panel is UI — it owns the terminal while the agent runs, so every
    progress signal (streamed tokens, tool completions, cache hits, stealth
    blocks) is forwarded here instead of being printed separately. All token
    streaming goes through :meth:`add_token`, triggered from the LangChain
    ``BaseCallbackHandler`` in :mod:`cyberpunk.agent.callbacks`.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None
        self._phase = ""
        self._detail = ""
        self._token_buf = ""
        self._history: list[Text] = []
        self._start_time = time.monotonic()

    def start(self) -> None:
        """Begin rendering the live panel."""
        self._start_time = time.monotonic()
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=12,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Tear down the live panel. Safe to call even if ``start`` wasn't."""
        if self._live:
            self._live.stop()
            self._live = None

    def set_phase(self, phase: str, detail: str = "") -> None:
        """Switch the spinner to a new phase (e.g. "Thinking", "Running tool")."""
        self._phase = phase
        self._detail = detail
        self._token_buf = ""
        self._refresh()

    def add_token(self, token: str) -> None:
        """Append a streamed LLM token to the preview buffer."""
        self._token_buf += token
        # Keep only the tail — displaying the full generation would crowd
        # the terminal and render the spinner invisible.
        if len(self._token_buf) > 120:
            self._token_buf = "…" + self._token_buf[-119:]
        self._refresh()

    def log_tool_success(self, tool_name: str, elapsed_ms: float) -> None:
        """Record a successful tool execution."""
        self._history.append(
            Text.from_markup(
                f"  [green]✓[/green] [cyan]{escape(tool_name)}[/cyan] "
                f"[dim]({elapsed_ms:.0f}ms)[/dim]"
            )
        )
        self._refresh()

    def log_tool_error(self, tool_name: str, error: str) -> None:
        """Record a tool execution that failed or raised."""
        self._history.append(
            Text.from_markup(
                f"  [red]✗[/red] [cyan]{escape(tool_name)}[/cyan] [dim]{escape(error)}[/dim]"
            )
        )
        self._refresh()

    def log_cached(self, tool_name: str) -> None:
        """Record a cache hit (tool result reused from the per-run cache)."""
        self._history.append(
            Text.from_markup(
                f"  [yellow]↺[/yellow] [cyan]{escape(tool_name)}[/cyan] [dim](cached)[/dim]"
            )
        )
        self._refresh()

    def log_stealth_block(self, tool_name: str) -> None:
        """Record that stealth mode blocked an active tool."""
        self._history.append(
            Text.from_markup(
                f"  [red]⊘[/red] [cyan]{escape(tool_name)}[/cyan] "
                f"[dim]blocked by stealth mode[/dim]"
            )
        )
        self._refresh()

    def _elapsed(self) -> str:
        s = time.monotonic() - self._start_time
        return f"{s:.0f}s" if s < 60 else f"{s / 60:.1f}m"

    def _render(self) -> Panel:
        parts: list[Text | Spinner] = list(self._history)

        if self._phase:
            detail = f"  {self._detail}" if self._detail else ""
            spinner_text = f" {self._phase}{detail}"
            if self._token_buf:
                preview = self._token_buf.replace("\n", " ").strip()
                if preview:
                    spinner_text += f"\n  [dim]{escape(preview)}[/dim]"
            parts.append(Text(""))
            parts.append(Spinner("dots", text=Text.from_markup(spinner_text), style="cyan"))

        return Panel(
            Group(*parts) if parts else Text("[dim]Starting...[/dim]"),
            title=f"[bold cyan]CyberPunk Agent[/bold cyan] [dim]{self._elapsed()}[/dim]",
            border_style="dim cyan",
            padding=(0, 1),
        )

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())
