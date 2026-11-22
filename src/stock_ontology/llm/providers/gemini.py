"""Google Gemini provider adapter using `google-genai`."""

from __future__ import annotations

import threading
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from stock_ontology.config import Settings
from stock_ontology.llm.base import (
    AgentTurn,
    BaseLLMProvider,
    LLMProviderError,
    ProviderConfigError,
    ToolCall,
    classify_error,
)
from stock_ontology.llm.prompts import strip_json_fences

T = TypeVar("T", bound=BaseModel)
_THOUGHT_SIGNATURE_SKIP = b"skip_thought_signature_validator"


class GeminiProvider(BaseLLMProvider):
    """Production Gemini API adapter using `google-genai`."""

    def __init__(self, settings: Settings, client: genai.Client | None = None) -> None:
        self.settings = settings
        self.name = "gemini"
        self.chat_model = settings.gemini_model
        self.embedding_model = settings.embedding_model
        self.supports_chat = True
        self.supports_embeddings = True
        self._client = client
        self._owns_client = client is None
        self._lock = threading.Lock()

    def is_configured(self) -> bool:
        return self._client is not None or bool((self.settings.gemini_api_key or "").strip())

    def _get_client(self) -> genai.Client:
        with self._lock:
            if self._client is None:
                api_key = (self.settings.gemini_api_key or "").strip()
                if not api_key:
                    raise ProviderConfigError(
                        "GEMINI_API_KEY is not set. Add it to `.env` or export GEMINI_API_KEY before running live Gemini calls.",
                        provider=self.name,
                        model=self.chat_model,
                    )
                timeout_ms = max(1, int(round(self.settings.llm_timeout_seconds * 1000)))
                self._client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=timeout_ms),
                )
            return self._client

    def close(self) -> None:
        """Close the underlying `google-genai` client if owned by this provider."""
        with self._lock:
            if self._client is not None and self._owns_client:
                close_fn = getattr(self._client, "close", None)
                if callable(close_fn):
                    close_fn()
                self._client = None

    def generate_structured(
        self, *, system_instruction: str, prompt: str, schema: type[T]
    ) -> T:
        client = self._get_client()
        try:
            response = client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1,
                ),
            )
            if response.parsed is not None and isinstance(response.parsed, schema):
                return response.parsed
            if not response.text or not response.text.strip():
                raise LLMProviderError(
                    "Gemini returned an empty structured response.",
                    provider=self.name,
                    model=self.chat_model,
                    error_kind="invalid_response",
                )
            return schema.model_validate_json(strip_json_fences(response.text))
        except Exception as exc:  # noqa: BLE001
            raise classify_error(exc, provider=self.name, model=self.chat_model) from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        vectors: list[list[float]] = []
        batch_size = 50
        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                # Wrap each string in its own Content so multimodal embedding models (e.g.
                # gemini-embedding-2) do not merge consecutive strings into one request.
                batch_contents = [
                    types.Content(parts=[types.Part.from_text(text=item.strip() or "empty")])
                    for item in batch
                ]
                result = client.models.embed_content(
                    model=self.embedding_model or self.settings.embedding_model,
                    contents=batch_contents,
                    config=types.EmbedContentConfig(
                        output_dimensionality=self.settings.embedding_dim
                    ),
                )
                if not result.embeddings or len(result.embeddings) != len(batch):
                    raise LLMProviderError(
                        "Gemini embedding API returned unexpected embedding count.",
                        provider=self.name,
                        model=self.embedding_model,
                        error_kind="invalid_response",
                    )
                for emb in result.embeddings:
                    if not emb.values:
                        raise LLMProviderError(
                            "Gemini embedding API returned empty vector values.",
                            provider=self.name,
                            model=self.embedding_model,
                            error_kind="invalid_response",
                        )
                    vectors.append(list(emb.values))
            return vectors
        except Exception as exc:  # noqa: BLE001
            raise classify_error(exc, provider=self.name, model=self.embedding_model) from exc

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        client = self._get_client()
        contents: list[types.Content] = []
        for msg in messages:
            role = msg["role"]
            raw_content = msg.get("raw_content")
            if isinstance(raw_content, types.Content):
                contents.append(raw_content)
            elif role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=msg["text"])])
                )
            elif role == "model":
                parts: list[types.Part] = []
                if msg.get("text"):
                    parts.append(types.Part.from_text(text=msg["text"]))
                for tc in msg.get("tool_calls", []):
                    fc_kwargs: dict[str, Any] = {
                        "name": tc["name"],
                        "args": dict(tc.get("args") or {}),
                    }
                    if tc.get("call_id"):
                        fc_kwargs["id"] = tc["call_id"]
                    # Reconstructed non-Gemini tool calls lack an opaque thought signature.
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(**fc_kwargs),
                            thought_signature=_THOUGHT_SIGNATURE_SKIP,
                        )
                    )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                parts = []
                for resp in msg["responses"]:
                    fr_kwargs: dict[str, Any] = {
                        "name": resp["name"],
                        "response": {"result": resp["response"]},
                    }
                    if resp.get("call_id"):
                        fr_kwargs["id"] = resp["call_id"]
                    parts.append(
                        types.Part(function_response=types.FunctionResponse(**fr_kwargs))
                    )
                if parts:
                    contents.append(types.Content(role="user", parts=parts))

        declarations = [
            types.FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters_json_schema=schema["parameters"],
            )
            for schema in tool_schemas
        ]
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": 0.2,
        }
        if declarations:
            config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]

        try:
            response = client.models.generate_content(
                model=self.chat_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:  # noqa: BLE001
            raise classify_error(exc, provider=self.name, model=self.chat_model) from exc

        candidate_content = (
            response.candidates[0].content
            if response.candidates and response.candidates[0].content is not None
            else None
        )
        tool_calls: list[ToolCall] = []
        if response.function_calls:
            for fc in response.function_calls:
                if fc.name:
                    tool_calls.append(
                        ToolCall(
                            name=fc.name,
                            args=dict(fc.args or {}),
                            call_id=getattr(fc, "id", None),
                        )
                    )

        text: str | None = None
        if candidate_content and candidate_content.parts:
            text_parts = [
                p.text
                for p in candidate_content.parts
                if getattr(p, "text", None) and not getattr(p, "thought", False)
            ]
            if text_parts:
                text = "\n".join(text_parts)
        elif not tool_calls and response.text:
            text = response.text

        return AgentTurn(
            text=text,
            tool_calls=tool_calls,
            raw_content=candidate_content,
            provider=self.name,
            model=self.chat_model,
        )
