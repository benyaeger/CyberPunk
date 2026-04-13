"""CLI entry point: Typer app with all commands and flags."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from cyberpunk import __app_name__, __version__
from cyberpunk.agent.orchestrator import AgentOrchestrator
from cyberpunk.core.config import load_config
from cyberpunk.tools import ToolRegistry

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
        typer.Option("--version", callback=_version_callback, is_eager=True,
                      help="Show version."),
    ] = False,
) -> None:
    """CyberPunk — network intelligence powered by local LLM."""


@app.command()
def analyze(
    stealth: Annotated[bool, typer.Option("--stealth", "-s", help="Passive-only mode.")] = False,
    output: Annotated[str, typer.Option("--output", "-o", help="Output format: rich, json, plain.")] = "rich",
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show tool calls and reasoning.")] = False,
    subnet: Annotated[str | None, typer.Option("--subnet", help="Target subnet (e.g. 192.168.1.0/24).")] = None,
    config_path: Annotated[str | None, typer.Option("--config", "-c", help="Config file path.")] = None,
) -> None:
    """Run a network analysis."""
    config = load_config(config_path)

    # Override output format from flag
    if output != "rich":
        config.output.format = output

    # Health check
    from cyberpunk.agent.llm_client import OllamaClient

    llm_check = OllamaClient(
        model=config.llm.model,
        base_url=config.llm.base_url,
        timeout=config.llm.timeout,
    )
    ok, msg = llm_check.health_check()
    if not ok:
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1)

    if verbose:
        console.print(f"[dim]{msg}[/dim]")

    # Discover tools
    registry = ToolRegistry()
    registry.discover()

    tool_count = len(registry.get_definitions(stealth=stealth))
    mode = "stealth" if stealth else "full"
    console.print(
        Panel(
            Text.from_markup(
                f"[bold cyan]{__app_name__}[/bold cyan] Network Analysis\n"
                f"Mode: [{'yellow' if stealth else 'green'}]{mode}[/{'yellow' if stealth else 'green'}] "
                f"| Tools: {tool_count} | Model: {config.llm.model}"
            ),
            border_style="cyan",
        )
    )

    # Run agent
    orchestrator = AgentOrchestrator(
        config=config,
        registry=registry,
        console=console,
        verbose=verbose,
    )

    try:
        result = orchestrator.run(command="analyze", stealth=stealth, subnet=subnet)
    except Exception as e:
        console.print(f"[red]Agent error:[/red] {e}")
        raise typer.Exit(1)

    # Output
    if config.output.format == "json":
        console.print_json(data={"analysis": result})
    elif config.output.format == "plain":
        console.print(result, highlight=False)
    else:
        console.print()
        console.print(Panel(Markdown(result), title="Analysis Results", border_style="green", padding=(1, 2)))

    console.print(f"[dim]Audit log: {orchestrator.audit.log_path}[/dim]")


@app.command()
def tools(
    config_path: Annotated[str | None, typer.Option("--config", "-c", help="Config file path.")] = None,
) -> None:
    """List all registered tools."""
    load_config(config_path)
    registry = ToolRegistry()
    registry.discover()

    from rich.table import Table

    table = Table(title="Registered Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Description")
    table.add_column("Platforms")

    for defn in registry.get_definitions():
        table.add_row(
            defn.name,
            defn.category.value,
            defn.description[:60] + "..." if len(defn.description) > 60 else defn.description,
            ", ".join(defn.platform),
        )

    console.print(table)


if __name__ == "__main__":
    app()
