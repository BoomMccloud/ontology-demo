"""Unified LLM router supporting multi-provider fallback, error classification, and cooldowns."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from stock_ontology.config import ProviderName, Settings
from stock_ontology.llm.base import (
    AllProvidersFailedError,
    BaseLLMProvider,
    ProviderAttempt,
    ProviderConfigError,
    classify_error,
)
from stock_ontology.llm.providers import build_provider
from stock_ontology.models import ConsensusSynthesis, ExtractionResult, Node

logger = logging.getLogger(__name__)

_R = TypeVar("_R")
_COOLDOWN_ERROR_KINDS = frozenset({"rate_limit", "auth", "config"})


class LLMRouter:
    """Unified `LLMClient` routing requests across ordered providers with automatic fallback."""

    def __init__(
        self,
        chat_providers: Sequence[BaseLLMProvider],
        embedding_providers: Sequence[BaseLLMProvider] | None = None,
        *,
        fallback_enabled: bool = True,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not chat_providers:
            raise ValueError("LLMRouter requires at least one chat provider.")
        self.chat_providers: list[BaseLLMProvider] = list(chat_providers)
        if embedding_providers is None:
            self.embedding_providers: list[BaseLLMProvider] = [
                p for p in self.chat_providers if getattr(p, "supports_embeddings", True)
            ]
        else:
            self.embedding_providers = list(embedding_providers)

        self.fallback_enabled = fallback_enabled
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}
        self.last_chat_provider: str | None = None
        self.last_embedding_provider: str | None = None
        self.last_attempts: list[ProviderAttempt] = []

    @property
    def primary_provider(self) -> BaseLLMProvider:
        """Primary (highest-priority) chat provider."""
        return self.chat_providers[0]

    def _ordered_candidates(
        self, providers: Sequence[BaseLLMProvider]
    ) -> list[BaseLLMProvider]:
        if not providers:
            return []
        if not self.fallback_enabled:
            return [providers[0]]
        with self._lock:
            now = self._clock()
            active: list[BaseLLMProvider] = []
            cooled: list[BaseLLMProvider] = []
            for p in providers:
                if self._cooldown_until.get(p.name, 0.0) > now:
                    cooled.append(p)
                else:
                    active.append(p)
        # Prefer active providers in priority order; keep cooled providers as last resort.
        return active + cooled

    def _execute(
        self,
        providers: Sequence[BaseLLMProvider],
        operation: str,
        call_fn: Callable[[BaseLLMProvider], _R],
        *,
        is_embedding: bool = False,
    ) -> tuple[_R, BaseLLMProvider, bool]:
        if not providers:
            raise ProviderConfigError(
                f"No providers configured for operation {operation!r}.",
                provider="router",
            )

        candidates = self._ordered_candidates(providers)
        primary_name = providers[0].name
        attempts: list[ProviderAttempt] = []

        for provider in candidates:
            model_name = provider.embedding_model if is_embedding else provider.chat_model
            try:
                result = call_fn(provider)
            except Exception as exc:  # noqa: BLE001
                err = classify_error(exc, provider=provider.name, model=model_name)
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=err.model,
                        operation=operation,
                        success=False,
                        error_kind=err.error_kind,
                        error=str(err),
                        status_code=err.status_code,
                    )
                )
                if err.error_kind in _COOLDOWN_ERROR_KINDS and self.cooldown_seconds > 0:
                    with self._lock:
                        self._cooldown_until[provider.name] = (
                            self._clock() + self.cooldown_seconds
                        )
                logger.warning(
                    "LLM provider %s (%s) failed on %s [%s]: %s",
                    provider.name,
                    err.model,
                    operation,
                    err.error_kind,
                    err,
                )
                if not self.fallback_enabled or not err.retryable:
                    break
                continue

            used_fallback = provider.name != primary_name or len(attempts) > 0
            attempts.append(
                ProviderAttempt(
                    provider=provider.name,
                    model=model_name,
                    operation=operation,
                    success=True,
                )
            )
            with self._lock:
                self._cooldown_until.pop(provider.name, None)
                self.last_attempts = list(attempts)
                if is_embedding:
                    self.last_embedding_provider = provider.name
                else:
                    self.last_chat_provider = provider.name

            if used_fallback:
                if is_embedding:
                    logger.warning(
                        "Embedding fell back to provider=%s (%s); vectors from different embedding models may not share the same vector space.",
                        provider.name,
                        model_name,
                    )
                else:
                    logger.warning(
                        "LLM %s fell back from %s to %s (%s).",
                        operation,
                        primary_name,
                        provider.name,
                        model_name,
                    )
            return result, provider, used_fallback

        with self._lock:
            self.last_attempts = list(attempts)
        raise AllProvidersFailedError(operation=operation, attempts=attempts)

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        result, _, _ = self._execute(
            self.chat_providers,
            "extract_document",
            lambda p: p.extract_document(
                text=text,
                source_meta=source_meta,
                existing_catalog=existing_catalog,
                known_facets=known_facets,
            ),
        )
        return result

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
        result, _, _ = self._execute(
            self.chat_providers,
            f"extract_stage:{stage}",
            lambda p: p.extract_stage(
                stage=stage,
                text=text,
                source_meta=source_meta,
                existing_catalog=existing_catalog,
                known_facets=known_facets,
                prior=prior,
            ),
        )
        return result

    def synthesize_consensus(
        self,
        *,
        company: Node,
        events: list[Node],
        views: list[Node],
        themes: list[Node],
        prior_consensus: Node | None,
    ) -> ConsensusSynthesis:
        result, _, _ = self._execute(
            self.chat_providers,
            "synthesize_consensus",
            lambda p: p.synthesize_consensus(
                company=company,
                events=events,
                views=views,
                themes=themes,
                prior_consensus=prior_consensus,
            ),
        )
        return result

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.embedding_providers:
            raise ProviderConfigError(
                "No embedding-capable LLM providers configured.",
                provider="router",
            )
        result, _, _ = self._execute(
            self.embedding_providers,
            "embed_texts",
            lambda p: p.embed_texts(texts),
            is_embedding=True,
        )
        return result

    def describe(self) -> dict[str, Any]:
        """Return safe diagnostics about configured chains and runtime state."""
        with self._lock:
            now = self._clock()
            cooled = sorted(
                name for name, until in self._cooldown_until.items() if until > now
            )
            last_chat = self.last_chat_provider
            last_emb = self.last_embedding_provider
        return {
            "primary_provider": self.primary_provider.name,
            "fallback_enabled": self.fallback_enabled,
            "cooldown_seconds": self.cooldown_seconds,
            "cooled_down_providers": cooled,
            "last_chat_provider": last_chat,
            "last_embedding_provider": last_emb,
            "chat_providers": [p.describe() for p in self.chat_providers],
            "embedding_providers": [p.describe() for p in self.embedding_providers],
        }

    def format_chain_summary(self) -> str:
        """Render human-readable summary of the active chat provider chain."""
        chain = " -> ".join(f"{p.name} ({p.chat_model})" for p in self.chat_providers)
        if not self.fallback_enabled:
            return f"{chain} [fallback off]"
        return chain

    def close(self) -> None:
        """Close all unique provider instances managed by this router."""
        seen: set[int] = set()
        for provider in [*self.chat_providers, *self.embedding_providers]:
            pid = id(provider)
            if pid not in seen:
                seen.add(pid)
                provider.close()


def create_llm_client(settings: Settings) -> LLMRouter:
    """Instantiate a unified `LLMRouter` wired to the configured provider chains."""
    chat_names = settings.resolve_provider_chain()
    embed_names = settings.resolve_embedding_chain()

    cache: dict[ProviderName, BaseLLMProvider] = {}

    def _get_or_build(name: ProviderName) -> BaseLLMProvider:
        if name not in cache:
            cache[name] = build_provider(name, settings)
        return cache[name]

    chat_providers = [_get_or_build(name) for name in chat_names]
    embedding_providers = [_get_or_build(name) for name in embed_names]

    return LLMRouter(
        chat_providers,
        embedding_providers,
        fallback_enabled=settings.llm_fallback_enabled,
        cooldown_seconds=settings.llm_cooldown_seconds,
    )
