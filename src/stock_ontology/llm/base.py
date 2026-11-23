"""Base LLM provider abstractions, normalized turn models, and error classification."""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from stock_ontology.llm.prompts import (
    CONSENSUS_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    build_consensus_prompt,
    STAGE_SCHEMAS,
    STAGE_SYSTEM_PROMPTS,
    build_extraction_prompt,
    build_stage_prompt,
)
from stock_ontology.models import ConsensusSynthesis, ExtractionResult, Node

T = TypeVar("T", bound=BaseModel)

ErrorKind = Literal[
    "rate_limit",
    "auth",
    "not_found",
    "server",
    "network",
    "config",
    "invalid_response",
    "unknown",
]


@dataclass
class ToolCall:
    """Normalized function call requested by the query agent model."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass
class AgentTurn:
    """Single model turn in the agent's tool-calling loop."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_content: Any = None
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False


@dataclass
class ProviderAttempt:
    """Telemetry record for one provider attempt made by `LLMRouter`."""

    provider: str
    model: str | None
    operation: str
    success: bool
    error_kind: ErrorKind | None = None
    error: str | None = None
    status_code: int | None = None


class LLMProviderError(RuntimeError):
    """Normalized error raised by any LLM provider adapter."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str | None = None,
        status_code: int | None = None,
        error_kind: ErrorKind = "unknown",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.error_kind: ErrorKind = error_kind
        self.retryable = retryable


class ProviderConfigError(LLMProviderError):
    """Raised when a provider is missing credentials or requested capabilities."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            model=model,
            status_code=None,
            error_kind="config",
            retryable=True,
        )


class AllProvidersFailedError(LLMProviderError):
    """Raised when every provider in the configured fallback chain fails."""

    def __init__(self, *, operation: str, attempts: list[ProviderAttempt]) -> None:
        self.operation = operation
        self.attempts = attempts
        details = "; ".join(
            f"{att.provider}"
            f"{f'/{att.model}' if att.model else ''}"
            f" [{att.error_kind or 'unknown'}]: {att.error}"
            for att in attempts
        )
        last = attempts[-1] if attempts else None
        super().__init__(
            f"All LLM providers failed for {operation}: {details or 'no providers configured'}",
            provider=last.provider if last else "router",
            model=last.model if last else None,
            status_code=last.status_code if last else None,
            error_kind=last.error_kind or "unknown" if last else "config",
            retryable=False,
        )


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        val = getattr(resp, "status_code", None)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    return None


def classify_status_and_message(status_code: int | None, message: str) -> ErrorKind:
    """Classify an HTTP status code and error message into a normalized `ErrorKind`."""
    low = message.lower()
    if status_code == 429 or any(
        tok in low
        for tok in (
            "resource_exhausted",
            "rate limit",
            "rate_limit",
            "quota",
            "too many requests",
        )
    ):
        return "rate_limit"
    if status_code in (401, 403) or any(
        tok in low
        for tok in (
            "unauthorized",
            "invalid api key",
            "invalid_api_key",
            "api_key_invalid",
            "permission_denied",
            "authentication",
        )
    ):
        return "auth"
    if status_code == 404:
        return "not_found"
    if status_code is not None and 500 <= status_code < 600:
        return "server"
    return "unknown"


def classify_error(
    exc: Exception,
    *,
    provider: str,
    model: str | None = None,
) -> LLMProviderError:
    """Convert an arbitrary provider exception into an `LLMProviderError`."""
    if isinstance(exc, LLMProviderError):
        return exc

    status_code = _extract_status_code(exc)
    message = str(exc).strip() or exc.__class__.__name__

    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError)):
        kind: ErrorKind = "network"
    elif isinstance(exc, (ValidationError, json.JSONDecodeError)):
        kind = "invalid_response"
    else:
        kind = classify_status_and_message(status_code, message)

    return LLMProviderError(
        message,
        provider=provider,
        model=model,
        status_code=status_code,
        error_kind=kind,
        retryable=True,
    )


