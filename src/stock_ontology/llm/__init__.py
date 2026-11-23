"""Unified multi-LLM provider package with automatic fallback routing."""

from stock_ontology.llm.base import (
    AgentTurn,
    AllProvidersFailedError,
    BaseLLMProvider,
    ErrorKind,
    LLMClient,
    LLMProviderError,
    ProviderAttempt,
    ProviderConfigError,
    ToolCall,
    classify_error,
)
from stock_ontology.llm.prompts import (
    CONSENSUS_SYSTEM_PROMPT,
    EXTRACTION_STAGES,
    EXTRACTION_SYSTEM_PROMPT,
    build_consensus_prompt,
    build_extraction_prompt,
    build_stage_prompt,
    strip_json_fences,
)
from stock_ontology.llm.providers import (
    AnthropicProvider,
    DashScopeProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    build_provider,
)
from stock_ontology.llm.router import LLMRouter, create_llm_client

# Backwards-compatible aliases
DashScopeClient = DashScopeProvider
GeminiClient = GeminiProvider

__all__ = [
    "AgentTurn",
    "AllProvidersFailedError",
    "AnthropicProvider",
    "BaseLLMProvider",
    "CONSENSUS_SYSTEM_PROMPT",
    "DashScopeClient",
    "DashScopeProvider",
    "EXTRACTION_STAGES",
    "EXTRACTION_SYSTEM_PROMPT",
    "ErrorKind",
    "GeminiClient",
    "GeminiProvider",
    "LLMClient",
    "LLMProviderError",
    "LLMRouter",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "ProviderAttempt",
    "ProviderConfigError",
    "ToolCall",
    "build_consensus_prompt",
    "build_extraction_prompt",
    "build_stage_prompt",
    "build_provider",
    "classify_error",
    "create_llm_client",
    "strip_json_fences",
]
