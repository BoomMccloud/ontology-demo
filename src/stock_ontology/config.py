"""Configuration management for Stock Ontology MVP."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGE_CODES,
    normalize_language,
)

ProviderName = Literal["dashscope", "gemini", "openai", "anthropic", "openai_compatible"]
LLMProvider = Literal["auto", "dashscope", "gemini", "openai", "anthropic", "openai_compatible"]

VALID_PROVIDERS: tuple[ProviderName, ...] = (
    "dashscope",
    "gemini",
    "openai",
    "anthropic",
    "openai_compatible",
)
DEFAULT_PROVIDER_ORDER: tuple[ProviderName, ...] = (
    "gemini",
    "dashscope",
    "openai",
    "anthropic",
    "openai_compatible",
)
# Research note file types read by ingestion and shown by the web catalog.
SUPPORTED_EXTENSIONS = frozenset({".md", ".txt"})


class NoteConflictError(Exception):
    """The note or its extraction changed while a reader action was pending."""

    def __init__(self) -> None:
        super().__init__("The source note or its extraction changed. Retry the operation.")

DEFAULT_DASHSCOPE_INTL_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com/v1"

_T = TypeVar("_T")


def _dedupe(items: list[_T]) -> list[_T]:
    seen: set[_T] = set()
    out: list[_T] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_url(value: str | None) -> str | None:
    cleaned = _clean_opt(value)
    return cleaned.rstrip("/") if cleaned else None


def _parse_provider_list(raw: str | None, *, env_name: str) -> list[ProviderName] | None:
    cleaned = _clean_opt(raw)
    if cleaned is None:
        return None
    providers: list[ProviderName] = []
    for part in cleaned.split(","):
        item = part.strip().lower()
        if not item:
            continue
        if item not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider {item!r} in {env_name}. "
                f"Expected one of {', '.join(VALID_PROVIDERS)}."
            )
        providers.append(item)  # type: ignore[arg-type]
    return providers or None


def _parse_bool(raw: str | None, *, default: bool, env_name: str) -> bool:
    cleaned = _clean_opt(raw)
    if cleaned is None:
        return default
    low = cleaned.lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Invalid boolean value {raw!r} for {env_name}.")


def _parse_float(
    raw: str | None,
    *,
    default: float,
    env_name: str,
    min_value: float = 0.0,
    strictly_positive: bool = False,
) -> float:
    cleaned = _clean_opt(raw)
    if cleaned is None:
        return default
    try:
        val = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value {raw!r} for {env_name}.") from exc
    if strictly_positive and val <= min_value:
        raise ValueError(f"{env_name} must be > {min_value}, got {val}.")
    if not strictly_positive and val < min_value:
        raise ValueError(f"{env_name} must be >= {min_value}, got {val}.")
    return val


class Settings(BaseModel):
    """Runtime settings loaded from environment variables and optional overrides."""

    llm_provider: LLMProvider = Field(default="auto")
    llm_providers: list[ProviderName] | None = Field(default=None)
    llm_fallback_providers: list[ProviderName] = Field(default_factory=list)
    embedding_providers: list[ProviderName] | None = Field(default=None)
    llm_fallback_enabled: bool = Field(default=True)
    llm_cooldown_seconds: float = Field(default=60.0, ge=0.0)
    llm_timeout_seconds: float = Field(default=120.0, gt=0.0)

    # DashScope / Qwen (AP-Southeast-1 or international OpenAI-compatible endpoint)
    dashscope_api_key: str | None = Field(default=None)
    dashscope_api_url: str | None = Field(default=DEFAULT_DASHSCOPE_INTL_URL)
    dashscope_model: str = Field(default="qwen3.8-flash")
    dashscope_embedding_model: str = Field(default="qwen3.7-text-embedding")

    # Google Gemini
    gemini_api_key: str | None = Field(default=None)
    gemini_model: str = Field(default="gemini-3.8-flash")
    embedding_model: str = Field(default="gemini-embedding-2")

    # OpenAI
    openai_api_key: str | None = Field(default=None)
    openai_api_url: str = Field(default=DEFAULT_OPENAI_URL)
    openai_model: str = Field(default="gpt-4o-mini")
    openai_embedding_model: str = Field(default="text-embedding-3-small")

    # Anthropic
    anthropic_api_key: str | None = Field(default=None)
    anthropic_api_url: str = Field(default=DEFAULT_ANTHROPIC_URL)
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")

    # Generic OpenAI-compatible endpoint (vLLM, OpenRouter, LiteLLM, etc.)
    openai_compat_api_key: str | None = Field(default=None)
    openai_compat_api_url: str | None = Field(default=None)
    openai_compat_model: str | None = Field(default=None)
    openai_compat_embedding_model: str | None = Field(default=None)

    embedding_dim: int = Field(default=768, ge=1)
    db_path: Path = Field(default=Path("ontology.db"))
    data_dir: Path = Field(default=Path("data"))
    registry_path: Path = Field(default=Path("ontology_registry.json"))
    default_language: str = Field(default=DEFAULT_LANGUAGE)

    @field_validator("default_language")
    @classmethod
    def _validate_default_language(cls, value: str) -> str:
        norm = normalize_language(value)
        if norm is None:
            raise ValueError(
                f"Invalid default_language value: {value!r}. "
                f"Expected one of {', '.join(SUPPORTED_LANGUAGE_CODES)}."
            )
        return norm

    def is_provider_configured(self, provider: ProviderName) -> bool:
        """Return True if the required credentials/config for `provider` are present."""
        if provider == "dashscope":
            return bool(_clean_opt(self.dashscope_api_key) and _clean_url(self.dashscope_api_url))
        if provider == "gemini":
            return bool(_clean_opt(self.gemini_api_key))
        if provider == "openai":
            return bool(_clean_opt(self.openai_api_key) and _clean_url(self.openai_api_url))
        if provider == "anthropic":
            return bool(_clean_opt(self.anthropic_api_key) and _clean_url(self.anthropic_api_url))
        if provider == "openai_compatible":
            return bool(
                _clean_opt(self.openai_compat_api_key)
                and _clean_url(self.openai_compat_api_url)
                and _clean_opt(self.openai_compat_model)
            )
        return False

    def supports_embeddings(self, provider: ProviderName) -> bool:
        """Return True if `provider` supports text embeddings."""
        if provider == "anthropic":
            return False
        if provider == "openai_compatible":
            return bool(_clean_opt(self.openai_compat_embedding_model))
        return provider in ("dashscope", "gemini", "openai")

    def resolve_provider_chain(self) -> list[ProviderName]:
        """Resolve ordered chat/structured LLM providers including fallbacks."""
        if self.llm_providers:
            return _dedupe(list(self.llm_providers))

        if self.llm_provider != "auto":
            return _dedupe([self.llm_provider, *self.llm_fallback_providers])

        configured = [p for p in DEFAULT_PROVIDER_ORDER if self.is_provider_configured(p)]
        for fb in self.llm_fallback_providers:
            if fb not in configured:
                configured.append(fb)
        if not configured:
            return ["gemini"]
        return _dedupe(configured)

    def resolve_embedding_chain(self) -> list[ProviderName]:
        """Resolve ordered embedding providers, skipping chat-only providers."""
        if self.embedding_providers:
            return _dedupe(list(self.embedding_providers))

        chain = [p for p in self.resolve_provider_chain() if self.supports_embeddings(p)]
        if chain:
            return chain

        return [
            p
            for p in DEFAULT_PROVIDER_ORDER
            if self.is_provider_configured(p) and self.supports_embeddings(p)
        ]

    def resolve_provider(self) -> ProviderName:
        """Choose the primary active LLM provider."""
        return self.resolve_provider_chain()[0]

    @classmethod
    def from_env(
        cls,
        *,
        db_path: str | Path | None = None,
        data_dir: str | Path | None = None,
        registry_path: str | Path | None = None,
        env_file: str | Path | None = None,
        default_language: str | None = None,
    ) -> Settings:
        """Load settings from `.env` (if present) and process environment."""
        load_dotenv(dotenv_path=env_file, override=False)

        raw_lang = (
            default_language
            if default_language is not None
            else (os.getenv("APP_LANGUAGE") or os.getenv("STOCK_ONTOLOGY_LANG"))
        )
        if raw_lang is not None and raw_lang.strip():
            resolved_lang = normalize_language(raw_lang)
            if resolved_lang is None:
                raise ValueError(
                    f"Invalid APP_LANGUAGE value: {raw_lang!r}. "
                    f"Expected one of {', '.join(SUPPORTED_LANGUAGE_CODES)}."
                )
        else:
            resolved_lang = DEFAULT_LANGUAGE

        raw_provider = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
        if raw_provider not in ("auto", *VALID_PROVIDERS):
            raise ValueError(
                f"Invalid LLM_PROVIDER value: {raw_provider!r}. "
                f"Expected auto or one of {', '.join(VALID_PROVIDERS)}."
            )

        llm_providers = _parse_provider_list(os.getenv("LLM_PROVIDERS"), env_name="LLM_PROVIDERS")
        fallback_providers = (
            _parse_provider_list(
                os.getenv("LLM_FALLBACK_PROVIDERS"), env_name="LLM_FALLBACK_PROVIDERS"
            )
            or []
        )
        embedding_providers = _parse_provider_list(
            os.getenv("EMBEDDING_PROVIDERS"), env_name="EMBEDDING_PROVIDERS"
        )

        fallback_enabled = _parse_bool(
            os.getenv("LLM_FALLBACK_ENABLED"), default=True, env_name="LLM_FALLBACK_ENABLED"
        )
        cooldown_seconds = _parse_float(
            os.getenv("LLM_COOLDOWN_SECONDS"),
            default=60.0,
            env_name="LLM_COOLDOWN_SECONDS",
            min_value=0.0,
        )
        timeout_seconds = _parse_float(
            os.getenv("LLM_TIMEOUT_SECONDS"),
            default=120.0,
            env_name="LLM_TIMEOUT_SECONDS",
            min_value=0.0,
            strictly_positive=True,
        )

        gemini_key = _clean_opt(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        ds_key = _clean_opt(
            os.getenv("DASHSCOPE_AP_SOUTHEAST_1_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        )
        ds_url = (
            _clean_url(
                os.getenv("DASHSCOPE_AP_SOUTHEAST_1_API_URL") or os.getenv("DASHSCOPE_API_URL")
            )
            or DEFAULT_DASHSCOPE_INTL_URL
        )

        openai_key = _clean_opt(os.getenv("OPENAI_API_KEY"))
        openai_url = (
            _clean_url(os.getenv("OPENAI_API_URL") or os.getenv("OPENAI_BASE_URL"))
            or DEFAULT_OPENAI_URL
        )
        anthropic_key = _clean_opt(os.getenv("ANTHROPIC_API_KEY"))
        anthropic_url = _clean_url(os.getenv("ANTHROPIC_API_URL")) or DEFAULT_ANTHROPIC_URL

        compat_key = _clean_opt(os.getenv("OPENAI_COMPAT_API_KEY"))
        compat_url = _clean_url(os.getenv("OPENAI_COMPAT_API_URL"))
        compat_model = _clean_opt(os.getenv("OPENAI_COMPAT_MODEL"))
        compat_emb_model = _clean_opt(os.getenv("OPENAI_COMPAT_EMBEDDING_MODEL"))

        raw_dim = os.getenv("EMBEDDING_DIM", "768")
        try:
            embedding_dim = int(raw_dim)
        except ValueError as exc:
            raise ValueError(f"Invalid EMBEDDING_DIM value: {raw_dim!r}") from exc

        return cls(
            llm_provider=raw_provider,  # type: ignore[arg-type]
            llm_providers=llm_providers,
            llm_fallback_providers=fallback_providers,
            embedding_providers=embedding_providers,
            llm_fallback_enabled=fallback_enabled,
            llm_cooldown_seconds=cooldown_seconds,
            llm_timeout_seconds=timeout_seconds,
            dashscope_api_key=ds_key,
            dashscope_api_url=ds_url,
            dashscope_model=_clean_opt(os.getenv("DASHSCOPE_MODEL")) or "qwen3.8-flash",
            dashscope_embedding_model=_clean_opt(os.getenv("DASHSCOPE_EMBEDDING_MODEL"))
            or "qwen3.7-text-embedding",
            gemini_api_key=gemini_key,
            gemini_model=_clean_opt(os.getenv("GEMINI_MODEL")) or "gemini-3.8-flash",
            embedding_model=_clean_opt(os.getenv("GEMINI_EMBEDDING_MODEL")) or "gemini-embedding-2",
            openai_api_key=openai_key,
            openai_api_url=openai_url,
            openai_model=_clean_opt(os.getenv("OPENAI_MODEL")) or "gpt-4o-mini",
            openai_embedding_model=_clean_opt(os.getenv("OPENAI_EMBEDDING_MODEL"))
            or "text-embedding-3-small",
            anthropic_api_key=anthropic_key,
            anthropic_api_url=anthropic_url,
            anthropic_model=_clean_opt(os.getenv("ANTHROPIC_MODEL")) or "claude-sonnet-4-20250514",
            openai_compat_api_key=compat_key,
            openai_compat_api_url=compat_url,
            openai_compat_model=compat_model,
            openai_compat_embedding_model=compat_emb_model,
            embedding_dim=embedding_dim,
            db_path=(
                Path(db_path)
                if db_path is not None
                else Path(os.getenv("ONTOLOGY_DB", "ontology.db"))
            ),
            data_dir=(
                Path(data_dir)
                if data_dir is not None
                else Path(os.getenv("ONTOLOGY_DATA_DIR", "data"))
            ),
            registry_path=(
                Path(registry_path)
                if registry_path is not None
                else Path(os.getenv("ONTOLOGY_REGISTRY", "ontology_registry.json"))
            ),
            default_language=resolved_lang,
        )
