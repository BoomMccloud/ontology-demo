"""Offline tests for the unified multi-LLM provider router, fallback, cooldown, and adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import types

from stock_ontology.agent import OntologyAgent
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.llm import (
    AgentTurn,
    AllProvidersFailedError,
    AnthropicProvider,
    BaseLLMProvider,
    DashScopeProvider,
    GeminiProvider,
    LLMRouter,
    OpenAICompatibleProvider,
    OpenAIProvider,
    ToolCall,
    create_llm_client,
)
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
        self.seen_messages: list[list[dict[str, Any]]] = []

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

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        self.chat_calls += 1
        self.seen_messages.append(list(messages))
        val = self._next(self._side_effects)
        if callable(val):
            val = val(messages)
        if isinstance(val, AgentTurn):
            return val
        return AgentTurn(text=str(val))


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
            AgentTurn(text="Fallback reply 1"),
            AgentTurn(text="Fallback reply 2"),
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

    turn1 = router.generate_agent_reply(
        system_instruction="sys", messages=[{"role": "user", "text": "hi"}], tool_schemas=[]
    )
    assert turn1.text == "Fallback reply 1"
    assert turn1.provider == "gemini"
    assert turn1.model == "gemini-3.8-flash"
    assert turn1.fallback_used is True

    turn2 = router.generate_agent_reply(
        system_instruction="sys", messages=[{"role": "user", "text": "hi"}], tool_schemas=[]
    )
    assert turn2.text == "Fallback reply 2"
    assert turn2.fallback_used is True

    vecs = router.embed_texts(["nvidia"])
    assert vecs == [[0.1, 0.2]]
    assert router.last_embedding_provider == "gemini"
    assert p_primary.chat_calls == 4
    assert p_secondary.chat_calls == 4


def test_router_cooldown_and_disabled_fallback_and_all_failed() -> None:
    class _RateLimitError(RuntimeError):
        status_code = 429

    clock = _FakeClock(start=1000.0)
    p1 = _StubProvider(
        "dashscope",
        side_effects=[
            _RateLimitError("429 RESOURCE_EXHAUSTED"),
            AgentTurn(text="Primary recovered"),
        ],
    )
    p2 = _StubProvider(
        "openai",
        side_effects=[
            AgentTurn(text="Secondary 1"),
            AgentTurn(text="Secondary 2"),
            RuntimeError("Secondary transient failure"),
        ],
    )
    router = LLMRouter([p1, p2], cooldown_seconds=60.0, clock=clock)

    # First call hits p1 (429 -> cooled for 60s), falls back to p2.
    t1 = router.generate_agent_reply(
        system_instruction="s", messages=[{"role": "user", "text": "1"}], tool_schemas=[]
    )
    assert t1.provider == "openai"
    assert t1.fallback_used is True
    assert p1.chat_calls == 1
    assert "dashscope" in router.describe()["cooled_down_providers"]

    # Within cooldown window, p1 is skipped cleanly.
    clock.advance(30.0)
    t2 = router.generate_agent_reply(
        system_instruction="s", messages=[{"role": "user", "text": "2"}], tool_schemas=[]
    )
    assert t2.provider == "openai"
    assert p1.chat_calls == 1
    assert p2.chat_calls == 2

    # If p2 fails while p1 is still cooled, router still tries cooled p1 as last resort!
    t3 = router.generate_agent_reply(
        system_instruction="s", messages=[{"role": "user", "text": "3"}], tool_schemas=[]
    )
    assert t3.provider == "dashscope"
    assert t3.text == "Primary recovered"
    assert p1.chat_calls == 2
    assert router.describe()["cooled_down_providers"] == []

    # When fallback_enabled=False, router does not try p2.
    p_fail = _StubProvider("dashscope", side_effects=[_RateLimitError("429")])
    p_unused = _StubProvider("gemini", side_effects=[AgentTurn(text="should not run")])
    strict_router = LLMRouter([p_fail, p_unused], fallback_enabled=False)
    with pytest.raises(AllProvidersFailedError) as exc_info:
        strict_router.generate_agent_reply(
            system_instruction="s", messages=[{"role": "user", "text": "x"}], tool_schemas=[]
        )
    assert len(exc_info.value.attempts) == 1
    assert exc_info.value.attempts[0].provider == "dashscope"
    assert p_unused.chat_calls == 0

    # When all providers fail, AllProvidersFailedError summarizes every attempt.
    p_a = _StubProvider("dashscope", side_effects=[RuntimeError("ds down")])
    p_b = _StubProvider("gemini", side_effects=[_RateLimitError("429 quota")])
    broken = LLMRouter([p_a, p_b], fallback_enabled=True)
    with pytest.raises(AllProvidersFailedError) as all_err:
        broken.generate_agent_reply(
            system_instruction="s", messages=[{"role": "user", "text": "x"}], tool_schemas=[]
        )
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
        msgs = body["messages"]
        if msgs[-1]["content"][0]["type"] == "text":
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "list_catalog",
                            "input": {},
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "Anthropic agent done."}]}
        )

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
    assert compat.generate_agent_reply(
        system_instruction="sys", messages=[{"role": "user", "text": "hi"}], tool_schemas=[]
    ).text == "OpenAI OK"
    assert len(seen_openai_bodies) >= 2

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

    t_call = ant.generate_agent_reply(
        system_instruction="sys",
        messages=[{"role": "user", "text": "catalog?"}],
        tool_schemas=[{"name": "list_catalog", "description": "list", "parameters": {"type": "object"}}],
    )
    assert t_call.tool_calls[0].name == "list_catalog"
    t_done = ant.generate_agent_reply(
        system_instruction="sys",
        messages=[
            {"role": "user", "text": "catalog?"},
            {
                "role": "model",
                "text": None,
                "tool_calls": [{"name": "list_catalog", "args": {}, "call_id": "toolu_1"}],
            },
            {
                "role": "tool",
                "responses": [{"name": "list_catalog", "call_id": "toolu_1", "response": {"ok": True}}],
            },
        ],
        tool_schemas=[{"name": "list_catalog", "description": "list", "parameters": {"type": "object"}}],
    )
    assert t_done.text == "Anthropic agent done."
    assert len(seen_anthropic_bodies) == 3


def test_cross_provider_agent_turn_fallback_gemini_and_dashscope(tmp_path: Path) -> None:
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

    # Turn 1 succeeds on Gemini (producing raw_content=types.Content and call_id=None).
    # Turn 2 fails on Gemini with 429 and falls back to DashScope (OpenAI-compatible).
    gem_calls = 0

    class _FakeGenAIModels:
        def generate_content(self, **kwargs: Any) -> Any:
            nonlocal gem_calls
            gem_calls += 1
            if gem_calls == 1:
                fc = types.FunctionCall(name="get_entity_overview", args={"entity_name_or_id": "NVDA"})
                part = types.Part(function_call=fc)
                content = types.Content(role="model", parts=[part])
                cand = types.Candidate(content=content)
                return types.GenerateContentResponse(candidates=[cand])
            err = RuntimeError("429 RESOURCE_EXHAUSTED")
            err.code = 429  # type: ignore[attr-defined]
            raise err

    class _FakeGenAIClient:
        models = _FakeGenAIModels()

    seen_ds_messages: list[list[dict[str, Any]]] = []

    def ds_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_ds_messages.append(body["messages"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "NVIDIA via DashScope fallback."}}]},
        )

    settings = Settings(
        gemini_api_key="gkey",
        dashscope_api_key="dkey",
        dashscope_api_url="https://mock.dashscope.local/v1",
        embedding_dim=4,
    )
    gem = GeminiProvider(settings, client=_FakeGenAIClient())  # type: ignore[arg-type]
    ds = DashScopeProvider(settings, http_client=httpx.Client(transport=httpx.MockTransport(ds_handler)))
    router = LLMRouter([gem, ds])

    with OntologyDB(db_path, embedding_dim=4, read_only=True) as ro_db:
        agent = OntologyAgent(ro_db, router)
        reply = agent.ask("Check NVDA")

    assert reply == "NVIDIA via DashScope fallback."
    assert agent.last_provider == "dashscope"
    assert agent.last_fallback_used is True
    assert len(seen_ds_messages) == 1
    # Verify assistant tool_call id and tool response tool_call_id match cleanly!
    ds_msgs = seen_ds_messages[0]
    assistant_tc_id = ds_msgs[2]["tool_calls"][0]["id"]
    tool_resp_id = ds_msgs[3]["tool_call_id"]
    assert assistant_tc_id == tool_resp_id


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

    class _RateLimitError(RuntimeError):
        status_code = 429

    p_gem = _StubProvider(
        "gemini",
        chat_model="gemini-3.8-flash",
        side_effects=[_RateLimitError("429 RESOURCE_EXHAUSTED")],
    )
    p_ds = _StubProvider(
        "dashscope",
        chat_model="qwen3.8-flash",
        side_effects=[AgentTurn(text="Answered by DashScope fallback.")],
    )
    router = LLMRouter([p_gem, p_ds])

    settings = Settings(
        db_path=db_path,
        embedding_dim=4,
        data_dir=tmp_path,
        dashscope_api_key="super-secret-ds-key",
        gemini_api_key="super-secret-gm-key",
    )
    app = create_app(settings, llm=router)
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
