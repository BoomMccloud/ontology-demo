"""Anthropic Messages API provider adapter (chat, structured tool output, agent tools)."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from stock_ontology.config import Settings
from stock_ontology.llm.base import (
    AgentTurn,
    BaseLLMProvider,
    HttpJsonClientMixin,
    LLMProviderError,
    ProviderConfigError,
    ToolCall,
    classify_error,
)
from stock_ontology.llm.prompts import strip_json_fences

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(HttpJsonClientMixin, BaseLLMProvider):
    """Anthropic `/v1/messages` adapter for structured extraction and tool-calling agent."""

    def __init__(
        self, settings: Settings, http_client: httpx.Client | None = None
    ) -> None:
        self.settings = settings
        self.name = "anthropic"
        self.chat_model = settings.anthropic_model
        self.embedding_model = None
        self.supports_chat = True
        self.supports_embeddings = False
        self._api_key = (settings.anthropic_api_key or "").strip() or None
        self._base_url = settings.anthropic_api_url.strip().rstrip("/")
        self._init_http(http_client=http_client, timeout=settings.llm_timeout_seconds)

    def is_configured(self) -> bool:
        return bool(self._api_key and self._base_url and self.chat_model)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _post_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key or not self._base_url:
            raise ProviderConfigError(
                "ANTHROPIC_API_KEY is not set.",
                provider=self.name,
                model=self.chat_model,
            )
        return self._post_json(
            url=f"{self._base_url}/messages",
            headers=self._headers(),
            payload=payload,
            provider=self.name,
            model=self.chat_model,
        )

    def generate_structured(
        self, *, system_instruction: str, prompt: str, schema: type[T]
    ) -> T:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "system": system_instruction,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": schema.__name__,
                    "description": f"Return structured {schema.__name__} JSON output.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            "tool_choice": {"type": "tool", "name": schema.__name__},
        }
        data = self._post_messages(payload)
        blocks = data.get("content") or []

        for block in blocks:
            if block.get("type") == "tool_use" and (
                block.get("name") == schema.__name__ or "input" in block
            ):
                try:
                    return schema.model_validate(block.get("input"))
                except Exception as exc:  # noqa: BLE001
                    raise classify_error(exc, provider=self.name, model=self.chat_model) from exc

        text_parts = [
            block.get("text", "")
            for block in blocks
            if block.get("type") == "text" and isinstance(block.get("text"), str)
        ]
        joined = "\n".join(p for p in text_parts if p).strip()
        if joined:
            try:
                return schema.model_validate_json(strip_json_fences(joined))
            except Exception as exc:  # noqa: BLE001
                raise classify_error(exc, provider=self.name, model=self.chat_model) from exc

        raise LLMProviderError(
            "Anthropic returned no structured tool_use or JSON text block.",
            provider=self.name,
            model=self.chat_model,
            error_kind="invalid_response",
        )

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        anth_messages: list[dict[str, Any]] = []
        last_assistant_call_ids: list[str] = []

        def _append_msg(role: str, blocks: list[dict[str, Any]]) -> None:
            if not blocks:
                return
            if anth_messages and anth_messages[-1]["role"] == role:
                anth_messages[-1]["content"].extend(blocks)
            else:
                anth_messages.append({"role": role, "content": blocks})

        for msg_idx, msg in enumerate(messages):
            role = msg["role"]
            if role == "user":
                _append_msg("user", [{"type": "text", "text": msg["text"]}])
            elif role == "model":
                blocks: list[dict[str, Any]] = []
                if msg.get("text"):
                    blocks.append({"type": "text", "text": msg["text"]})
                tool_calls = msg.get("tool_calls") or []
                current_ids: list[str] = []
                for idx, tc in enumerate(tool_calls):
                    cid = tc.get("call_id") or f"toolu_m{msg_idx}_{idx}"
                    current_ids.append(cid)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": cid,
                            "name": tc["name"],
                            "input": dict(tc.get("args") or {}),
                        }
                    )
                last_assistant_call_ids = current_ids
                _append_msg("assistant", blocks)
            elif role == "tool":
                result_blocks: list[dict[str, Any]] = []
                for idx, resp in enumerate(msg["responses"]):
                    fallback_cid = (
                        last_assistant_call_ids[idx]
                        if idx < len(last_assistant_call_ids)
                        else f"toolu_m{msg_idx}_{idx}"
                    )
                    result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": resp.get("call_id") or fallback_cid,
                            "content": json.dumps(resp["response"]),
                        }
                    )
                _append_msg("user", result_blocks)

        tools = [
            {
                "name": schema["name"],
                "description": schema["description"],
                "input_schema": schema["parameters"],
            }
            for schema in tool_schemas
        ]
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "max_tokens": 4096,
            "temperature": 0.2,
            "system": system_instruction,
            "messages": anth_messages,
            "tools": tools,
        }
        data = self._post_messages(payload)
        blocks = data.get("content") or []
        if not blocks:
            raise LLMProviderError(
                "Anthropic returned empty content in agent reply.",
                provider=self.name,
                model=self.chat_model,
                error_kind="invalid_response",
            )

        text_parts: list[str] = []
        parsed_calls: list[ToolCall] = []
        for block in blocks:
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                text_parts.append(block["text"].strip())
            elif btype == "tool_use" and block.get("name"):
                raw_input = block.get("input")
                parsed_calls.append(
                    ToolCall(
                        name=block["name"],
                        args=dict(raw_input) if isinstance(raw_input, dict) else {},
                        call_id=block.get("id"),
                    )
                )

        text = "\n".join(text_parts) if text_parts else None
        return AgentTurn(
            text=text,
            tool_calls=parsed_calls,
            provider=self.name,
            model=self.chat_model,
        )
