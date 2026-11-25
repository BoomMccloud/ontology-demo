"""Google Gemini provider adapter using `google-genai`."""

from __future__ import annotations

import threading
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from stock_ontology.config import Settings
from stock_ontology.llm.base import (
    BaseLLMProvider,
    LLMProviderError,
    ProviderConfigError,
    classify_error,
)
from stock_ontology.llm.prompts import strip_json_fences

T = TypeVar("T", bound=BaseModel)


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
            return self._parse_structured(response, schema)
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
                vectors.extend(self._batch_vectors(result, len(batch)))
        except Exception as exc:  # noqa: BLE001
            raise classify_error(exc, provider=self.name, model=self.embedding_model) from exc
        return vectors

    def _parse_structured(self, response: types.GenerateContentResponse, schema: type[T]) -> T:
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

    def _batch_vectors(self, result: types.EmbedContentResponse, expected: int) -> list[list[float]]:
        if not result.embeddings or len(result.embeddings) != expected:
            raise LLMProviderError(
                "Gemini embedding API returned unexpected embedding count.",
                provider=self.name,
                model=self.embedding_model,
                error_kind="invalid_response",
            )
        if any(not emb.values for emb in result.embeddings):
            raise LLMProviderError(
                "Gemini embedding API returned empty vector values.",
                provider=self.name,
                model=self.embedding_model,
                error_kind="invalid_response",
            )
        return [list(emb.values) for emb in result.embeddings]
