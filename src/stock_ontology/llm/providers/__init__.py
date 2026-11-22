"""Concrete LLM provider adapters and factory helper."""

from __future__ import annotations

from stock_ontology.config import ProviderName, Settings
from stock_ontology.llm.base import BaseLLMProvider
from stock_ontology.llm.providers.anthropic import AnthropicProvider
from stock_ontology.llm.providers.gemini import GeminiProvider
from stock_ontology.llm.providers.openai_compat import (
    DashScopeProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    create_openai_compat_provider,
)


def build_provider(name: ProviderName, settings: Settings) -> BaseLLMProvider:
    """Instantiate a single named `BaseLLMProvider` from `settings`."""
    if name == "dashscope":
        return DashScopeProvider(settings)
    if name == "gemini":
        return GeminiProvider(settings)
    if name == "openai":
        return OpenAIProvider(settings)
    if name == "anthropic":
        return AnthropicProvider(settings)
    if name == "openai_compatible":
        return create_openai_compat_provider(settings)
    raise ValueError(f"Unsupported LLM provider: {name!r}")


__all__ = [
    "AnthropicProvider",
    "DashScopeProvider",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "build_provider",
]