class LLMClient(Protocol):
    """Abstract interface used by the ingestion pipeline and query agent."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult: ...

    def synthesize_consensus(
        self,
        *,
        company: Node,
        events: list[Node],
        views: list[Node],
        themes: list[Node],
        prior_consensus: Node | None,
    ) -> ConsensusSynthesis: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn: ...


class BaseLLMProvider(ABC):
    """Base adapter for a single concrete LLM/embedding provider."""

    name: str
    chat_model: str
    embedding_model: str | None = None
    supports_chat: bool = True
    supports_embeddings: bool = True

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials and configuration required for live calls exist."""

    @abstractmethod
    def generate_structured(
        self, *, system_instruction: str, prompt: str, schema: type[T]
    ) -> T:
        """Generate structured JSON validated against Pydantic `schema`."""

    @abstractmethod
    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        """Run one tool-calling/conversation turn for the query agent."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed text inputs into vectors; override on embedding-capable providers."""
        raise ProviderConfigError(
            f"Provider {self.name!r} does not support embeddings.",
            provider=self.name,
            model=self.embedding_model,
        )

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        """Extract ontology entities, events, views, themes, and edges from a document."""
        return self.generate_structured(
            system_instruction=EXTRACTION_SYSTEM_PROMPT,
            prompt=build_extraction_prompt(
                text=text,
                source_meta=source_meta,
                existing_catalog=existing_catalog,
                known_facets=known_facets,
            ),
            schema=ExtractionResult,
        )

    def extract_stage(
        self,
        *,
        stage: str,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
        prior: ExtractionResult,
    ) -> ExtractionResult:
        """Run one extraction stage. Its schema only allows the node types that stage owns."""
        result = self.generate_structured(
            system_instruction=STAGE_SYSTEM_PROMPTS[stage],
            prompt=build_stage_prompt(
                text=text,
                source_meta=source_meta,
                existing_catalog=existing_catalog,
                known_facets=known_facets,
                prior=prior,
            ),
            schema=STAGE_SCHEMAS[stage],
        )
        return ExtractionResult(**{name: getattr(result, name) for name in type(result).model_fields})

    def synthesize_consensus(
        self,
        *,
        company: Node,
        events: list[Node],
        views: list[Node],
        themes: list[Node],
        prior_consensus: Node | None,
    ) -> ConsensusSynthesis:
        """Synthesize a company's house consensus view from ontology nodes."""
        return self.generate_structured(
            system_instruction=CONSENSUS_SYSTEM_PROMPT,
            prompt=build_consensus_prompt(
                company=company,
                events=events,
                views=views,
                themes=themes,
                prior_consensus=prior_consensus,
            ),
            schema=ConsensusSynthesis,
        )

    def describe(self) -> dict[str, Any]:
        """Return safe diagnostic metadata (never includes API keys)."""
        return {
            "name": self.name,
            "configured": self.is_configured(),
            "chat_model": self.chat_model,
            "embedding_model": self.embedding_model,
            "supports_chat": self.supports_chat,
            "supports_embeddings": self.supports_embeddings,
        }

    def close(self) -> None:
        """Release any underlying HTTP clients/resources."""


class HttpJsonClientMixin:
    """Thread-safe shared HTTP JSON helper for REST-based provider adapters."""

    _http: httpx.Client | None
    _owns_http: bool
    _timeout: float
    _lock: threading.Lock

    def _init_http(self, *, http_client: httpx.Client | None, timeout: float) -> None:
        self._http = http_client
        self._owns_http = http_client is None
        self._timeout = timeout
        self._lock = threading.Lock()

    def _get_http(self) -> httpx.Client:
        with self._lock:
            if self._http is None:
                self._http = httpx.Client(timeout=self._timeout)
            return self._http

    def _post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        provider: str,
        model: str | None,
    ) -> dict[str, Any]:
        client = self._get_http()
        try:
            resp = client.post(url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise classify_error(exc, provider=provider, model=model) from exc

        if resp.status_code >= 400:
            body_preview = resp.text[:500]
            kind = classify_status_and_message(resp.status_code, body_preview)
            raise LLMProviderError(
                f"{provider} API error {resp.status_code} on {url}: {body_preview}",
                provider=provider,
                model=model,
                status_code=resp.status_code,
                error_kind=kind,
                retryable=True,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMProviderError(
                f"{provider} returned non-JSON response: {resp.text[:300]}",
                provider=provider,
                model=model,
                status_code=resp.status_code,
                error_kind="invalid_response",
                retryable=True,
            ) from exc
        if not isinstance(data, dict):
            raise LLMProviderError(
                f"{provider} returned unexpected JSON payload type {type(data).__name__}.",
                provider=provider,
                model=model,
                status_code=resp.status_code,
                error_kind="invalid_response",
                retryable=True,
            )
        return data

    def close(self) -> None:
        """Close the HTTP client if owned by this provider."""
        with self._lock:
            if self._http is not None and self._owns_http:
                self._http.close()
                self._http = None
