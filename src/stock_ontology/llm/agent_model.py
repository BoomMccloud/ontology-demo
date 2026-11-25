"""Pydantic AI chat models for the query agent, built from the configured provider chain.

The agent answers through Pydantic AI's own model classes. `AgentModelChain` is the
one piece kept on top: it orders models that recently failed with a rate-limit, auth
or config error last on later turns, for `llm_cooldown_seconds`, as `LLMRouter` does
for ingestion.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelQuotaExceededError,
    ModelRateLimitError,
)
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.settings import ModelSettings

from stock_ontology.config import ProviderName, Settings
from stock_ontology.llm.base import ProviderConfigError, classify_error

logger = logging.getLogger(__name__)

_COOLDOWN_ERROR_KINDS = frozenset({"rate_limit", "auth", "config"})
_COOLDOWN_ERROR_TYPES = (ModelRateLimitError, ModelQuotaExceededError, ModelAuthenticationError)


def _strip_v1(url: str) -> str:
    """The Anthropic SDK adds `/v1` itself; settings keep it in `anthropic_api_url`."""
    cleaned = url.strip().rstrip("/")
    return cleaned[: -len("/v1")] if cleaned.endswith("/v1") else cleaned


def build_native_model(name: ProviderName, settings: Settings) -> Model:
    """Build the Pydantic AI model for one configured chat provider."""
    if name == "gemini":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(settings.gemini_model, provider=GoogleProvider(api_key=settings.gemini_api_key))
    if name == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicModel(
            settings.anthropic_model,
            provider=AnthropicProvider(
                api_key=settings.anthropic_api_key, base_url=_strip_v1(settings.anthropic_api_url)
            ),
        )

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if name == "dashscope":
        model, base_url, api_key = settings.dashscope_model, settings.dashscope_api_url, settings.dashscope_api_key
    elif name == "openai":
        model, base_url, api_key = settings.openai_model, settings.openai_api_url, settings.openai_api_key
    elif name == "openai_compatible":
        model, base_url, api_key = (
            settings.openai_compat_model or "",
            settings.openai_compat_api_url,
            settings.openai_compat_api_key,
        )
    else:
        raise ValueError(f"Unknown chat provider {name!r}.")
    # DashScope's Qwen models think by default; the router turned that off, so the agent does too.
    defaults: ModelSettings | None = {"extra_body": {"enable_thinking": False}} if name == "dashscope" else None
    return OpenAIChatModel(model, provider=OpenAIProvider(base_url=base_url, api_key=api_key), settings=defaults)


class _CooldownFallbackModel(FallbackModel):
    """A `FallbackModel` that re-reads the chain's cooldowns before every request.

    A turn makes one request per tool round plus the final answer. Ordering once per
    turn would retry a model that just failed on every later request of that turn.
    `models` keeps the configured order between requests, so `models[0]` is the
    configured primary when the agent decides whether a fallback answered.
    """

    def __init__(self, chain: AgentModelChain) -> None:
        super().__init__(*chain.models, fallback_on=chain._falls_back)
        self._agent_chain = chain

    @contextmanager
    def _cooldown_order(self) -> Iterator[None]:
        # `FallbackModel` walks `self.models` only inside `request` and `request_stream`,
        # so swapping the list around those two calls is enough.
        configured, self.models = self.models, self._agent_chain.ordered()
        try:
            yield
        finally:
            self.models = configured

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        with self._cooldown_order():
            return await super().request(*args, **kwargs)

    @asynccontextmanager
    async def request_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        with self._cooldown_order():
            async with super().request_stream(*args, **kwargs) as stream:
                yield stream


class AgentModelChain:
    """One per process: the agent's native models in priority order, plus a cooldown map.

    Call `for_turn()` for each agent turn. It returns a `FallbackModel` that puts
    cooled models last (still tried, as a last resort) on every request of the turn,
    or the model itself when there is only one. Each turn gets its own instance
    because the instance swaps its model list for the length of a request.
    """

    def __init__(
        self,
        models: Sequence[Model],
        *,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.models = list(models)
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._cooldown_until: dict[str, float] = {}

    def ordered(self) -> list[Model]:
        """The models for the next request: active ones in priority order, then cooled ones."""
        with self._lock:
            now = self._clock()
            cooled = {name for name, until in self._cooldown_until.items() if until > now}
        active = [m for m in self.models if m.model_name not in cooled]
        return active + [m for m in self.models if m.model_name in cooled]

    def for_turn(self) -> Model:
        if not self.models:
            raise ProviderConfigError("No configured chat provider for the agent.", provider="agent")
        if len(self.models) == 1:
            return self.models[0]
        return _CooldownFallbackModel(self)

    def _falls_back(self, exc: Exception) -> bool:
        """`fallback_on` handler: fall back on any API error, cooling the model on rate-limit/auth/config."""
        if not isinstance(exc, ModelAPIError):
            return False
        kind = classify_error(exc, provider="agent", model=exc.model_name).error_kind
        cools = (isinstance(exc, _COOLDOWN_ERROR_TYPES) or kind in _COOLDOWN_ERROR_KINDS) and self.cooldown_seconds > 0
        if cools:
            with self._lock:
                self._cooldown_until[exc.model_name] = self._clock() + self.cooldown_seconds
        logger.warning(
            "Agent model %s failed [%s]; falling back to the next model%s: %s",
            exc.model_name,
            kind,
            f" and cooling it for {self.cooldown_seconds:g}s" if cools else "",
            exc,
        )
        return True


def build_agent_models(settings: Settings) -> AgentModelChain:
    """The agent's model chain from the configured chat providers, skipping unconfigured ones."""
    names = [n for n in settings.resolve_provider_chain() if settings.is_provider_configured(n)]
    if not settings.llm_fallback_enabled:
        names = names[:1]
    return AgentModelChain(
        [build_native_model(n, settings) for n in names],
        cooldown_seconds=settings.llm_cooldown_seconds,
    )
