"""CLI entry point: Typer app with all commands and flags."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cyberpunk import __app_name__, __version__
from cyberpunk.agent import AgentRunner
from cyberpunk.agent.llm import health_check
from cyberpunk.core.config import load_config
from cyberpunk.tools import available_tools

app = typer.Typer(
    name="cyberpunk",
    help="CLI network intelligence powered by local LLM.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"{__app_name__} v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """CyberPunk — network intelligence powered by local LLM."""


@app.command()
def analyze(
    stealth: Annotated[bool, typer.Option("--stealth", "-s", help="Passive-only mode.")] = False,
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output format: rich, json, plain.")
    ] = "rich",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show tool calls and reasoning.")
    ] = False,
    subnet: Annotated[
        str | None,
        typer.Option("--subnet", help="Target subnet (e.g. 192.168.1.0/24)."),
    ] = None,
    config_path: Annotated[
        str | None, typer.Option("--config", "-c", help="Config file path.")
    ] = None,
) -> None:
    """Run a network analysis."""
    config = load_config(config_path)

    if output != "rich":
        config.output.format = output

    ok, msg = health_check(config)
    if not ok:
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1)

    if verbose:
        console.print(f"[dim]{msg}[/dim]")

    tool_count = len(available_tools(stealth=stealth))
    mode = "stealth" if stealth else "full"
    console.print(
        Panel(
            Text.from_markup(
                f"[bold cyan]{__app_name__}[/bold cyan] Network Analysis\n"
                f"Mode: [{'yellow' if stealth else 'green'}]{mode}"
                f"[/{'yellow' if stealth else 'green'}] "
                f"| Tools: {tool_count} | Model: {config.llm.model}"
            ),
            border_style="cyan",
        )
    )

    runner = AgentRunner(config=config, console=console)
    try:
        result = runner.run(command="analyze", stealth=stealth, subnet=subnet)
    except Exception as e:
        console.print(f"[red]Agent error:[/red] {e}")
        raise typer.Exit(1) from e

    if config.output.format == "json":
        console.print_json(data={"analysis": result})
    elif config.output.format == "plain":
        console.print(result, highlight=False)
    else:
        console.print()
        console.print(
            Panel(
                Markdown(result),
                title="Analysis Results",
                border_style="green",
                padding=(1, 2),
            )
        )

    console.print(f"[dim]Audit log: {runner.audit.log_path}[/dim]")


@app.command()
def tools(
    config_path: Annotated[
        str | None, typer.Option("--config", "-c", help="Config file path.")
    ] = None,
) -> None:
    """List all registered tools."""
    load_config(config_path)

    table = Table(title="Registered Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Description")

    for tool in available_tools():
        tags = tool.tags or []
        category = next((t for t in tags if t in ("passive", "active", "analysis")), "unknown")
        description = tool.description or ""
        table.add_row(
            tool.name,
            category,
            description[:60] + "..." if len(description) > 60 else description,
        )

    console.print(table)


if __name__ == "__main__":
    app()
