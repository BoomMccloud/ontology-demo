"""Pydantic AI `Model` adapter over the existing `LLMClient` model layer.

The adapter keeps `LLMClient` / `LLMRouter` (fallback, error classification,
cooldowns) and every provider as they are. It only translates Pydantic AI
message history into the normalized message dicts `generate_agent_reply`
already accepts, and its `AgentTurn` back into a `ModelResponse`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from stock_ontology.llm.base import AgentTurn, LLMClient

# `provider_details` keys used to round-trip what providers need on later turns.
RAW_CONTENT_KEY = "raw_content"
CALL_ID_KEY = "call_id"


def _original_call_id(part: ToolCallPart) -> str | None:
    """The provider's own call id, which may be `None` where Pydantic AI generated one."""
    details = part.provider_details or {}
    if CALL_ID_KEY in details:
        return details[CALL_ID_KEY]
    return part.tool_call_id


def to_llm_messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    """Convert Pydantic AI history into the message dicts `LLMClient.generate_agent_reply` takes."""
    out: list[dict[str, Any]] = []
    call_ids: dict[str, str | None] = {}
    for message in messages:
        if isinstance(message, ModelResponse):
            text_parts = [p.content for p in message.parts if isinstance(p, TextPart)]
            tool_calls = []
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    original = _original_call_id(part)
                    call_ids[part.tool_call_id] = original
                    tool_calls.append(
                        {"name": part.tool_name, "args": part.args_as_dict(), "call_id": original}
                    )
            model_msg: dict[str, Any] = {
                "role": "model",
                "text": "".join(text_parts) if text_parts else None,
                "tool_calls": tool_calls,
            }
            raw_content = (message.provider_details or {}).get(RAW_CONTENT_KEY)
            if raw_content is not None:
                model_msg[RAW_CONTENT_KEY] = raw_content
            out.append(model_msg)
        elif isinstance(message, ModelRequest):
            responses: list[dict[str, Any]] = []
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    content = part.content
                    text = content if isinstance(content, str) else "".join(str(c) for c in content)
                    out.append({"role": "user", "text": text})
                elif isinstance(part, ToolReturnPart):
                    content = part.content
                    if getattr(part, "outcome", None) == "retried":
                        content = {"error": str(content)}
                    responses.append(
                        {
                            "name": part.tool_name,
                            "call_id": call_ids.get(part.tool_call_id, part.tool_call_id),
                            "response": content,
                        }
                    )
            if responses:
                out.append({"role": "tool", "responses": responses})
    return out


def from_agent_turn(turn: AgentTurn) -> ModelResponse:
    """Convert a normalized `AgentTurn` into a Pydantic AI `ModelResponse`."""
    parts: list[Any] = []
    if turn.text or not turn.tool_calls:
        parts.append(TextPart(content=turn.text or ""))
    for tc in turn.tool_calls:
        kwargs: dict[str, Any] = {"provider_details": {CALL_ID_KEY: tc.call_id}}
        if tc.call_id is not None:
            kwargs["tool_call_id"] = tc.call_id
        parts.append(ToolCallPart(tool_name=tc.name, args=dict(tc.args), **kwargs))
    details = {RAW_CONTENT_KEY: turn.raw_content} if turn.raw_content is not None else None
    return ModelResponse(
        parts=parts,
        model_name=turn.model,
        provider_name=turn.provider,
        provider_details=details,
    )


class LLMClientModel(Model):
    """Pydantic AI model that answers through an existing `LLMClient` (usually `LLMRouter`)."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        system_instruction: str,
        on_turn: Callable[[AgentTurn], None] | None = None,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.system_instruction = system_instruction
        self.on_turn = on_turn

    @property
    def model_name(self) -> str:
        return "llm-client"

    @property
    def system(self) -> str:
        return "stock-ontology"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        tool_schemas = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.parameters_json_schema,
            }
            for tool in model_request_parameters.function_tools
        ]
        turn = self.llm.generate_agent_reply(
            system_instruction=self.system_instruction,
            messages=to_llm_messages(messages),
            tool_schemas=tool_schemas,
        )
        if self.on_turn is not None:
            self.on_turn(turn)
        return from_agent_turn(turn)
