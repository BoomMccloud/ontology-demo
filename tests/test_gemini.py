"""Offline tests for the Google Gemini provider adapter, embeddings, structured output, and tools."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import _transformers as genai_transformers
from google.genai import types

from stock_ontology.agent import OntologyAgent
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.llm import (
    DashScopeProvider,
    GeminiClient,
    GeminiProvider,
    LLMProviderError,
    LLMRouter,
    ProviderConfigError,
)
from stock_ontology.llm.pydantic_ai_model import to_llm_messages
from stock_ontology.models import ConsensusSynthesis, ExtractedEntity, ExtractionResult, Node


def test_gemini_provider_config_timeout_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    assert GeminiClient is GeminiProvider

    unconfigured = GeminiProvider(Settings(gemini_api_key=None))
    assert unconfigured.is_configured() is False
    with pytest.raises(ProviderConfigError) as cfg_exc:
        unconfigured.generate_structured(
            system_instruction="sys", prompt="hi", schema=ExtractionResult
        )
    assert cfg_exc.value.error_kind == "config"
    assert cfg_exc.value.provider == "gemini"

    created_clients: list[dict[str, Any]] = []

    class _OwnedFakeClient:
        def __init__(self, *, api_key: str, http_options: types.HttpOptions) -> None:
            self.api_key = api_key
            self.http_options = http_options
            self.closed = 0
            created_clients.append({"client": self, "api_key": api_key, "http_options": http_options})

        def close(self) -> None:
            self.closed += 1

    monkeypatch.setattr("stock_ontology.llm.providers.gemini.genai.Client", _OwnedFakeClient)

    settings = Settings(gemini_api_key="test-gemini-key", llm_timeout_seconds=45.5)
    owned = GeminiProvider(settings)
    assert owned.is_configured() is True
    assert owned.chat_model == "gemini-3.8-flash"
    assert owned.embedding_model == "gemini-embedding-2"

    client_instance = owned._get_client()
    assert len(created_clients) == 1
    assert created_clients[0]["api_key"] == "test-gemini-key"
    assert created_clients[0]["http_options"].timeout == 45500

    # close() closes owned client once and is idempotent.
    owned.close()
    owned.close()
    assert client_instance.closed == 1  # type: ignore[attr-defined]

    # Injected client counts as configured and is never closed by provider.close().
    injected_client = _OwnedFakeClient(
        api_key="injected", http_options=types.HttpOptions(timeout=1000)
    )
    injected = GeminiProvider(Settings(gemini_api_key=None), client=injected_client)  # type: ignore[arg-type]
    assert injected.is_configured() is True
    assert injected._get_client() is injected_client
    injected.close()
    assert injected_client.closed == 0


def test_gemini_embeddings_content_batching_and_sanitization() -> None:
    calls: list[dict[str, Any]] = []

    class _FakeModels:
        def embed_content(
            self, *, model: str, contents: Any, config: types.EmbedContentConfig
        ) -> types.EmbedContentResponse:
            calls.append({"model": model, "contents": contents, "config": config})
            assert isinstance(contents, list)
            assert all(isinstance(item, types.Content) for item in contents)
            # Regression check: google-genai's multimodal embedding transformer must preserve
            # 1 Content per input text rather than merging consecutive strings.
            assert len(genai_transformers.t_contents(contents)) == len(contents)
            return types.EmbedContentResponse(
                embeddings=[
                    types.ContentEmbedding(values=[float(idx), 0.5, 0.25, 0.125])
                    for idx in range(len(contents))
                ]
            )

    class _FakeClient:
        models = _FakeModels()

    settings = Settings(
        gemini_api_key="gkey",
        embedding_model="gemini-embedding-2",
        embedding_dim=4,
    )
    prov = GeminiProvider(settings, client=_FakeClient())  # type: ignore[arg-type]

    assert prov.embed_texts([]) == []
    assert calls == []

    inputs = ["" if i == 0 else ("   \n\t " if i == 1 else f"note {i}") for i in range(55)]
    vecs = prov.embed_texts(inputs)
    assert len(vecs) == 55
    assert [len(c["contents"]) for c in calls] == [50, 5]
    assert calls[0]["model"] == "gemini-embedding-2"
    assert calls[0]["config"].output_dimensionality == 4

    # Empty / whitespace strings are sanitized to "empty" before sending to Gemini.
    assert calls[0]["contents"][0].parts[0].text == "empty"
    assert calls[0]["contents"][1].parts[0].text == "empty"
    assert calls[0]["contents"][2].parts[0].text == "note 2"

    # Mismatched count -> invalid_response.
    class _BadCountModels:
        def embed_content(self, **kwargs: Any) -> types.EmbedContentResponse:
            return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=[1.0, 0.0, 0.0, 0.0])])

    bad_count_prov = GeminiProvider(settings, client=SimpleNamespace(models=_BadCountModels()))  # type: ignore[arg-type]
    with pytest.raises(LLMProviderError) as count_err:
        bad_count_prov.embed_texts(["one", "two"])
    assert count_err.value.error_kind == "invalid_response"

    # Empty vector values -> invalid_response.
    class _EmptyValuesModels:
        def embed_content(self, **kwargs: Any) -> types.EmbedContentResponse:
            return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=[])])

    empty_val_prov = GeminiProvider(settings, client=SimpleNamespace(models=_EmptyValuesModels()))  # type: ignore[arg-type]
    with pytest.raises(LLMProviderError) as val_err:
        empty_val_prov.embed_texts(["one"])
    assert val_err.value.error_kind == "invalid_response"


def test_gemini_structured_extraction_consensus_and_errors() -> None:
    seen_configs: list[types.GenerateContentConfig] = []

    expected_ext = ExtractionResult(
        entities=[
            ExtractedEntity(
                temp_id="e1",
                name="NVIDIA",
                summary="AI GPU leader",
                aliases=["NVDA"],
                entity_type="company",
            )
        ]
    )
    consensus_payload = {
        "stance": "buy",
        "support_strength": "strong",
        "conviction": "high",
        "summary": "Blackwell demand remains strong.",
        "pillars": ["Hyperscaler AI capex grows >20%"],
        "supporting_node_ids": ["ev_1"],
        "contradicting_node_ids": [],
        "facets": [],
    }

    mode = {"case": "parsed"}

    class _FakeModels:
        def generate_content(
            self, *, model: str, contents: Any, config: types.GenerateContentConfig
        ) -> Any:
            seen_configs.append(config)
            if mode["case"] == "parsed":
                return SimpleNamespace(parsed=expected_ext, text="")
            if mode["case"] == "fenced_text":
                return SimpleNamespace(
                    parsed=None,
                    text=f"```json\n{json.dumps(consensus_payload)}\n```",
                )
            if mode["case"] == "whitespace":
                return SimpleNamespace(parsed=None, text="   \n\t  ")
            return SimpleNamespace(parsed=None, text="{not valid json")

    prov = GeminiProvider(
        Settings(gemini_api_key="gkey"),
        client=SimpleNamespace(models=_FakeModels()),  # type: ignore[arg-type]
    )

    ext = prov.extract_document(
        text="NVDA update",
        source_meta={"file_path": "NVDA/note.md"},
        existing_catalog="",
        known_facets={},
    )
    assert ext == expected_ext
    assert seen_configs[-1].response_mime_type == "application/json"
    assert seen_configs[-1].response_schema is ExtractionResult

    mode["case"] = "fenced_text"
    nvda = Node(id="ent_nvda", node_type="entity", name="NVIDIA", summary="GPU leader")
    syn = prov.synthesize_consensus(
        company=nvda, events=[], views=[], themes=[], prior_consensus=None
    )
    assert isinstance(syn, ConsensusSynthesis)
    assert syn.stance == "buy"
    assert syn.supporting_node_ids == ["ev_1"]

    mode["case"] = "whitespace"
    with pytest.raises(LLMProviderError) as ws_err:
        prov.extract_document(text="x", source_meta={}, existing_catalog="", known_facets={})
    assert ws_err.value.error_kind == "invalid_response"

    mode["case"] = "bad_json"
    with pytest.raises(LLMProviderError) as json_err:
        prov.extract_document(text="x", source_meta={}, existing_catalog="", known_facets={})
    assert json_err.value.error_kind == "invalid_response"


def test_gemini_agent_tool_calling_thought_filtering_and_empty_tools(tmp_path: Path) -> None:
    db_path = tmp_path / "gemini_agent.db"
    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        db.upsert_node(
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="AI GPU leader",
                aliases=["NVDA"],
                facets={"entity_type": "company", "ticker": "NVDA"},
            ),
            embedding=[1.0, 0.0, 0.0, 0.0],
        )

    seen_calls: list[dict[str, Any]] = []
    call_idx = 0

    class _FakeModels:
        def generate_content(
            self, *, model: str, contents: list[types.Content], config: types.GenerateContentConfig
        ) -> types.GenerateContentResponse:
            nonlocal call_idx
            call_idx += 1
            seen_calls.append({"contents": contents, "config": config})
            if call_idx == 1:
                thought_part = types.Part(text="internal reasoning", thought=True)
                fc_part = types.Part(
                    function_call=types.FunctionCall(
                        id="call_gem_1",
                        name="get_entity_overview",
                        args={"entity_name_or_id": "NVDA"},
                    ),
                    thought_signature=b"opaque_sig_1",
                )
                return types.GenerateContentResponse(
                    candidates=[
                        types.Candidate(content=types.Content(role="model", parts=[thought_part, fc_part]))
                    ]
                )
            if call_idx == 2:
                # Verify FunctionResponse.id matches call_gem_1 from turn 1.
                tool_content = contents[-1]
                assert tool_content.role == "user"
                assert tool_content.parts is not None
                fr = tool_content.parts[0].function_response
                assert fr is not None
                assert fr.id == "call_gem_1"
                assert fr.name == "get_entity_overview"
                thought_part = types.Part(text="more thoughts", thought=True)
                answer_part = types.Part(text="NVIDIA summary.")
                return types.GenerateContentResponse(
                    candidates=[
                        types.Candidate(content=types.Content(role="model", parts=[thought_part, answer_part]))
                    ]
                )
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(content=types.Content(role="model", parts=[types.Part(text="No tools needed.")]))
                ]
            )

    prov = GeminiProvider(
        Settings(gemini_api_key="gkey"),
        client=SimpleNamespace(models=_FakeModels()),  # type: ignore[arg-type]
    )

    with OntologyDB(db_path, embedding_dim=4, read_only=True) as ro_db:
        agent = OntologyAgent(ro_db, prov)
        reply = agent.ask("Summarize NVDA")

    assert reply == "NVIDIA summary."
    assert agent.last_provider == "gemini"
    assert agent.last_model == "gemini-3.8-flash"
    assert agent.tool_trace[0]["tool"] == "get_entity_overview"
    # Turn 1 must not expose thought text as assistant text.
    history = to_llm_messages(agent.messages)
    assert history[1]["text"] is None
    assert history[1]["tool_calls"][0]["call_id"] == "call_gem_1"
    assert "internal reasoning" not in reply
    assert "more thoughts" not in reply

    # Empty tool_schemas omits config.tools rather than sending an empty Tool declaration list.
    empty_tools_turn = prov.generate_agent_reply(
        system_instruction="sys",
        messages=[{"role": "user", "text": "hello"}],
        tool_schemas=[],
    )
    assert empty_tools_turn.text == "No tools needed."
    assert seen_calls[-1]["config"].tools is None


def test_cross_provider_fallback_dashscope_to_gemini_sets_thought_signature(tmp_path: Path) -> None:
    db_path = tmp_path / "ds_to_gem.db"
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

    ds_calls = 0

    def ds_handler(request: httpx.Request) -> httpx.Response:
        nonlocal ds_calls
        ds_calls += 1
        if ds_calls == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_ds_99",
                                        "type": "function",
                                        "function": {
                                            "name": "get_entity_overview",
                                            "arguments": json.dumps({"entity_name_or_id": "NVDA"}),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(429, json={"error": {"message": "RESOURCE_EXHAUSTED"}})

    seen_gemini_contents: list[list[types.Content]] = []

    class _FakeGenAIModels:
        def generate_content(
            self, *, model: str, contents: list[types.Content], config: types.GenerateContentConfig
        ) -> types.GenerateContentResponse:
            seen_gemini_contents.append(contents)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model",
                            parts=[types.Part.from_text(text="NVIDIA via Gemini fallback.")],
                        )
                    )
                ]
            )

    settings = Settings(
        dashscope_api_key="dkey",
        dashscope_api_url="https://mock.dashscope.local/v1",
        gemini_api_key="gkey",
        embedding_dim=4,
    )
    ds = DashScopeProvider(settings, http_client=httpx.Client(transport=httpx.MockTransport(ds_handler)))
    gem = GeminiProvider(settings, client=SimpleNamespace(models=_FakeGenAIModels()))  # type: ignore[arg-type]
    router = LLMRouter([ds, gem])

    with OntologyDB(db_path, embedding_dim=4, read_only=True) as ro_db:
        agent = OntologyAgent(ro_db, router)
        reply = agent.ask("Check NVDA")

    assert reply == "NVIDIA via Gemini fallback."
    assert agent.last_provider == "gemini"
    assert agent.last_fallback_used is True
    assert len(seen_gemini_contents) == 1

    gem_msgs = seen_gemini_contents[0]
    assert len(gem_msgs) == 3
    model_msg = gem_msgs[1]
    tool_msg = gem_msgs[2]
    assert model_msg.role == "model"
    assert model_msg.parts is not None
    assert model_msg.parts[0].function_call is not None
    assert model_msg.parts[0].function_call.name == "get_entity_overview"
    assert model_msg.parts[0].function_call.id == "call_ds_99"
    assert model_msg.parts[0].thought_signature == b"skip_thought_signature_validator"

    assert tool_msg.role == "user"
    assert tool_msg.parts is not None
    assert tool_msg.parts[0].function_response is not None
    assert tool_msg.parts[0].function_response.name == "get_entity_overview"
    assert tool_msg.parts[0].function_response.id == "call_ds_99"


@pytest.mark.parametrize(
    ("exc_factory", "expected_kind"),
    [
        (lambda: _api_exc("429 RESOURCE_EXHAUSTED", code=429), "rate_limit"),
        (lambda: _api_exc("400 API_KEY_INVALID. Please pass a valid API key.", code=400), "auth"),
        (lambda: _api_exc("404 NOT_FOUND", code=404), "not_found"),
        (lambda: _api_exc("503 Service Unavailable", code=503), "server"),
        (lambda: httpx.ReadTimeout("timed out"), "network"),
    ],
)
def test_gemini_error_classification(
    exc_factory: Any, expected_kind: str
) -> None:
    class _FailingModels:
        def generate_content(self, **kwargs: Any) -> Any:
            raise exc_factory()

    prov = GeminiProvider(
        Settings(gemini_api_key="gkey"),
        client=SimpleNamespace(models=_FailingModels()),  # type: ignore[arg-type]
    )
    with pytest.raises(LLMProviderError) as exc_info:
        prov.generate_agent_reply(
            system_instruction="sys",
            messages=[{"role": "user", "text": "hi"}],
            tool_schemas=[],
        )
    assert exc_info.value.provider == "gemini"
    assert exc_info.value.error_kind == expected_kind


def _api_exc(message: str, *, code: int) -> RuntimeError:
    err = RuntimeError(message)
    err.code = code  # type: ignore[attr-defined]
    return err
