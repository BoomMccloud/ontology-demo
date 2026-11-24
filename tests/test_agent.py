"""Offline tests for the strictly read-only PM query agent (UX #1 and UX #2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stock_ontology.agent import OntologyAgent
from stock_ontology.db import OntologyDB
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from stock_ontology.models import ConsensusSynthesis, Edge, ExtractionResult, Node

DIM = 16


def _unit_vec(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[idx % DIM] = 1.0
    return v


def _text(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(text)])


def _call(name: str, args: dict[str, Any], call_id: str | None = None) -> ModelResponse:
    part = ToolCallPart(name, args, tool_call_id=call_id) if call_id else ToolCallPart(name, args)
    return ModelResponse(parts=[part])


def _last_part(messages: list[ModelMessage]) -> Any:
    """The last part of the latest request: the user's prompt or a tool return."""
    request = next(m for m in reversed(messages) if isinstance(m, ModelRequest))
    return request.parts[-1]


def _seed_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU and NVLink platform leader.",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        vrt = Node(
            id="ent_vrt",
            node_type="entity",
            name="Vertiv",
            summary="Liquid cooling CDU and UPS provider.",
            aliases=["VRT"],
            facets={"entity_type": "company", "ticker": "VRT"},
        )
        tsmc = Node(
            id="ent_tsmc",
            node_type="entity",
            name="TSMC",
            summary="Foundry and CoWoS packaging supplier.",
            aliases=["TSM"],
            facets={"entity_type": "company", "ticker": "TSM"},
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Grid power and >100kW rack thermal density constraints.",
            facets={"stage": "accelerating"},
        )
        ev_nvda = Node(
            id="evt_q3",
            node_type="event",
            name="NVL72 Q4 Ramp",
            summary="GB200 NVL72 ramping in Q4; hyperscaler capex +18% YoY.",
            facets={
                "event_type": "fact",
                "event_date": "2026-10-15",
                "source": {"file_path": "NVDA/2026-10-15_q3_preview.md"},
            },
            source_doc_id="doc_nvda_q3",
        )
        cons_nvda = Node(
            id="vw_cons_nvda",
            node_type="view",
            name="Consensus: Buy NVIDIA",
            summary="Buy NVDA on CUDA moat and hyperscaler AI capex; watch rack thermal/power pacing.",
            facets={
                "view_type": "consensus",
                "stance": "buy",
                "support_strength": "strong",
                "conviction": "high",
                "status": "active",
                "pillars": [
                    "Hyperscaler AI capex grows >20% YoY",
                    "Blackwell NVL72 rack power/cooling issues remain localized to small colos",
                ],
            },
        )

        for idx, node in enumerate([nvda, vrt, tsmc, theme, ev_nvda]):
            db.upsert_node(node, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(id="ed1", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_nvda_q3", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed2", from_id="ent_vrt", to_id="thm_power", relation="BENEFITS_FROM", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed3", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed4", from_id="ent_tsmc", to_id="ent_nvda", relation="SUPPLIES_TO", facets={"basis": "extracted"})
        )
        db.upsert_consensus_view(
            "ent_nvda",
            cons_nvda,
            _unit_vec(6),
            supporting_ids=["evt_q3"],
            contradicting_ids=[],
        )


