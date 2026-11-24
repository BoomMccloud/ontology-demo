"""Anthropic Messages API provider adapter (chat, structured tool output, agent tools)."""

from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from stock_ontology.config import Settings
from stock_ontology.llm.base import (
    BaseLLMProvider,
    HttpJsonClientMixin,
    LLMProviderError,
    ProviderConfigError,
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
