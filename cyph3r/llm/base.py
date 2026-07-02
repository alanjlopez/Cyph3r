"""Provider-agnostic LLM interface.

The agent talks to any model through :class:`LLMProvider`. Conversation messages use a
neutral role/content shape (a superset of the Anthropic Messages format): ``content`` is
either a string or a list of content blocks. Providers translate to and from their own
wire format; the Anthropic reference implementation uses this shape directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    """A tool the model may call, as name + description + JSON-schema input."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class TurnResult:
    """The outcome of one model turn.

    ``assistant_message`` is the assistant turn to append to history (neutral shape).
    ``tool_calls`` is empty when the model produced a final answer. ``text`` is any
    visible text emitted this turn.
    """

    assistant_message: dict[str, Any]
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    stop_reason: str = "end_turn"


class LLMProvider(Protocol):
    """Anything that can run one turn of a tool-using conversation."""

    def run_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
    ) -> TurnResult:
        ...


def tool_result_message(results: list[tuple[str, Any, bool]]) -> dict[str, Any]:
    """Build a neutral user message carrying tool results.

    ``results`` is a list of ``(tool_call_id, content, is_error)``. Non-string content
    is JSON-encoded so it round-trips cleanly through any provider.
    """
    blocks: list[dict[str, Any]] = []
    for tool_call_id, content, is_error in results:
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        blocks.append(
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": text,
                "is_error": is_error,
            }
        )
    return {"role": "user", "content": blocks}