class ScriptedAgentLLM:
    """Offline `LLMClient` for tool embeddings, plus a scripted Pydantic AI model that inspects real tool responses."""

    def __init__(self, loop_forever: bool = False) -> None:
        self.loop_forever = loop_forever

    @property
    def model(self) -> FunctionModel:
        return FunctionModel(self.respond, model_name="scripted")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            low = t.lower()
            if "nvda" in low or "nvidia" in low:
                out.append(_unit_vec(0))
            elif "power" in low:
                out.append(_unit_vec(3))
            else:
                out.append(_unit_vec(15))
        return out

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if self.loop_forever:
            return _call("list_catalog", {})

        last = _last_part(messages)
        if isinstance(last, UserPromptPart):
            text = str(last.content).lower()
            if "theme" in text or "power bottleneck" in text:
                return _call("find_theme_companies", {"theme_query": "AI Data Center Power Bottleneck"})
            if "consensus" in text or "meeting" in text:
                return _call("get_entity_overview", {"entity_name_or_id": "NVDA"})
            if "how many" in text and "negative" in text:
                return _call(
                    "query_entity_signals",
                    {
                        "entity_name_or_id": "NVDA",
                        "sentiments": ["negative"],
                        "categories": ["rumor", "news"],
                    },
                )
            return _call("list_catalog", {})

        if isinstance(last, ToolReturnPart):
            tool_name = last.tool_name
            payload = last.content
            if tool_name == "get_entity_overview":
                cons = payload["consensus"]
                pillars = cons["facets"]["pillars"]
                src = payload["events"][0]["facets"]["source"]["file_path"]
                return _text(
                    f"Verdict: Keep ({cons['facets']['stance'].upper()}). "
                    f"Checked pillars: {json.dumps(pillars)}. "
                    f"Source: {src}. Read-only mode: save note to data/NVDA/ and run ingest to update DB."
                )
            if tool_name == "query_entity_signals":
                total = payload["total_matched"]
                unclassified = payload["unclassified_in_scope"]
                names = ", ".join(it["name"] for it in payload["items"])
                return _text(
                    f"Found {total} negative rumor/news items for {payload['entity']['name']}: "
                    f"{names}. Unclassified legacy items in scope: {unclassified}."
                )
            if tool_name == "find_theme_companies":
                names = [c["company"]["name"] for c in payload["companies"]]
                return _text(f"Affected companies: {', '.join(sorted(names))}.")
            return _text(json.dumps(payload))

        return _text("No action.")


