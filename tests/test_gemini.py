"""Offline tests for the Google Gemini provider adapter, embeddings, structured output, and tools."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import _transformers as genai_transformers
from google.genai import types

from stock_ontology.config import Settings
from stock_ontology.llm import (
    GeminiClient,
    GeminiProvider,
    LLMProviderError,
    ProviderConfigError,
)
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
    assert syn.stance == "bullish"
    assert syn.supporting_node_ids == ["ev_1"]

    mode["case"] = "whitespace"
    with pytest.raises(LLMProviderError) as ws_err:
        prov.extract_document(text="x", source_meta={}, existing_catalog="", known_facets={})
    assert ws_err.value.error_kind == "invalid_response"

    mode["case"] = "bad_json"
    with pytest.raises(LLMProviderError) as json_err:
        prov.extract_document(text="x", source_meta={}, existing_catalog="", known_facets={})
    assert json_err.value.error_kind == "invalid_response"


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
        prov.generate_structured(system_instruction="sys", prompt="hi", schema=ConsensusSynthesis)
    assert exc_info.value.provider == "gemini"
    assert exc_info.value.error_kind == expected_kind


def _api_exc(message: str, *, code: int) -> RuntimeError:
    err = RuntimeError(message)
    err.code = code  # type: ignore[attr-defined]
    return err
