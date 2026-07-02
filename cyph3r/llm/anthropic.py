"""Anthropic Claude reference implementation of :class:`LLMProvider`.

Uses the official ``anthropic`` SDK with a manual tool-use loop (one turn per
``run_turn`` call); the agent drives the loop so it can intercept tool calls for
self-repair, schema refresh, and learning. The SDK is imported lazily so importing this
module does not require the package to be installed.
"""

from __future__ import annotations

from typing import Any

from .base import ToolCall, ToolSpec, TurnResult


class AnthropicProvider:
    def __init__(
        self,
        model: str = "claude-opus-4-8",
        max_tokens: int = 16000,
        api_key: str | None = None,
    ) -> None:
        import anthropic  # lazy

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def run_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
    ) -> TurnResult:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            tools=[
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ],
            messages=messages,
        )

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
            elif block.type == "text":
                text_parts.append(block.text)

        # Pass the SDK content blocks straight back as the assistant turn; the SDK
        # accepts its own response content as input on the next request, preserving
        # thinking and tool_use blocks.
        assistant_message = {"role": "assistant", "content": response.content}
        return TurnResult(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            text="".join(text_parts),
            stop_reason=response.stop_reason or "end_turn",
        )