def test_agent_requires_read_only_db(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as writable_db:
        with pytest.raises(ValueError, match="read-only"):
            OntologyAgent(writable_db, ScriptedAgentLLM(), model=ScriptedAgentLLM().model)


def test_agent_ux1_meeting_note_consensus_check(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        llm = ScriptedAgentLLM()
        agent = OntologyAgent(ro_db, llm, model=llm.model)
        reply = agent.ask(
            "I just had a meeting with a supply engineer confirming Blackwell yields are fine "
            "and only small colos face transformer delays. Does this change our NVDA consensus?"
        )

        assert "Keep (BULLISH)" in reply
        assert "NVDA/2026-10-15_q3_preview.md" in reply
        assert "read-only" in reply.lower()
        assert agent.tool_trace[0]["tool"] == "get_entity_overview"
        # Strict one-way guarantee: DB stats and consensus node remain untouched.
        assert ro_db.get_stats() == before_stats


def test_agent_ux2_theme_related_companies(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        llm = ScriptedAgentLLM()
        agent = OntologyAgent(ro_db, llm, model=llm.model)
        reply = agent.ask(
            "In this meeting we discussed AI Data Center Power Bottleneck. What are the related companies?"
        )

        assert "NVIDIA" in reply and "Vertiv" in reply
        assert "TSMC" not in reply  # a supplier, not an affected company
        assert agent.tool_trace[0]["tool"] == "find_theme_companies"


def test_agent_tool_error_and_max_rounds_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        llm = ScriptedAgentLLM(loop_forever=True)
        agent = OntologyAgent(ro_db, llm, model=llm.model)
        err_res = agent.execute_tool("nonexistent_tool", {})
        assert "error" in err_res

        missing_ent = agent.execute_tool("get_entity_overview", {"entity_name_or_id": "DOES_NOT_EXIST"})
        assert "error" in missing_ent

        bounded = agent.ask("Infinite loop test", max_rounds=2)
        assert "maximum tool-calling rounds" in bounded.lower()


def test_agent_ux3_query_entity_signals_negative_rumors_and_news(tmp_path: Path) -> None:
    db_path = tmp_path / "signals.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Consumer hardware giant.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        evt_sec = Node(
            id="evt_sec",
            node_type="event",
            name="SEC Civil Inquiry",
            summary="Reported inquiry into disclosure practices.",
            facets={
                "event_type": "news",
                "status": "rumored",
                "sentiment": "negative",
                "event_date": "2026-11-15",
                "source": {"file_path": "NVDA/2026-11-15_news.md"},
            },
            source_doc_id="doc_s1",
        )
        vw_delay = Node(
            id="vw_delay",
            node_type="view",
            name="Rubin Yield Rumor",
            summary="Rumor of early packaging yield caution.",
            facets={
                "view_type": "rumor",
                "stance": "cautious",
                "sentiment": "negative",
                "as_of": "2026-11-16",
                "source": {"file_path": "NVDA/2026-11-16_rumor.md"},
            },
            source_doc_id="doc_s2",
        )
        evt_dual = Node(
            id="evt_dual",
            node_type="event",
            name="Edge Silicon Shift",
            summary="Positive for Apple, negative for NVIDIA backend.",
            facets={
                "event_type": "news",
                "status": "occurred",
                "sentiment": "mixed",
                "event_date": "2026-11-17",
                "source": {"file_path": "AAPL/2026-11-17_news.md"},
            },
            source_doc_id="doc_s3",
        )
        evt_win = Node(
            id="evt_win",
            node_type="event",
            name="Hyperscaler GPU Order",
            summary="Large order expansion.",
            facets={
                "event_type": "news",
                "status": "occurred",
                "sentiment": "positive",
                "event_date": "2026-11-18",
                "source": {"file_path": "NVDA/2026-11-18_news.md"},
            },
            source_doc_id="doc_s4",
        )
        evt_old = Node(
            id="evt_old",
            node_type="event",
            name="Legacy Unclassified News",
            summary="Pre-sentiment news item.",
            facets={
                "event_type": "news",
                "status": "occurred",
                "event_date": "2026-09-01",
                "source": {"file_path": "NVDA/2026-09-01_old.md"},
            },
            source_doc_id="doc_s5",
        )

        for idx, node in enumerate([aapl, evt_sec, vw_delay, evt_dual, evt_win, evt_old], start=7):
            db.upsert_node(node, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(id="es1", from_id="evt_sec", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="es2", from_id="vw_delay", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s2", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(
                id="es3_nvda",
                from_id="evt_dual",
                to_id="ent_nvda",
                relation="ABOUT",
                facets={"sentiment": "negative", "basis": "extracted"},
                source_doc_id="doc_s3",
            )
        )
        db.upsert_edge(
            Edge(
                id="es3_aapl",
                from_id="evt_dual",
                to_id="ent_aapl",
                relation="ABOUT",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_s3",
            )
        )
        db.upsert_edge(
            Edge(id="es4", from_id="evt_win", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s4", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="es5", from_id="evt_old", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s5", facets={"basis": "extracted"})
        )

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        llm = ScriptedAgentLLM()
        agent = OntologyAgent(ro_db, llm, model=llm.model)
        reply = agent.ask("How many negative rumors or news have we heard about NVDA?")

        assert "Found 3 negative rumor/news items for NVIDIA" in reply
        assert "Unclassified legacy items in scope: 1" in reply
        assert agent.tool_trace[0]["tool"] == "query_entity_signals"
        payload = agent.tool_trace[0]["result"]
        assert payload["total_matched"] == 3
        assert payload["unclassified_in_scope"] == 1
        dual_item = next(it for it in payload["items"] if it["id"] == "evt_dual")
        assert dual_item["effective_sentiment"] == "negative"
        assert dual_item["sentiment_source"] == "edge"

        # Test bare string coercion & argument validation.
        coerced = agent.execute_tool(
            "query_entity_signals",
            {"entity_name_or_id": "NVDA", "sentiments": "negative", "categories": "rumor"},
        )
        assert coerced["total_matched"] == 2

        bad_sent = agent.execute_tool(
            "query_entity_signals",
            {"entity_name_or_id": "NVDA", "sentiments": ["bogus"]},
        )
        assert "error" in bad_sent

        bad_nt = agent.execute_tool(
            "query_entity_signals",
            {"entity_name_or_id": "NVDA", "node_types": ["theme"]},
        )
        assert "error" in bad_nt

        assert ro_db.get_stats() == before_stats


class ExtraToolsetLLM(ScriptedAgentLLM):
    """Scripted model that calls a non-ontology tool only when the agent offers it."""

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = _last_part(messages)
        if isinstance(last, UserPromptPart):
            offered = {tool.name for tool in info.function_tools}
            if "get_house_view" not in offered:
                return _text("House view tool was not offered.")
            return _call("get_house_view", {"ticker": "NVDA"}, call_id="call_hv")
        if isinstance(last, ToolReturnPart):
            return _text(f"House view from {last.tool_name}: {json.dumps(last.content)}")
        return _text("No action.")


def test_agent_runs_tools_from_extra_pydantic_ai_toolset(tmp_path: Path) -> None:
    from pydantic_ai import FunctionToolset

    def get_house_view(ticker: str) -> dict[str, str]:
        """Return the desk's house view for a ticker."""
        return {"ticker": ticker, "house_view": "OVERWEIGHT-7731"}

    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        llm = ExtraToolsetLLM()
        agent = OntologyAgent(
            ro_db,
            llm,
            model=llm.model,
            toolsets=[FunctionToolset([get_house_view])],
        )
        reply = agent.ask("What is the house view on NVDA?")

        assert "get_house_view" in reply
        assert "OVERWEIGHT-7731" in reply
        assert [entry["tool"] for entry in agent.tool_trace] == ["get_house_view"]
        assert agent.tool_trace[0]["args"] == {"ticker": "NVDA"}
        assert ro_db.get_stats() == before_stats


class RecordingAgentLLM(ScriptedAgentLLM):
    """Scripted model that records every request the agent sends to its Pydantic AI model."""

    def __init__(self, turns: list[ModelResponse]) -> None:
        super().__init__()
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(
            {
                "instructions": info.instructions,
                "messages": list(messages),
                "tool_schemas": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_json_schema,
                    }
                    for tool in info.function_tools
                ],
            }
        )
        return self.turns.pop(0)


