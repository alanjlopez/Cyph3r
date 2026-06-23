"""Terminal chat REPL and improvement command for Cyph3r."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(help="Cyph3r — talk to and improve your Neo4j graph.", no_args_is_help=True)
console = Console()


def _render_steps(steps) -> None:
    for step in steps:
        style = "red" if step.is_error else "cyan"
        query = step.arguments.get("query")
        detail = query if query else step.arguments
        console.print(f"  [{style}]→ {step.tool}[/] {detail}")


@app.command()
def chat(session: str = typer.Option("default", help="Session name to resume.")) -> None:
    """Start an interactive chat against the graph."""
    from .factory import build_agent

    agent, client = build_agent()
    console.print(
        Panel.fit(
            f"Cyph3r chat — session [bold]{session}[/]. Type 'exit' or Ctrl-D to quit.",
            border_style="green",
        )
    )
    try:
        while True:
            try:
                message = console.input("[bold green]you[/] › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not message:
                continue
            if message.lower() in {"exit", "quit"}:
                break
            result = agent.chat(session, message)
            _render_steps(result.steps)
            console.print(Panel(result.answer or "(no answer)", title="cyph3r", border_style="blue"))
    finally:
        client.close()


@app.command()
def improve(
    session: str = typer.Option("default", help="Session name to use."),
    scope: str = typer.Option(None, help="Optional focus for the improvement pass."),
) -> None:
    """Run a continuous-improvement pass over the graph."""
    from .factory import build_agent

    agent, client = build_agent()
    try:
        report = agent.improve(session, scope=scope)
        console.print(Panel(report.summary, title="findings", border_style="yellow"))
        _render_steps(report.steps)
        console.print(Panel(report.answer or "(no changes)", title="cyph3r", border_style="blue"))
    finally:
        client.close()


@app.command()
def view(
    host: str = typer.Option("127.0.0.1", help="Host to bind the viewer server to."),
    port: int = typer.Option(8000, help="Port to serve the viewer on."),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open the browser."),
) -> None:
    """Launch an interactive web view of the current graph.

    Starts the API server and opens the graph viewer in your browser. Works without an
    LLM API key — only a Neo4j connection is required to view the graph.
    """
    import threading
    import webbrowser

    import uvicorn

    url = f"http://{host}:{port}/graph/view"
    console.print(
        Panel.fit(
            f"Graph viewer at [bold]{url}[/]\nPress Ctrl-C to stop.",
            border_style="green",
        )
    )
    if not no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("cyph3r.api:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
