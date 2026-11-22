"""OpenAI-compatible LLM and embedding providers (DashScope/Qwen, OpenAI, generic endpoints)."""

from __future__ import annotations

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


class OpenAICompatibleProvider(HttpJsonClientMixin, BaseLLMProvider):
    """Generic OpenAI-compatible `/chat/completions` + `/embeddings` provider."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str | None,
        base_url: str | None,
        chat_model: str,
        embedding_model: str | None = None,
        embedding_dim: int = 768,
        embedding_batch_size: int = 50,
        embedding_max_chars: int | None = None,
        extra_chat_body: dict[str, Any] | None = None,
        timeout: float = 120.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.api_key = (api_key or "").strip() or None
        self.base_url = (base_url or "").strip().rstrip("/") or None
        self.chat_model = chat_model
        self.embedding_model = (embedding_model or "").strip() or None
        self.embedding_dim = embedding_dim
        self.embedding_batch_size = max(1, embedding_batch_size)
        self.embedding_max_chars = embedding_max_chars
        self.extra_chat_body = dict(extra_chat_body) if extra_chat_body else {}
        self.supports_chat = bool(self.chat_model)
        self.supports_embeddings = bool(self.embedding_model)
        self._init_http(http_client=http_client, timeout=timeout)

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.chat_model)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict[str, Any], *, model: str | None) -> dict[str, Any]:
        if not self.api_key or not self.base_url or not self.chat_model:
            raise ProviderConfigError(
                f"Provider {self.name!r} is missing required API key, base URL, or model.",
                provider=self.name,
                model=model,
            )
        return self._post_json(
            url=f"{self.base_url}{path}",
            headers=self._headers(),
            payload=payload,
            provider=self.name,
            model=model,
        )

    def generate_structured(
        self, *, system_instruction: str, prompt: str, schema: type[T]
    ) -> T:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                },
            },
            **self.extra_chat_body,
        }
        data = self._post("/chat/completions", payload, model=self.chat_model)
        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError(
                f"{self.name} returned no choices for structured output.",
                provider=self.name,
                model=self.chat_model,
                error_kind="invalid_response",
            )
        content = (choices[0].get("message") or {}).get("content") or ""
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError(
                f"{self.name} returned empty content for structured output.",
                provider=self.name,
                model=self.chat_model,
                error_kind="invalid_response",
            )
        try:
            return schema.model_validate_json(strip_json_fences(content))
        except Exception as exc:  # noqa: BLE001
            raise classify_error(exc, provider=self.name, model=self.chat_model) from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.supports_embeddings or not self.embedding_model:
            raise ProviderConfigError(
                f"Provider {self.name!r} has no embedding model configured.",
                provider=self.name,
                model=self.embedding_model,
            )

        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.embedding_batch_size):
            raw_batch = texts[i : i + self.embedding_batch_size]
            batch: list[str] = []
            for item in raw_batch:
                cleaned = item.strip()
                if self.embedding_max_chars is not None:
                    cleaned = cleaned[: self.embedding_max_chars]
                batch.append(cleaned or "empty")

            data = self._post(
                "/embeddings",
                {
                    "model": self.embedding_model,
                    "input": batch,
                    "dimensions": self.embedding_dim,
                },
                model=self.embedding_model,
            )
            items = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
            if len(items) != len(batch):
                raise LLMProviderError(
                    f"{self.name} embedding API returned unexpected count ({len(items)} != {len(batch)}).",
                    provider=self.name,
                    model=self.embedding_model,
                    error_kind="invalid_response",
                )
            for item in items:
                emb = item.get("embedding")
                if not emb:
                    raise LLMProviderError(
                        f"{self.name} embedding API returned empty vector.",
                        provider=self.name,
                        model=self.embedding_model,
                        error_kind="invalid_response",
                    )
                vectors.append(list(emb))
        return vectors

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        oai_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instruction}
        ]
        last_assistant_call_ids: list[str] = []

        for msg_idx, msg in enumerate(messages):
            role = msg["role"]
            if role == "user":
                oai_messages.append({"role": "user", "content": msg["text"]})
            elif role == "model":
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.get("text") or "",
                }
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    current_ids: list[str] = []
                    serialized_tcs: list[dict[str, Any]] = []
                    for idx, tc in enumerate(tool_calls):
                        cid = tc.get("call_id") or f"call_m{msg_idx}_{idx}"
                        current_ids.append(cid)
                        serialized_tcs.append(
                            {
                                "id": cid,
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json_dumps_args(tc.get("args", {})),
                                },
                            }
                        )
                    assistant_msg["tool_calls"] = serialized_tcs
                    last_assistant_call_ids = current_ids
                else:
                    last_assistant_call_ids = []
                oai_messages.append(assistant_msg)
            elif role == "tool":
                for idx, resp in enumerate(msg["responses"]):
                    fallback_cid = (
                        last_assistant_call_ids[idx]
                        if idx < len(last_assistant_call_ids)
                        else f"call_m{msg_idx}_{idx}"
                    )
                    oai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": resp.get("call_id") or fallback_cid,
                            "content": json_dumps_args(resp["response"]),
                        }
                    )

        tools = [{"type": "function", "function": schema} for schema in tool_schemas]
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "temperature": 0.2,
            "messages": oai_messages,
            "tools": tools,
            **self.extra_chat_body,
        }
        data = self._post("/chat/completions", payload, model=self.chat_model)
        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError(
                f"{self.name} returned no choices in agent reply.",
                provider=self.name,
                model=self.chat_model,
                error_kind="invalid_response",
            )
        msg_obj = choices[0].get("message") or {}

        parsed_tool_calls: list[ToolCall] = []
        for raw_tc in msg_obj.get("tool_calls") or []:
            fn = raw_tc.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            raw_args = fn.get("arguments") or "{}"
            parsed_args = parse_tool_args(raw_args)
            parsed_tool_calls.append(
                ToolCall(
                    name=name,
                    args=parsed_args,
                    call_id=raw_tc.get("id"),
                )
            )

        content = msg_obj.get("content")
        text = content.strip() if isinstance(content, str) and content.strip() else None
        return AgentTurn(
            text=text,
            tool_calls=parsed_tool_calls,
            provider=self.name,
            model=self.chat_model,
        )


def json_dumps_args(value: Any) -> str:
    import json

    return json.dumps(value)


def parse_tool_args(raw_args: Any) -> dict[str, Any]:
    import json

    if isinstance(raw_args, dict):
        return dict(raw_args)
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


class DashScopeProvider(OpenAICompatibleProvider):
    """Alibaba Cloud DashScope / Qwen OpenAI-compatible provider."""

    def __init__(
        self, settings: Settings, http_client: httpx.Client | None = None
    ) -> None:
        self.settings = settings
        super().__init__(
            name="dashscope",
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_api_url,
            chat_model=settings.dashscope_model,
            embedding_model=settings.dashscope_embedding_model,
            embedding_dim=settings.embedding_dim,
            embedding_batch_size=10,
            embedding_max_chars=4000,
            extra_chat_body={"enable_thinking": False},
            timeout=settings.llm_timeout_seconds,
            http_client=http_client,
        )


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI REST API provider."""

    def __init__(
        self, settings: Settings, http_client: httpx.Client | None = None
    ) -> None:
        self.settings = settings
        super().__init__(
            name="openai",
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_url,
            chat_model=settings.openai_model,
            embedding_model=settings.openai_embedding_model,
            embedding_dim=settings.embedding_dim,
            embedding_batch_size=50,
            embedding_max_chars=None,
            extra_chat_body=None,
            timeout=settings.llm_timeout_seconds,
            http_client=http_client,
        )


def create_openai_compat_provider(
    settings: Settings, http_client: httpx.Client | None = None
) -> OpenAICompatibleProvider:
    """Build generic OpenAI-compatible provider from `settings.openai_compat_*`."""
    return OpenAICompatibleProvider(
        name="openai_compatible",
        api_key=settings.openai_compat_api_key,
        base_url=settings.openai_compat_api_url,
        chat_model=settings.openai_compat_model or "",
        embedding_model=settings.openai_compat_embedding_model,
        embedding_dim=settings.embedding_dim,
        embedding_batch_size=50,
        embedding_max_chars=None,
        extra_chat_body=None,
        timeout=settings.llm_timeout_seconds,
        http_client=http_client,
    )
