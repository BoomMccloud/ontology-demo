"""Offline tests for the strictly read-only PM query agent (UX #1 and UX #2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stock_ontology.agent import OntologyAgent
from stock_ontology.db import OntologyDB
from stock_ontology.llm import AgentTurn, ToolCall
from stock_ontology.models import ConsensusSynthesis, Edge, ExtractionResult, Node

DIM = 16


def _unit_vec(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[idx % DIM] = 1.0
    return v


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
            Edge(id="ed1", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_nvda_q3")
        )
        db.upsert_edge(
            Edge(id="ed2", from_id="ent_vrt", to_id="thm_power", relation="BENEFITS_FROM")
        )
        db.upsert_edge(
            Edge(id="ed3", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO")
        )
        db.upsert_edge(
            Edge(id="ed4", from_id="ent_tsmc", to_id="ent_nvda", relation="SUPPLIES_TO")
        )
        db.upsert_consensus_view(
            "ent_nvda",
            cons_nvda,
            _unit_vec(6),
            supporting_ids=["evt_q3"],
            contradicting_ids=[],
        )


class ScriptedAgentLLM:
    """Offline mock driving tool calls and inspecting real tool responses."""

    def __init__(self, loop_forever: bool = False) -> None:
        self.loop_forever = loop_forever

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

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        if self.loop_forever:
            return AgentTurn(tool_calls=[ToolCall(name="list_catalog", args={})])

        last_msg = messages[-1]
        if last_msg["role"] == "user":
            text = last_msg["text"].lower()
            if "theme" in text or "power bottleneck" in text:
                return AgentTurn(
                    tool_calls=[
                        ToolCall(
                            name="find_theme_companies",
                            args={
                                "theme_query": "AI Data Center Power Bottleneck",
                                "include_second_order": True,
                            },
                        )
                    ]
                )
            if "consensus" in text or "meeting" in text:
                return AgentTurn(
                    tool_calls=[
                        ToolCall(
                            name="get_entity_overview",
                            args={"entity_name_or_id": "NVDA"},
                        )
                    ]
                )
            if "how many" in text and "negative" in text:
                return AgentTurn(
                    tool_calls=[
                        ToolCall(
                            name="query_entity_signals",
                            args={
                                "entity_name_or_id": "NVDA",
                                "sentiments": ["negative"],
                                "categories": ["rumor", "news"],
                            },
                        )
                    ]
                )
            return AgentTurn(tool_calls=[ToolCall(name="list_catalog", args={})])

        if last_msg["role"] == "tool":
            resp = last_msg["responses"][0]
            tool_name = resp["name"]
            payload = resp["response"]
            if tool_name == "get_entity_overview":
                cons = payload["consensus"]
                pillars = cons["facets"]["pillars"]
                src = payload["events"][0]["facets"]["source"]["file_path"]
                return AgentTurn(
                    text=(
                        f"Verdict: Keep ({cons['facets']['stance'].upper()}). "
                        f"Checked pillars: {json.dumps(pillars)}. "
                        f"Source: {src}. Read-only mode: save note to data/NVDA/ and run ingest to update DB."
                    )
                )
            if tool_name == "query_entity_signals":
                total = payload["total_matched"]
                unclassified = payload["unclassified_in_scope"]
                names = ", ".join(it["name"] for it in payload["items"])
                return AgentTurn(
                    text=(
                        f"Found {total} negative rumor/news items for {payload['entity']['name']}: "
                        f"{names}. Unclassified legacy items in scope: {unclassified}."
                    )
                )
            if tool_name == "find_theme_companies":
                first = [c["company"]["name"] for c in payload["first_order"]]
                second = [c["company"]["name"] for c in payload["second_order"]]
                return AgentTurn(
                    text=(
                        f"1st-order companies: {', '.join(sorted(first))}. "
                        f"2nd-order companies: {', '.join(sorted(second))}."
                    )
                )
            return AgentTurn(text=json.dumps(payload))

        return AgentTurn(text="No action.")


def test_agent_requires_read_only_db(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as writable_db:
        with pytest.raises(ValueError, match="read-only"):
            OntologyAgent(writable_db, ScriptedAgentLLM())


def test_agent_ux1_meeting_note_consensus_check(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        agent = OntologyAgent(ro_db, ScriptedAgentLLM())
        reply = agent.ask(
            "I just had a meeting with a supply engineer confirming Blackwell yields are fine "
            "and only small colos face transformer delays. Does this change our NVDA consensus?"
        )

        assert "Keep (BUY)" in reply
        assert "NVDA/2026-10-15_q3_preview.md" in reply
        assert "read-only" in reply.lower()
        assert agent.tool_trace[0]["tool"] == "get_entity_overview"
        # Strict one-way guarantee: DB stats and consensus node remain untouched.
        assert ro_db.get_stats() == before_stats


def test_agent_ux2_theme_related_companies(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        agent = OntologyAgent(ro_db, ScriptedAgentLLM())
        reply = agent.ask(
            "In this meeting we discussed AI Data Center Power Bottleneck. What are the related companies?"
        )

        assert "NVIDIA" in reply and "Vertiv" in reply
        assert "TSMC" in reply
        assert agent.tool_trace[0]["tool"] == "find_theme_companies"


def test_agent_tool_error_and_max_rounds_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        agent = OntologyAgent(ro_db, ScriptedAgentLLM(loop_forever=True))
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
            Edge(id="es1", from_id="evt_sec", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s1")
        )
        db.upsert_edge(
            Edge(id="es2", from_id="vw_delay", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s2")
        )
        db.upsert_edge(
            Edge(
                id="es3_nvda",
                from_id="evt_dual",
                to_id="ent_nvda",
                relation="ABOUT",
                facets={"sentiment": "negative"},
                source_doc_id="doc_s3",
            )
        )
        db.upsert_edge(
            Edge(
                id="es3_aapl",
                from_id="evt_dual",
                to_id="ent_aapl",
                relation="ABOUT",
                facets={"sentiment": "positive"},
                source_doc_id="doc_s3",
            )
        )
        db.upsert_edge(
            Edge(id="es4", from_id="evt_win", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s4")
        )
        db.upsert_edge(
            Edge(id="es5", from_id="evt_old", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_s5")
        )

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        agent = OntologyAgent(ro_db, ScriptedAgentLLM())
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
