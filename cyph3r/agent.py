"""GraphAgent — the control loop that makes Cyph3r more than an MCP server.

It wires the LLM provider to the graph tools, injects the live schema and recalled
memories into the system prompt, runs a bounded multi-step tool-use loop with Cypher
self-repair, persists conversation history, records learnings, and drives the
continuous-improvement pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import improve
from .graph import GraphClient
from .llm.base import LLMProvider, tool_result_message
from .memory import GraphMemory
from .schema import SchemaState
from .tools import ToolRegistry

_BASE_SYSTEM = """You are Cyph3r, an agent that manages a Neo4j graph through Cypher.

You can read, traverse, create, and modify the graph, and you maintain your own
graph-native memory. Work in steps using the available tools:
- Call get_schema before writing Cypher against an unfamiliar graph.
- Use traverse / find_path to explore how entities connect; prefer them over ad-hoc
  Cypher for relationship questions.
- Use create_relationship (MERGE-based) or write_cypher to modify the graph.
- When a Cypher tool returns an error, read the message, correct the query, and retry.
- Record durable lessons and important facts with remember (kind='insight' for reusable
  lessons), linking them to the entities they concern via 'about'.

When you have enough information to act, act. Be concise. After finishing, give a short,
plain-language answer: what you did or found, and any Cypher that changed the graph."""

_IMPROVE_SYSTEM = """\

You are now running a graph-improvement pass. For each finding, briefly explain the
change and the Cypher, then apply it (propose-then-auto-apply). Use create_relationship
to connect orphan nodes when the right link is clear from context, and write_cypher to
fix duplicates or inconsistencies. Do not modify the agent's own memory nodes. Record an
insight summarizing what you changed."""


@dataclass
class Step:
    tool: str
    arguments: dict[str, Any]
    output: Any
    is_error: bool


@dataclass
class ChatResult:
    answer: str
    steps: list[Step] = field(default_factory=list)


@dataclass
class ImproveReport:
    summary: str
    answer: str
    steps: list[Step] = field(default_factory=list)


class GraphAgent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        memory: GraphMemory,
        schema_state: SchemaState,
        client: GraphClient,
        meta_prefix: str = "Cyph3r",
        max_steps: int = 16,
        max_repair_attempts: int = 3,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.memory = memory
        self.schema_state = schema_state
        self.client = client
        self.meta_prefix = meta_prefix
        self.max_steps = max_steps
        self.max_repair_attempts = max_repair_attempts

    # -- public API ----------------------------------------------------------

    def chat(self, session_id: str, user_message: str) -> ChatResult:
        answer, steps = self._run_loop(session_id, user_message, system_extra="")
        self._record_session_learning(user_message, steps)
        return ChatResult(answer=answer, steps=steps)

    def improve(self, session_id: str, scope: str | None = None) -> ImproveReport:
        findings = improve.analyze(self.client, meta_prefix=self.meta_prefix)
        if findings.is_empty():
            return ImproveReport(
                summary=findings.summary(),
                answer="No structural issues detected; nothing to improve.",
            )
        prompt = (
            "Improve the graph based on these findings"
            + (f" (scope: {scope})" if scope else "")
            + ":\n\n"
            + findings.summary()
        )
        answer, steps = self._run_loop(session_id, prompt, system_extra=_IMPROVE_SYSTEM)
        self._safe(
            lambda: self.memory.record_memory(
                f"Ran improvement pass. {findings.summary()}",
                kind="insight",
            )
        )
        return ImproveReport(summary=findings.summary(), answer=answer, steps=steps)

    # -- core loop -----------------------------------------------------------

    def _run_loop(
        self,
        session_id: str,
        user_message: str,
        system_extra: str,
    ) -> tuple[str, list[Step]]:
        self._safe(lambda: self.memory.ensure_session(session_id))
        history = self._safe(lambda: self.memory.load_history(session_id)) or []

        messages: list[dict[str, Any]] = list(history)
        messages.append({"role": "user", "content": user_message})

        system = self._build_system(user_message, system_extra)
        tool_specs = self.registry.specs()

        steps: list[Step] = []
        answer = ""
        consecutive_errors = 0

        for _ in range(self.max_steps):
            turn = self.provider.run_turn(
                system=system, messages=messages, tools=tool_specs
            )
            messages.append(turn.assistant_message)

            if not turn.tool_calls:
                answer = turn.text
                break

            results: list[tuple[str, Any, bool]] = []
            had_error = False
            for call in turn.tool_calls:
                output, is_error = self.registry.execute(call.name, call.input)
                steps.append(Step(call.name, call.input, output, is_error))
                results.append((call.id, output, is_error))
                had_error = had_error or is_error

            messages.append(tool_result_message(results))

            consecutive_errors = consecutive_errors + 1 if had_error else 0
            if consecutive_errors > self.max_repair_attempts:
                answer = (
                    "Stopped after repeated tool errors that could not be repaired. "
                    "See the steps for the last error."
                )
                break

        self._persist_turn(session_id, user_message, answer)
        return answer, steps

    # -- helpers -------------------------------------------------------------

    def _build_system(self, user_message: str, system_extra: str) -> str:
        schema_text = self._safe(self.schema_state.render) or "Schema unavailable."
        memories = self._safe(lambda: self.memory.recall(limit=5)) or []
        parts = [_BASE_SYSTEM]
        if system_extra:
            parts.append(system_extra)
        parts.append("Current graph schema:\n" + schema_text)
        if memories:
            recalled = "\n".join(f"- ({m.kind}) {m.content}" for m in memories)
            parts.append("Relevant memories from past sessions:\n" + recalled)
        return "\n\n".join(parts)

    def _persist_turn(self, session_id: str, user_message: str, answer: str) -> None:
        self._safe(lambda: self.memory.append_message(session_id, "user", user_message))
        if answer:
            self._safe(
                lambda: self.memory.append_message(session_id, "assistant", answer)
            )

    def _record_session_learning(self, user_message: str, steps: list[Step]) -> None:
        writes = [s for s in steps if s.tool in ("write_cypher", "create_relationship")]
        verb = "modified the graph" if writes else "answered a question"
        content = (
            f"User request: {user_message[:280]}. "
            f"Resolved with {len(steps)} tool call(s); {verb}."
        )
        self._safe(lambda: self.memory.record_memory(content, kind="insight"))

    @staticmethod
    def _safe(fn: Any) -> Any:
        """Run a memory/schema side-effect, swallowing backend hiccups.

        Bookkeeping failures should never crash a chat turn.
        """
        try:
            return fn()
        except Exception:
            return None
