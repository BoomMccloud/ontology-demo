"""Offline tests for the unified multi-LLM provider router, fallback, cooldown, and adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from stock_ontology.agent import OntologyAgent
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel

from stock_ontology.llm import (
    AllProvidersFailedError,
    AnthropicProvider,
    BaseLLMProvider,
    LLMRouter,
    OpenAICompatibleProvider,
    OpenAIProvider,
    create_llm_client,
)
from stock_ontology.llm.agent_model import AgentModelChain, build_agent_models
from stock_ontology.models import ConsensusSynthesis, ExtractionResult, Node
from stock_ontology.web import create_app


class _FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _StubProvider(BaseLLMProvider):
    def __init__(
        self,
        name: str,
        *,
        chat_model: str = "model-a",
        embedding_model: str | None = "emb-a",
        supports_embeddings: bool = True,
        configured: bool = True,
        side_effects: list[Any] | None = None,
        embed_side_effects: list[Any] | None = None,
    ) -> None:
        self.name = name
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self.supports_embeddings = supports_embeddings
        self._configured = configured
        self._side_effects = list(side_effects or [])
        self._embed_side_effects = list(embed_side_effects or [])
        self.chat_calls = 0
        self.embed_calls = 0

    def is_configured(self) -> bool:
        return self._configured

    def _next(self, queue: list[Any]) -> Any:
        if not queue:
            raise RuntimeError(f"No stub response queued for {self.name}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item()
        return item

    def generate_structured(self, *, system_instruction: str, prompt: str, schema: type[Any]) -> Any:
        self.chat_calls += 1
        val = self._next(self._side_effects)
        if isinstance(val, schema):
            return val
        return schema.model_validate(val)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.supports_embeddings:
            return super().embed_texts(texts)
        self.embed_calls += 1
        val = self._next(self._embed_side_effects)
        if callable(val):
            return val(texts)
        return val


def test_settings_from_env_chains_and_dashscope_key_without_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in (
        "LLM_PROVIDER",
        "LLM_PROVIDERS",
        "LLM_FALLBACK_PROVIDERS",
        "EMBEDDING_PROVIDERS",
        "LLM_FALLBACK_ENABLED",
        "LLM_COOLDOWN_SECONDS",
        "LLM_TIMEOUT_SECONDS",
        "DASHSCOPE_AP_SOUTHEAST_1_API_KEY",
        "DASHSCOPE_AP_SOUTHEAST_1_API_URL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_API_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_COMPAT_API_KEY",
        "OPENAI_COMPAT_API_URL",
        "OPENAI_COMPAT_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DASHSCOPE_AP_SOUTHEAST_1_API_KEY=ds-secret-key",
                "GEMINI_API_KEY=gm-secret-key",
                "ANTHROPIC_API_KEY=ant-secret-key",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file=env_file)
    assert settings.resolve_provider() == "gemini"
    assert settings.resolve_provider_chain() == ["gemini", "dashscope", "anthropic"]
    # Anthropic does not support embeddings, so embedding chain skips it cleanly.
    assert settings.resolve_embedding_chain() == ["gemini", "dashscope"]

    router = create_llm_client(settings)
    assert isinstance(router, LLMRouter)
    assert [p.name for p in router.chat_providers] == ["gemini", "dashscope", "anthropic"]
    assert [p.name for p in router.embedding_providers] == ["gemini", "dashscope"]

    # Explicit LLM_PROVIDERS and EMBEDDING_PROVIDERS
    monkeypatch.setenv("LLM_PROVIDERS", "openai,anthropic,dashscope")
    monkeypatch.setenv("EMBEDDING_PROVIDERS", "dashscope,gemini")
    s_explicit = Settings.from_env(env_file=env_file)
    assert s_explicit.resolve_provider_chain() == ["openai", "anthropic", "dashscope"]
    assert s_explicit.resolve_embedding_chain() == ["dashscope", "gemini"]

    # Pinned LLM_PROVIDER + LLM_FALLBACK_PROVIDERS
    monkeypatch.delenv("LLM_PROVIDERS")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "dashscope,gemini")
    s_pinned = Settings.from_env(env_file=env_file)
    assert s_pinned.resolve_provider_chain() == ["anthropic", "dashscope", "gemini"]
    assert s_pinned.resolve_embedding_chain() == ["dashscope", "gemini"]

    # Invalid provider rejected clearly
    monkeypatch.setenv("LLM_PROVIDERS", "dashscope,bogus")
    with pytest.raises(ValueError, match="Invalid provider"):
        Settings.from_env(env_file=env_file)


def test_router_fallback_across_error_types_and_operations() -> None:
    class _RateLimitError(RuntimeError):
        status_code = 429

    class _AuthError(RuntimeError):
        status_code = 401

    class _ServerError(RuntimeError):
        status_code = 503

    nvda = Node(id="ent_nvda", node_type="entity", name="NVIDIA", summary="GPU leader")
    extraction = ExtractionResult()
    consensus = ConsensusSynthesis(
        stance="buy",
        support_strength="strong",
        conviction="high",
        summary="Strong demand.",
        pillars=["Hyperscaler AI spend >20%"],
    )

    p_primary = _StubProvider(
        "dashscope",
        chat_model="qwen3.8-flash",
        side_effects=[
            _RateLimitError("429 RESOURCE_EXHAUSTED"),
            _AuthError("401 Unauthorized"),
            _ServerError("503 Service Unavailable"),
            httpx.ReadTimeout("request timed out"),
        ],
        embed_side_effects=[ValueError("bad json") if False else json.JSONDecodeError("bad", "x", 0)],
    )
    p_secondary = _StubProvider(
        "gemini",
        chat_model="gemini-3.8-flash",
        embedding_model="gemini-embedding-2",
        side_effects=[
            extraction,
            consensus,
            consensus.model_copy(update={"summary": "Fallback reply 1"}),
            consensus.model_copy(update={"summary": "Fallback reply 2"}),
        ],
        embed_side_effects=[[[0.1, 0.2]]],
    )

    # Set cooldown=0 here so every operation directly exercises primary -> secondary fallback.
    router = LLMRouter([p_primary, p_secondary], cooldown_seconds=0.0)

    ext_res = router.extract_document(
        text="doc",
        source_meta={"file_path": "NVDA/note.md"},
        existing_catalog="",
        known_facets={},
    )
    assert ext_res == extraction

    syn_res = router.synthesize_consensus(
        company=nvda, events=[], views=[], themes=[], prior_consensus=None
    )
    assert syn_res.stance == "bullish"

    # The 503 and the network timeout fall back as well.
    syn1 = router.synthesize_consensus(
        company=nvda, events=[], views=[], themes=[], prior_consensus=None
    )
    assert syn1.summary == "Fallback reply 1"
    assert router.last_chat_provider == "gemini"
    assert [(a.provider, a.error_kind) for a in router.last_attempts] == [
        ("dashscope", "server"),
        ("gemini", None),
    ]

    syn2 = router.synthesize_consensus(
        company=nvda, events=[], views=[], themes=[], prior_consensus=None
    )
    assert syn2.summary == "Fallback reply 2"
    assert [(a.provider, a.error_kind) for a in router.last_attempts] == [
        ("dashscope", "network"),
        ("gemini", None),
    ]

    vecs = router.embed_texts(["nvidia"])
    assert vecs == [[0.1, 0.2]]
    assert router.last_embedding_provider == "gemini"
    assert p_primary.chat_calls == 4
    assert p_secondary.chat_calls == 4


def test_router_cooldown_and_disabled_fallback_and_all_failed() -> None:
    class _RateLimitError(RuntimeError):
        status_code = 429

    nvda = Node(id="ent_nvda", node_type="entity", name="NVIDIA", summary="GPU leader")

    def _syn(summary: str) -> ConsensusSynthesis:
        return ConsensusSynthesis(
            stance="buy", support_strength="strong", conviction="high", summary=summary, pillars=["p"]
        )

    def _synthesize(router: LLMRouter) -> ConsensusSynthesis:
        return router.synthesize_consensus(company=nvda, events=[], views=[], themes=[], prior_consensus=None)

    clock = _FakeClock(start=1000.0)
    p1 = _StubProvider(
        "dashscope",
        side_effects=[
            _RateLimitError("429 RESOURCE_EXHAUSTED"),
            _syn("Primary recovered"),
        ],
    )
    p2 = _StubProvider(
        "openai",
        side_effects=[
            _syn("Secondary 1"),
            _syn("Secondary 2"),
            RuntimeError("Secondary transient failure"),
        ],
    )
    router = LLMRouter([p1, p2], cooldown_seconds=60.0, clock=clock)

    # First call hits p1 (429 -> cooled for 60s), falls back to p2.
    t1 = _synthesize(router)
    assert t1.summary == "Secondary 1"
    assert router.last_chat_provider == "openai"
    assert [a.provider for a in router.last_attempts] == ["dashscope", "openai"]
    assert p1.chat_calls == 1
    assert "dashscope" in router.describe()["cooled_down_providers"]

    # Within cooldown window, p1 is skipped cleanly.
    clock.advance(30.0)
    t2 = _synthesize(router)
    assert t2.summary == "Secondary 2"
    assert router.last_chat_provider == "openai"
    assert p1.chat_calls == 1
    assert p2.chat_calls == 2

    # If p2 fails while p1 is still cooled, router still tries cooled p1 as last resort!
    t3 = _synthesize(router)
    assert router.last_chat_provider == "dashscope"
    assert t3.summary == "Primary recovered"
    assert p1.chat_calls == 2
    assert router.describe()["cooled_down_providers"] == []

    # When fallback_enabled=False, router does not try p2.
    p_fail = _StubProvider("dashscope", side_effects=[_RateLimitError("429")])
    p_unused = _StubProvider("gemini", side_effects=[_syn("should not run")])
    strict_router = LLMRouter([p_fail, p_unused], fallback_enabled=False)
    with pytest.raises(AllProvidersFailedError) as exc_info:
        _synthesize(strict_router)
    assert len(exc_info.value.attempts) == 1
    assert exc_info.value.attempts[0].provider == "dashscope"
    assert p_unused.chat_calls == 0

    # When all providers fail, AllProvidersFailedError summarizes every attempt.
    p_a = _StubProvider("dashscope", side_effects=[RuntimeError("ds down")])
    p_b = _StubProvider("gemini", side_effects=[_RateLimitError("429 quota")])
    broken = LLMRouter([p_a, p_b], fallback_enabled=True)
    with pytest.raises(AllProvidersFailedError) as all_err:
        _synthesize(broken)
    msg = str(all_err.value)
    assert "dashscope" in msg and "gemini" in msg
    assert len(all_err.value.attempts) == 2


def test_openai_anthropic_and_compat_http_adapters() -> None:
    seen_openai_bodies: list[dict[str, Any]] = []
    seen_anthropic_bodies: list[dict[str, Any]] = []

    def openai_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_openai_bodies.append(body)
        assert "enable_thinking" not in body
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.5, 0.5, 0.0, 0.0]}]},
            )
        if body.get("response_format"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "entities": [],
                                        "events": [],
                                        "views": [],
                                        "themes": [],
                                        "edges": [],
                                    }
                                ),
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "OpenAI OK"}}]}
        )

    def anthropic_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "ant-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content.decode("utf-8"))
        seen_anthropic_bodies.append(body)
        if body.get("tool_choice"):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_struct_1",
                            "name": "ConsensusSynthesis",
                            "input": {
                                "stance": "buy",
                                "support_strength": "strong",
                                "conviction": "high",
                                "summary": "Anthropic synthesis",
                                "pillars": ["Pillar 1"],
                                "supporting_node_ids": [],
                                "contradicting_node_ids": [],
                                "facets": [],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(500, json={"error": "unexpected request"})

    settings = Settings(
        openai_api_key="oa-key",
        openai_api_url="https://mock.openai.local/v1",
        anthropic_api_key="ant-key",
        anthropic_api_url="https://mock.anthropic.local/v1",
        openai_compat_api_key="compat-key",
        openai_compat_api_url="https://mock.compat.local/v1",
        openai_compat_model="llama-3.3-70b",
        embedding_dim=4,
    )
    oa = OpenAIProvider(settings, http_client=httpx.Client(transport=httpx.MockTransport(openai_handler)))
    ant = AnthropicProvider(
        settings, http_client=httpx.Client(transport=httpx.MockTransport(anthropic_handler))
    )
    compat = OpenAICompatibleProvider(
        name="openai_compatible",
        api_key=settings.openai_compat_api_key,
        base_url=settings.openai_compat_api_url,
        chat_model=settings.openai_compat_model or "",
        embedding_dim=4,
        http_client=httpx.Client(transport=httpx.MockTransport(openai_handler)),
    )

    assert oa.extract_document(
        text="hello",
        source_meta={},
        existing_catalog="",
        known_facets={},
    ).entities == []
    assert oa.embed_texts(["test"]) == [[0.5, 0.5, 0.0, 0.0]]
    assert compat.extract_document(
        text="hi", source_meta={}, existing_catalog="", known_facets={}
    ).entities == []
    assert seen_openai_bodies[-1]["model"] == "llama-3.3-70b"
    assert len(seen_openai_bodies) >= 3

    syn = ant.synthesize_consensus(
        company=Node(id="ent_1", node_type="entity", name="NVDA", summary="GPUs"),
        events=[],
        views=[],
        themes=[],
        prior_consensus=None,
    )
    assert syn.stance == "bullish"
    assert ant.supports_embeddings is False

    # Router configured with Anthropic first + OpenAI fallback handles embeddings via OpenAI.
    router = LLMRouter([ant, oa])
    assert router.embed_texts(["test"]) == [[0.5, 0.5, 0.0, 0.0]]
    assert router.last_embedding_provider == "openai"

    assert len(seen_anthropic_bodies) == 1


def test_build_agent_models_maps_chain_to_native_models() -> None:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.models.openai import OpenAIChatModel

    settings = Settings(
        llm_providers=["anthropic", "gemini", "dashscope", "openai", "openai_compatible"],
        gemini_api_key="g",
        gemini_model="gemini-x",
        dashscope_api_key="d",
        dashscope_api_url="https://mock.dashscope.local/compatible-mode/v1",
        dashscope_model="qwen-x",
        openai_api_key="o",
        openai_api_url="https://mock.openai.local/v1",
        openai_model="gpt-x",
        anthropic_api_key="a",
        anthropic_api_url="https://mock.anthropic.local/v1",
        anthropic_model="claude-x",
        openai_compat_api_key="c",
        openai_compat_api_url="https://mock.compat.local/v1",
        openai_compat_model="llama-x",
        llm_cooldown_seconds=17.0,
    )
    chain = build_agent_models(settings)
    assert chain.cooldown_seconds == 17.0
    assert [(type(m), m.model_name, (m.base_url or "").rstrip("/")) for m in chain.models] == [
        (AnthropicModel, "claude-x", "https://mock.anthropic.local"),
        (GoogleModel, "gemini-x", "https://generativelanguage.googleapis.com"),
        (OpenAIChatModel, "qwen-x", "https://mock.dashscope.local/compatible-mode/v1"),
        (OpenAIChatModel, "gpt-x", "https://mock.openai.local/v1"),
        (OpenAIChatModel, "llama-x", "https://mock.compat.local/v1"),
    ]
    turn_model = chain.for_turn()
    assert isinstance(turn_model, FallbackModel)
    assert [m.model_name for m in turn_model.models] == ["claude-x", "gemini-x", "qwen-x", "gpt-x", "llama-x"]

    # Unconfigured providers are skipped, and with fallback off only the first configured one is used.
    partial = build_agent_models(Settings(llm_providers=["anthropic", "gemini", "dashscope"], dashscope_api_key="d", gemini_api_key="g"))
    assert [m.model_name for m in partial.models] == [Settings.model_fields["gemini_model"].default, "qwen3.8-flash"]
    strict = build_agent_models(
        Settings(llm_providers=["gemini", "dashscope"], gemini_api_key="g", dashscope_api_key="d", llm_fallback_enabled=False)
    )
    assert len(strict.models) == 1 and strict.for_turn() is strict.models[0]

    from stock_ontology.llm import ProviderConfigError

    with pytest.raises(ProviderConfigError):
        build_agent_models(Settings(llm_providers=["gemini"])).for_turn()


def test_agent_model_chain_cools_failed_models_last_across_turns(tmp_path: Path) -> None:
    db_path = tmp_path / "cross.db"
    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        db.upsert_node(
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="GPU leader",
                aliases=["NVDA"],
                facets={"entity_type": "company", "ticker": "NVDA"},
            ),
            embedding=[1.0, 0.0, 0.0, 0.0],
        )

    calls: list[str] = []
    gemini_errors: list[Exception | None] = [None, ModelHTTPError(429, "gemini-x", {"error": "quota"})]
    ds_seen: list[list[ModelMessage]] = []

    def gemini(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("gemini")
        error = gemini_errors.pop(0) if gemini_errors else None
        if error is not None:
            raise error
        if not any(isinstance(p, ToolReturnPart) for m in messages for p in getattr(m, "parts", [])):
            return ModelResponse(
                parts=[ToolCallPart("get_entity_overview", {"entity_name_or_id": "NVDA"})], provider_name="google"
            )
        return ModelResponse(parts=[TextPart("NVIDIA via Gemini.")], provider_name="google")

    dashscope_errors: list[Exception | None] = []

    def dashscope(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("dashscope")
        ds_seen.append(list(messages))
        error = dashscope_errors.pop(0) if dashscope_errors else None
        if error is not None:
            raise error
        return ModelResponse(parts=[TextPart("NVIDIA via DashScope fallback.")], provider_name="openai")

    clock = _FakeClock(start=1000.0)
    chain = AgentModelChain(
        [FunctionModel(gemini, model_name="gemini-x"), FunctionModel(dashscope, model_name="qwen-x")],
        cooldown_seconds=60.0,
        clock=clock,
    )

    with OntologyDB(db_path, embedding_dim=4, read_only=True) as ro_db:
        agent = OntologyAgent(ro_db, _StubProvider("gemini"), model=chain.for_turn())
        # Turn 1: Gemini calls a tool, then its follow-up request is rate limited and DashScope answers.
        first = agent.chat("Check NVDA", ())
        assert calls == ["gemini", "gemini", "dashscope"]
        assert first.reply == "NVIDIA via DashScope fallback."
        assert (first.provider, first.model, first.fallback_used) == ("openai", "qwen-x", True)
        # DashScope sees the whole history, with the tool call and its return paired by id.
        history = ds_seen[0]
        call = next(p for m in history if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, ToolCallPart))
        ret = next(p for m in history if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart))
        assert call.tool_call_id == ret.tool_call_id

        # Turn 2, within the cooldown: DashScope is tried first; Gemini is not called.
        clock.advance(30.0)
        calls.clear()
        agent.model = chain.for_turn()
        assert [m.model_name for m in agent.model.models] == ["qwen-x", "gemini-x"]
        second = agent.chat("Again", first.history)
        assert calls == ["dashscope"]
        assert (second.provider, second.model) == ("openai", "qwen-x")

        # Turn 3: if DashScope fails while Gemini is cooled, Gemini is still the last resort.
        calls.clear()
        dashscope_errors.append(ModelAPIError("qwen-x", "connection reset"))
        agent.model = chain.for_turn()
        third = agent.chat("Once more", second.history)
        assert calls == ["dashscope", "gemini"]
        assert third.reply == "NVIDIA via Gemini."
        assert (third.provider, third.model) == ("google", "gemini-x")

        # A non-cooling error (connection) leaves DashScope active; after the window Gemini leads again.
        clock.advance(31.0)
        assert [m.model_name for m in chain.ordered()] == ["gemini-x", "qwen-x"]

    # 401/403 cool a model too; other HTTP errors fall back without cooling.
    for status, cools in ((401, True), (403, True), (500, False)):
        chain = AgentModelChain([FunctionModel(gemini, model_name="m1"), FunctionModel(dashscope, model_name="m2")], clock=clock)
        assert chain._falls_back(ModelHTTPError(status, "m1")) is True
        assert [m.model_name for m in chain.ordered()] == (["m2", "m1"] if cools else ["m1", "m2"])
    assert AgentModelChain([], clock=clock)._falls_back(ValueError("not an API error")) is False


def test_web_health_and_chat_report_provider_and_no_secret_leak(tmp_path: Path) -> None:
    db_path = tmp_path / "web_router.db"
    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        db.upsert_node(
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="GPU leader",
                aliases=["NVDA"],
                facets={"entity_type": "company", "ticker": "NVDA"},
            ),
            embedding=[1.0, 0.0, 0.0, 0.0],
        )

    p_gem = _StubProvider("gemini", chat_model="gemini-3.8-flash")
    p_ds = _StubProvider("dashscope", chat_model="qwen3.8-flash")
    router = LLMRouter([p_gem, p_ds])

    def gemini(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(429, "gemini-3.8-flash", {"error": "RESOURCE_EXHAUSTED"})

    def dashscope(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Answered by DashScope fallback.")], provider_name="dashscope")

    agent_models = AgentModelChain(
        [FunctionModel(gemini, model_name="gemini-3.8-flash"), FunctionModel(dashscope, model_name="qwen3.8-flash")]
    )

    settings = Settings(
        db_path=db_path,
        embedding_dim=4,
        data_dir=tmp_path,
        dashscope_api_key="super-secret-ds-key",
        gemini_api_key="super-secret-gm-key",
    )
    app = create_app(settings, llm=router, agent_model=agent_models)
    client = TestClient(app)

    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    health_json = r_health.json()
    assert health_json["llm"]["primary_provider"] == "gemini"
    assert health_json["llm"]["fallback_enabled"] is True
    health_text = json.dumps(health_json)
    assert "super-secret-ds-key" not in health_text
    assert "super-secret-gm-key" not in health_text

    r_chat = client.post("/api/chat", json={"message": "Check NVDA"})
    assert r_chat.status_code == 200
    chat_json = r_chat.json()
    assert chat_json["reply"] == "Answered by DashScope fallback."
    assert chat_json["provider"] == "dashscope"
    assert chat_json["model"] == "qwen3.8-flash"
    assert chat_json["fallback_used"] is True