def test_agent_offers_ontology_tools_with_existing_schemas_and_prompt(tmp_path: Path) -> None:
    from stock_ontology.agent import TOOL_SCHEMAS, build_agent_system_prompt

    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        llm = RecordingAgentLLM([_text("Hello.")])
        agent = OntologyAgent(ro_db, llm, model=llm.model, language="zh")
        assert agent.ask("hi") == "Hello."

    request = llm.requests[0]
    assert request["tool_schemas"] == TOOL_SCHEMAS
    assert request["instructions"] == build_agent_system_prompt("zh")
    [only] = request["messages"]
    assert isinstance(only, ModelRequest)
    assert [(type(p), p.content) for p in only.parts] == [(UserPromptPart, "hi")]


class ProviderStampedAgentLLM(ScriptedAgentLLM):
    """Scripted model that stamps each model call with a distinct provider."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        response = super().respond(messages, info)
        self.calls += 1
        response.provider_name = f"prov-{self.calls}"
        return response


def test_agent_chat_returns_immutable_turn_contract(tmp_path: Path) -> None:
    import dataclasses

    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        from pydantic_ai.exceptions import ModelHTTPError
        from pydantic_ai.models.fallback import FallbackModel

        def rate_limited(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise ModelHTTPError(429, "model-x", {"error": "quota"})

        llm = ProviderStampedAgentLLM()
        agent = OntologyAgent(ro_db, llm, model=FunctionModel(llm.respond, model_name="model-a"))
        first = agent.chat("Does this meeting change our NVDA consensus?", ())
        # The second turn's first model is rate limited, so a fallback answers it.
        agent.model = FallbackModel(
            FunctionModel(rate_limited, model_name="model-x"),
            FunctionModel(llm.respond, model_name="model-b"),
        )
        second = agent.chat(
            "In this meeting we discussed AI Data Center Power Bottleneck. Related companies?",
            first.history,
        )

    # The result shape is pinned: exactly these fields, frozen.
    assert type(first).__name__ == "ChatTurn"
    assert dataclasses.is_dataclass(first)
    assert [f.name for f in dataclasses.fields(first)] == [
        "reply",
        "history",
        "tools_used",
        "provider",
        "model",
        "fallback_used",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.reply = "changed"  # type: ignore[misc]

    assert "Keep (BULLISH)" in first.reply
    assert "Affected companies" in second.reply

    # History is an opaque tuple handed back unchanged; it grows across turns.
    assert isinstance(first.history, tuple) and isinstance(second.history, tuple)
    assert len(first.history) > 0
    assert second.history[: len(first.history)] == first.history
    assert len(second.history) > len(first.history)

    # Tools are only this turn's, even on a reused agent.
    assert first.tools_used == ("get_entity_overview",)
    assert second.tools_used == ("find_theme_companies",)

    # Provider fields come from the turn's final model call.
    assert (first.provider, first.model, first.fallback_used) == ("prov-2", "model-a", False)
    assert (second.provider, second.model, second.fallback_used) == ("prov-4", "model-b", True)


def test_prompt_and_tool_schema_vocab_lists_come_from_vocab() -> None:
    from stock_ontology.agent import TOOL_SCHEMAS
    from stock_ontology.llm.prompts import EXTRACTION_SYSTEM_PROMPT
    from stock_ontology.vocab import (
        CONVICTION,
        ENTITY_TYPE,
        EVENT_STATUS,
        EVENT_TYPE,
        EXTRACTED_VIEW_TYPES,
        SENTIMENT_FILTER_VALUES,
        SIGNAL_CATEGORIES,
        STANCE,
        SUPPORT_STRENGTH,
        format_choices,
    )

    assert f"`stance` ({format_choices(STANCE.members, sep='|')})" in EXTRACTION_SYSTEM_PROMPT
    assert f"`view_type`: {format_choices(EXTRACTED_VIEW_TYPES)}." in EXTRACTION_SYSTEM_PROMPT
    assert f"`event_type`: {format_choices(EVENT_TYPE.members)}." in EXTRACTION_SYSTEM_PROMPT
    assert f"`status`: {format_choices(EVENT_STATUS.members)}." in EXTRACTION_SYSTEM_PROMPT
    assert format_choices(ENTITY_TYPE.members, sep=", ") in EXTRACTION_SYSTEM_PROMPT
    assert format_choices(SUPPORT_STRENGTH.members, sep="|") in EXTRACTION_SYSTEM_PROMPT
    assert format_choices(CONVICTION.members, sep="|") in EXTRACTION_SYSTEM_PROMPT
    assert "`consensus`" not in format_choices(EXTRACTED_VIEW_TYPES)

    signals = next(t for t in TOOL_SCHEMAS if t["name"] == "query_entity_signals")
    props = signals["parameters"]["properties"]
    assert props["sentiments"]["items"]["enum"] == list(SENTIMENT_FILTER_VALUES)
    assert all(cat in props["categories"]["description"] for cat in SIGNAL_CATEGORIES)
    assert all(st in props["statuses"]["description"] for st in EVENT_STATUS.members)


# --- Generic ontology search (ledger: docs/proposals/ontology-search.md) ---


class AppleNearestSearchLLM(RecordingAgentLLM):
    """Every query embeds nearest to the Apple consensus view, never to NVIDIA."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vec(9) for _ in texts]


