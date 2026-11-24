"""Offline tests for DashScope OpenAI-compatible provider, embeddings, and tool calling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from stock_ontology.agent import OntologyAgent
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.llm import (
    DashScopeClient,
    DashScopeProvider,
    GeminiProvider,
    LLMRouter,
    create_llm_client,
)
from stock_ontology.models import Node


def test_settings_resolve_provider_auto_and_overrides() -> None:
    s_gemini = Settings(gemini_api_key="gkey")
    assert s_gemini.resolve_provider() == "gemini"
    assert s_gemini.resolve_provider_chain() == ["gemini"]
    r_gemini = create_llm_client(s_gemini)
    assert isinstance(r_gemini, LLMRouter)
    assert isinstance(r_gemini.primary_provider, GeminiProvider)

    s_ds_only = Settings(dashscope_api_key="dkey")
    assert s_ds_only.resolve_provider() == "dashscope"
    assert s_ds_only.resolve_provider_chain() == ["dashscope"]
    r_ds_only = create_llm_client(s_ds_only)
    assert isinstance(r_ds_only.primary_provider, DashScopeProvider)

    s_both_key_only = Settings(gemini_api_key="gkey", dashscope_api_key="dkey")
    assert s_both_key_only.resolve_provider() == "gemini"
    assert s_both_key_only.resolve_provider_chain() == ["gemini", "dashscope"]

    s_both = Settings(
        gemini_api_key="gkey",
        dashscope_api_key="dkey",
        dashscope_api_url="https://example.dashscope/v1",
    )
    assert s_both.resolve_provider() == "gemini"
    assert s_both.resolve_provider_chain() == ["gemini", "dashscope"]
    r_both = create_llm_client(s_both)
    assert isinstance(r_both, LLMRouter)
    assert isinstance(r_both.primary_provider, GeminiProvider)
    assert [p.name for p in r_both.chat_providers] == ["gemini", "dashscope"]

    s_forced = Settings(
        llm_provider="dashscope",
        gemini_api_key="gkey",
        dashscope_api_key="dkey",
        dashscope_api_url="https://example.dashscope/v1",
    )
    assert s_forced.resolve_provider() == "dashscope"
    assert s_forced.resolve_provider_chain() == ["dashscope"]
    r_forced = create_llm_client(s_forced)
    assert isinstance(r_forced.primary_provider, DashScopeProvider)


def test_dashscope_embeddings_structured_and_agent_tools(tmp_path: Path) -> None:
    seen_requests: list[tuple[str, dict[str, Any]]] = []
    agent_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_requests.append((request.url.path, body))

        if request.url.path.endswith("/embeddings"):
            inputs = body["input"]
            assert body["model"] == "qwen3.7-text-embedding"
            assert body["dimensions"] == 8
            data = [
                {"object": "embedding", "index": idx, "embedding": [1.0] + [0.0] * 7}
                for idx in range(len(inputs))
            ]
            return httpx.Response(200, json={"object": "list", "data": data})

        if request.url.path.endswith("/chat/completions"):
            assert body["model"] == "qwen3.8-flash"
            resp_fmt = body.get("response_format") or {}
            schema_name = (resp_fmt.get("json_schema") or {}).get("name")
            msgs = body["messages"]

            if schema_name:
                assert body["enable_thinking"] is False
            else:
                # Agent turns go through Pydantic AI's OpenAI model, which sends the agent's model settings.
                agent_bodies.append(body)
                assert body.get("max_tokens", body.get("max_completion_tokens")) == 77, sorted(body)

            if schema_name == "ExtractionResult":
                user_prompt = msgs[-1]["content"]
                assert "Source file metadata:" in user_prompt
                assert "Folder entity hint:" not in user_prompt
                payload = {
                    "entities": [
                        {
                            "temp_id": "e1",
                            "name": "NVIDIA",
                            "summary": "AI GPU leader",
                            "aliases": ["NVDA"],
                            "entity_type": "company",
                            "facets": [{"key": "ticker", "value": "NVDA"}],
                        }
                    ],
                    "events": [],
                    "views": [],
                    "themes": [],
                    "edges": [],
                }
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"message": {"role": "assistant", "content": f"```json\n{json.dumps(payload)}\n```"}}
                        ]
                    },
                )

            if schema_name == "ConsensusSynthesis":
                payload = {
                    "stance": "buy",
                    "support_strength": "strong",
                    "conviction": "high",
                    "summary": "Strong AI capex demand.",
                    "pillars": ["Hyperscaler capex grows >20%"],
                    "supporting_node_ids": [],
                    "contradicting_node_ids": [],
                    "facets": [],
                }
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}]},
                )

            # Agent tool-calling turns, as full OpenAI chat completions.
            completion = {"id": "cmpl", "object": "chat.completion", "created": 0, "model": body["model"]}
            if msgs[-1]["role"] == "user":
                return httpx.Response(
                    200,
                    json={
                        **completion,
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "tool_calls",
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_nvda_1",
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
            if msgs[-1]["role"] == "tool":
                assert msgs[-1]["tool_call_id"] == "call_nvda_1"
                tool_data = json.loads(msgs[-1]["content"])
                return httpx.Response(
                    200,
                    json={
                        **completion,
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": f"Confirmed consensus for {tool_data['entity']['name']}.",
                                }
                            }
                        ]
                    },
                )

        return httpx.Response(404, json={"error": "not found"})

    settings = Settings(
        dashscope_api_key="test-key",
        dashscope_api_url="https://mock.dashscope.local/compatible-mode/v1",
        embedding_dim=8,
    )
    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    client = DashScopeClient(settings, http_client=mock_http)

    # 1. Batching 12 embeddings -> 2 requests (10 + 2).
    vecs = client.embed_texts([f"item {i}" for i in range(12)])
    assert len(vecs) == 12
    emb_reqs = [b for p, b in seen_requests if p.endswith("/embeddings")]
    assert [len(b["input"]) for b in emb_reqs] == [10, 2]

    # 2. Structured ExtractionResult & ConsensusSynthesis.
    extracted = client.extract_document(
        text="NVIDIA update",
        source_meta={"file_path": "NVDA/test.md"},
        existing_catalog="",
        known_facets={},
    )
    assert extracted.entities[0].name == "NVIDIA"

    nvda = Node(
        id="ent_nvda",
        node_type="entity",
        name="NVIDIA",
        summary="AI GPU leader",
        aliases=["NVDA"],
        facets={"entity_type": "company", "ticker": "NVDA"},
    )
    syn = client.synthesize_consensus(
        company=nvda, events=[], views=[], themes=[], prior_consensus=None
    )
    assert syn.stance == "bullish"

    # 3. Agent tool-calling round-trip against read-only DB.
    db_path = tmp_path / "ds_agent.db"
    with OntologyDB(db_path, embedding_dim=8, read_only=False) as db:
        db.upsert_node(nvda, embedding=[1.0] + [0.0] * 7)

    with OntologyDB(db_path, embedding_dim=8, read_only=True) as ro_db:
        import httpx2
        from pydantic_ai.models.openai import OpenAIChatModel

        def agent_handler(request: httpx2.Request) -> httpx2.Response:
            resp = handler(httpx.Request(request.method, str(request.url), content=request.content))
            return httpx2.Response(resp.status_code, content=resp.content, headers=dict(resp.headers))

        from pydantic_ai.providers.openai import OpenAIProvider

        model = OpenAIChatModel(
            settings.dashscope_model,
            provider=OpenAIProvider(
                base_url=settings.dashscope_api_url,
                api_key=settings.dashscope_api_key,
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(agent_handler)),
            ),
        )
        agent = OntologyAgent(ro_db, client, model=model, model_settings={"max_tokens": 77})
        reply = agent.ask("What is our view on NVDA?")
        assert "Confirmed consensus for NVIDIA" in reply
        assert agent.tool_trace[0]["tool"] == "get_entity_overview"
        assert len(agent_bodies) == 2
