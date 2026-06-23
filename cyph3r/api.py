"""REST API for Cyph3r, built on FastAPI.

Run with: ``uvicorn cyph3r.api:app``. The Neo4j client is created on startup and shared
across requests; the LLM agent is built best-effort so the read-only graph endpoints
(``/graph``, ``/graph/view``, ``/sessions``) work even when no API key is configured.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import snapshot, web

_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .config import load_settings
    from .factory import build_agent, build_client

    settings = load_settings()
    client = build_client(settings)
    _state["client"] = client
    _state["meta_prefix"] = settings.cyph3r_meta_label_prefix

    # The agent needs an LLM provider (and thus an API key). Build it best-effort so the
    # viewer and other read endpoints keep working without one.
    try:
        agent, _ = build_agent(settings, client=client)
        _state["agent"] = agent
    except Exception as exc:  # noqa: BLE001 - surfaced via /chat 503
        _state["agent"] = None
        _state["agent_error"] = str(exc)

    try:
        yield
    finally:
        client.close()
        _state.clear()


app = FastAPI(title="Cyph3r", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


class ImproveRequest(BaseModel):
    session_id: str = "default"
    scope: str | None = None


def _require_agent():
    agent = _state.get("agent")
    if agent is None:
        detail = _state.get("agent_error", "LLM not configured")
        raise HTTPException(
            status_code=503,
            detail=f"LLM agent unavailable: {detail}. Set ANTHROPIC_API_KEY to enable chat.",
        )
    return agent


def _serialize_steps(steps) -> list[dict[str, Any]]:
    return [
        {"tool": s.tool, "arguments": s.arguments, "output": s.output, "is_error": s.is_error}
        for s in steps
    ]


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    agent = _require_agent()
    result = agent.chat(request.session_id, request.message)
    return {"answer": result.answer, "steps": _serialize_steps(result.steps)}


@app.post("/improve")
def improve(request: ImproveRequest) -> dict[str, Any]:
    agent = _require_agent()
    report = agent.improve(request.session_id, scope=request.scope)
    return {
        "summary": report.summary,
        "answer": report.answer,
        "steps": _serialize_steps(report.steps),
    }


@app.get("/graph")
def graph(limit: int = 300, include_meta: bool = False) -> dict[str, Any]:
    """Return the current graph as nodes/edges for visualization."""
    return snapshot.graph_snapshot(
        _state["client"],
        meta_prefix=_state["meta_prefix"],
        node_limit=limit,
        include_meta=include_meta,
    )


@app.get("/graph/view", response_class=HTMLResponse)
def graph_view() -> str:
    """Serve the interactive graph viewer page."""
    return web.VIEW_HTML


@app.get("/sessions")
def list_sessions() -> dict[str, Any]:
    prefix = _state["meta_prefix"]
    rows = _state["client"].read(
        f"MATCH (s:`{prefix}Session`) "
        f"RETURN s.id AS id, s.created_at AS created_at ORDER BY created_at DESC"
    )
    return {"sessions": rows}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    prefix = _state["meta_prefix"]
    _state["client"].write(
        f"MATCH (s:`{prefix}Session` {{id: $sid}}) "
        f"OPTIONAL MATCH (s)-[:HAS_MESSAGE]->(m:`{prefix}Message`) "
        f"DETACH DELETE s, m",
        {"sid": session_id},
    )
    return {"deleted": session_id}
