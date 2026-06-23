"""REST API for Cyph3r, built on FastAPI.

Run with: ``uvicorn cyph3r.api:app``. The agent and Neo4j client are created once on
startup and shared across requests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .factory import build_agent

    agent, client = build_agent()
    _state["agent"] = agent
    _state["client"] = client
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


def _serialize_steps(steps) -> list[dict[str, Any]]:
    return [
        {
            "tool": s.tool,
            "arguments": s.arguments,
            "output": s.output,
            "is_error": s.is_error,
        }
        for s in steps
    ]


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    agent = _state["agent"]
    result = agent.chat(request.session_id, request.message)
    return {"answer": result.answer, "steps": _serialize_steps(result.steps)}


@app.post("/improve")
def improve(request: ImproveRequest) -> dict[str, Any]:
    agent = _state["agent"]
    report = agent.improve(request.session_id, scope=request.scope)
    return {
        "summary": report.summary,
        "answer": report.answer,
        "steps": _serialize_steps(report.steps),
    }


@app.get("/sessions")
def list_sessions() -> dict[str, Any]:
    agent = _state["agent"]
    prefix = agent.meta_prefix
    rows = agent.client.read(
        f"MATCH (s:`{prefix}Session`) "
        f"RETURN s.id AS id, s.created_at AS created_at ORDER BY created_at DESC"
    )
    return {"sessions": rows}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    agent = _state["agent"]
    prefix = agent.meta_prefix
    agent.client.write(
        f"MATCH (s:`{prefix}Session` {{id: $sid}}) "
        f"OPTIONAL MATCH (s)-[:HAS_MESSAGE]->(m:`{prefix}Message`) "
        f"DETACH DELETE s, m",
        {"sid": session_id},
    )
    return {"deleted": session_id}