def _seed_search_db(db_path: Path) -> None:
    _seed_db(db_path)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple Inc.",
            summary="Consumer devices and services.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        db.upsert_node(aapl, embedding=_unit_vec(8))
        cons = Node(
            id="vw_cons_aapl",
            node_type="view",
            name="Consensus: Buy Apple Inc.",
            summary="Maintain Buy on services growth.",
            facets={"stance": "buy", "view_type": "analyst_report"},
        )
        db.upsert_consensus_view("ent_aapl", cons, _unit_vec(9), supporting_ids=[], contradicting_ids=[])


def _tool_response(llm: RecordingAgentLLM) -> dict[str, Any]:
    """The tool result the agent handed back to the model on the second request."""
    part = _last_part(llm.requests[1]["messages"])
    assert isinstance(part, ToolReturnPart)
    return part.content


def test_agent_search_nodes_returns_entity_first_with_match_reasons(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_search_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        llm = AppleNearestSearchLLM(
            [
                _call("search_nodes", {"query": "nvidia"}),
                _text("done"),
            ]
        )
        turn = OntologyAgent(ro_db, llm, model=llm.model).chat("nvidia", ())

    assert turn.tools_used == ("search_nodes",)
    results = _tool_response(llm)["results"]
    ids = [r["id"] for r in results]
    assert ids[0] == "ent_nvda", f"search_nodes did not put the name match first: {ids}"
    assert results[0]["match_reason"] == "name"
    apple = next(r for r in results if r["id"] == "vw_cons_aapl")
    assert apple["match_reason"] == "semantic"


def test_agent_search_notes_greps_only_supported_notes_inside_data_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_search_db(db_path)
    data_dir = tmp_path / "data"
    (data_dir / "Notes").mkdir(parents=True)
    (data_dir / "Notes" / "2026-11-10_channel_check.md").write_text(
        "# Channel check\n\nChannel check: NVIDIA lead times shortened.\n", encoding="utf-8"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("NVIDIA OUTSIDE-MARKER-1\n", encoding="utf-8")
    (data_dir / "linked.md").symlink_to(outside / "secret.md")
    (data_dir / ".dotnote.md").write_text("NVIDIA HIDDEN-FILE-MARKER-3\n", encoding="utf-8")
    (data_dir / "Notes" / "deck.pdf").write_text("NVIDIA UNSUPPORTED-MARKER-4\n", encoding="utf-8")

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        llm = AppleNearestSearchLLM(
            [
                _call("search_notes", {"query": "nvidia"}),
                _text("done"),
            ]
        )
        try:
            agent = OntologyAgent(ro_db, llm, model=llm.model, data_dir=data_dir)
        except TypeError as exc:
            pytest.fail(f"OntologyAgent does not accept data_dir for note search: {exc}")
        turn = agent.chat("nvidia", ())
        assert ro_db.get_stats() == before_stats

    assert "search_notes" in [schema["name"] for schema in llm.requests[0]["tool_schemas"]]
    assert turn.tools_used == ("search_notes",)
    passages = _tool_response(llm)["passages"]
    assert {"file": "Notes/2026-11-10_channel_check.md", "line": 3} in [
        {"file": p["file"], "line": p["line"]} for p in passages
    ]
    assert any("NVIDIA lead times shortened." in p["text"] for p in passages)
    dumped = json.dumps(passages)
    for marker in ("OUTSIDE-MARKER-1", "HIDDEN-FILE-MARKER-3", "UNSUPPORTED-MARKER-4"):
        assert marker not in dumped


class _NoChatLLM:
    """`LLMClient` for tool embeddings only; records any chat call so a test can assert there was none."""

    def __init__(self) -> None:
        self.chat_calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vec(15) for _ in texts]

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    def generate_agent_reply(self, **kwargs: Any) -> Any:
        self.chat_calls += 1
        raise AssertionError("the agent must answer through its Pydantic AI model, not LLMClient")


def test_agent_answers_through_native_model_with_model_settings(tmp_path: Path) -> None:
    from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from stock_ontology.agent import build_agent_system_prompt

    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    seen: list[AgentInfo] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info)
        returns = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("list_catalog", {})], provider_name="gemini")
        return ModelResponse(parts=[TextPart("Catalog has " + ", ".join(sorted(e["name"] for e in returns[-1].content["entities"])))], provider_name="gemini")

    llm = _NoChatLLM()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        agent = OntologyAgent(
            ro_db,
            llm,
            model=FunctionModel(respond, model_name="gemini-test"),
            model_settings={"max_tokens": 123},
        )
        turn = agent.chat("What is in the catalog?", ())

    # Every model request (tool round and final answer) carries the agent's model settings.
    assert len(seen) == 2
    assert all((info.model_settings or {}).get("max_tokens") == 123 for info in seen)
    # The system prompt reaches the native model as Pydantic AI instructions.
    assert all(info.instructions == build_agent_system_prompt() for info in seen)
    # Tools still run and the answer comes from the native model; LLMClient made no chat call.
    assert turn.tools_used == ("list_catalog",)
    assert turn.reply == "Catalog has NVIDIA, TSMC, Vertiv"
    assert (turn.provider, turn.model, turn.fallback_used) == ("gemini", "gemini-test", False)
    assert llm.chat_calls == 0


def test_agent_falls_back_to_next_native_model_and_stamps_answering_provider(tmp_path: Path) -> None:
    from pydantic_ai.exceptions import ModelHTTPError
    from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
    from pydantic_ai.models.fallback import FallbackModel
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    calls: list[str] = []

    def rate_limited(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("gemini")
        raise ModelHTTPError(429, "gemini-test", {"error": "quota"})

    def answers(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("dashscope")
        return ModelResponse(parts=[TextPart("Answered by the fallback.")], provider_name="dashscope")

    llm = _NoChatLLM()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        agent = OntologyAgent(
            ro_db,
            llm,
            model=FallbackModel(
                FunctionModel(rate_limited, model_name="gemini-test"),
                FunctionModel(answers, model_name="qwen-test"),
            ),
        )
        turn = agent.chat("Anything new on NVDA?", ())

    assert calls == ["gemini", "dashscope"]
    assert turn.reply == "Answered by the fallback."
    assert (turn.provider, turn.model, turn.fallback_used) == ("dashscope", "qwen-test", True)
    assert llm.chat_calls == 0
