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


def _diagnose(exc: Exception) -> str:
    """Turn a connection failure into an actionable message."""
    text = f"{type(exc).__name__}: {exc}"
    name = type(exc).__name__
    msg = str(exc).lower()
    hints: list[str] = []
    if name == "ServiceUnavailable" or "connection refused" in msg or "unable to retrieve routing" in msg:
        hints.append("Is the DBMS running? Start it in Neo4j Desktop (it must not say STOPPED), then retry.")
        hints.append("Confirm NEO4J_URI matches the Connection URI shown in Desktop (default neo4j://127.0.0.1:7687).")
    if name == "AuthError" or "unauthorized" in msg or "authentication" in msg:
        hints.append("NEO4J_USER / NEO4J_PASSWORD in .env don't match — use the password you set for this DBMS in Neo4j Desktop.")
    if "databasenotfound" in msg or "database does not exist" in msg or "database is unavailable" in msg:
        hints.append("The database named in NEO4J_DATABASE doesn't exist — create it in Neo4j Desktop (Databases → Create database) or point NEO4J_DATABASE at an existing one.")
    if not hints:
        hints.append("Check Neo4j Desktop shows the DBMS as running, and that the URI, user, password, and database in .env match it.")
    return text + "\n\n" + "\n".join(f"• {h}" for h in hints)


@app.command()
def check() -> None:
    """Verify the Neo4j connection configured in .env and print a diagnosis.

    Needs no LLM API key. Run this first when setting up against a local Neo4j.
    """
    from .config import load_settings
    from .graph import Neo4jClient

    settings = load_settings()
    console.print(
        f"Checking [bold]{settings.neo4j_uri}[/] "
        f"(user: {settings.neo4j_user}, database: {settings.neo4j_database})"
    )
    try:
        client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
    except Exception as exc:  # bad URI scheme, driver-level failure
        console.print(Panel(_diagnose(exc), title="connection failed", border_style="red"))
        raise typer.Exit(1)

    try:
        try:
            client.read("RETURN 1 AS ok")
        except Exception as exc:
            console.print(Panel(_diagnose(exc), title="connection failed", border_style="red"))
            raise typer.Exit(1)

        version = "unknown"
        nodes = "?"
        try:
            rows = client.read("CALL dbms.components() YIELD versions RETURN versions[0] AS v")
            if rows:
                version = rows[0]["v"]
        except Exception:
            pass
        try:
            nodes = client.read("MATCH (n) RETURN count(n) AS c")[0]["c"]
        except Exception:
            pass
    finally:
        client.close()

    console.print(
        Panel(
            f"Connected. Neo4j {version}, database [bold]{settings.neo4j_database}[/], "
            f"{nodes} node(s).\n"
            "Next: [bold]cyph3r view[/] to see the graph (no API key needed), "
            "or [bold]cyph3r chat[/] to start building it.",
            title="ok",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
