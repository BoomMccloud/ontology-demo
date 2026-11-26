"""Offline unit tests for SQLite + sqlite-vec storage, read-only enforcement, and graph queries."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
import sqlite_vec

from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, ExtractedEdge, ExtractedEntity, ExtractionResult, Node
from stock_ontology.pipeline import IngestionPipeline
from stock_ontology.registry import create_minimal_registry, save_registry


def insert_legacy_edge(db: OntologyDB, edge: Edge) -> None:
    """Store `edge` by raw SQL, as rows with an unmapped relation were written before `upsert_edge` refused them."""
    import json

    db.conn.execute(
        "INSERT INTO edges (id, from_id, to_id, relation, facets_json, source_doc_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (edge.id, edge.from_id, edge.to_id, edge.relation, json.dumps(edge.facets), edge.source_doc_id, edge.created_at.isoformat()),
    )
    db.conn.commit()


def seed_edge(db: OntologyDB, edge: Edge) -> None:
    """Write `edge` normally, or as a legacy row when the registry would now refuse its relation or endpoints."""
    from stock_ontology.registry import FacetSchemaError

    try:
        db.upsert_edge(edge)
    except FacetSchemaError:
        insert_legacy_edge(db, edge)


def _unit_vec(index: int, dim: int = 8) -> list[float]:
    vec = [0.0] * dim
    vec[index % dim] = 1.0
    return vec


def test_sqlite_vec_search_and_node_type_filter() -> None:
    with OntologyDB(":memory:", embedding_dim=8) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU leader",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        vrt = Node(
            id="ent_vrt",
            node_type="entity",
            name="Vertiv",
            summary="Liquid cooling infrastructure",
            aliases=["VRT"],
            facets={"entity_type": "company", "ticker": "VRT"},
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Power Bottleneck",
            summary="Data center power and thermal constraints",
            facets={"stage": "accelerating"},
        )

        db.upsert_node(nvda, embedding=_unit_vec(0))
        db.upsert_node(vrt, embedding=_unit_vec(1))
        db.upsert_node(theme, embedding=_unit_vec(1))

        # Update vector for vrt to confirm clean delete+insert replacement.
        db.upsert_node(vrt, embedding=[0.2, 0.98, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        all_hits = db.vector_search(_unit_vec(0), limit=3)
        assert all_hits[0][0].id == "ent_nvda"
        assert all_hits[0][1] == pytest.approx(0.0, abs=1e-5)

        theme_hits = db.vector_search(_unit_vec(1), node_type="theme", limit=2)
        assert len(theme_hits) == 1
        assert theme_hits[0][0].id == "thm_power"


def test_read_only_enforces_pragma_query_only(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ro.db"
    with OntologyDB(db_file, embedding_dim=8, read_only=False) as writer:
        writer.upsert_node(
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="GPU leader",
                facets={"entity_type": "company"},
            ),
            embedding=_unit_vec(0),
        )

    with OntologyDB(db_file, embedding_dim=8, read_only=True) as reader:
        assert reader.get_node("ent_nvda") is not None
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.upsert_node(
                Node(
                    id="ent_illegal",
                    node_type="entity",
                    name="Illegal",
                    summary="Should fail", facets={"entity_type": "company"},
                )
            )
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.conn.execute("DELETE FROM nodes WHERE id = 'ent_nvda'")


def test_delete_document_artifacts_preserves_canonical_nodes() -> None:
    with OntologyDB(":memory:", embedding_dim=8) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="GPU leader",
            facets={"entity_type": "company"},
        )
        theme = Node(
            id="thm_ai",
            node_type="theme",
            name="AI Capex",
            summary="Hyperscaler AI spend", facets={"stage": "accelerating"},
        )
        ev_doc1 = Node(
            id="evt_1",
            node_type="event",
            name="Q3 Beat",
            summary="Strong Q3",
            facets={"event_type": "earnings"},
            source_doc_id="doc_1",
        )
        vw_doc1 = Node(
            id="vw_1",
            node_type="view",
            name="Bullish Note",
            summary="Buy NVDA",
            facets={"view_type": "analyst_report"},
            source_doc_id="doc_1",
        )
        ev_doc2 = Node(
            id="evt_2",
            node_type="event",
            name="Supply Check",
            summary="CoWoS tight",
            facets={"event_type": "fact"},
            source_doc_id="doc_2",
        )

        for idx, n in enumerate([nvda, theme, ev_doc1, vw_doc1, ev_doc2]):
            db.upsert_node(n, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(id="e1", from_id="evt_1", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="e2", from_id="vw_1", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="e3", from_id="evt_1", to_id="thm_ai", relation="RELATES_TO", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="e4", from_id="evt_2", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_2", facets={"basis": "extracted"})
        )

        assert db.get_doc_affected_company_ids("doc_1") == {"ent_nvda"}

        db.delete_document_artifacts("doc_1")

        # Canonical nodes and doc_2 artifacts survive; doc_1 nodes/edges/vectors are gone.
        assert db.get_node("ent_nvda") is not None
        assert db.get_node("thm_ai") is not None
        assert db.get_node("evt_2") is not None
        assert db.get_node("evt_1") is None
        assert db.get_node("vw_1") is None
        vec_ids = {
            r["node_id"]
            for r in db.conn.execute("SELECT node_id FROM node_vectors").fetchall()
        }
        assert vec_ids == {"ent_nvda", "thm_ai", "evt_2"}
        assert len(db.get_incident_edges("ent_nvda")) == 1


def test_consensus_supersession_and_theme_and_bfs_traversal() -> None:
    with OntologyDB(":memory:", embedding_dim=8) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPUs",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        vrt = Node(
            id="ent_vrt",
            node_type="entity",
            name="Vertiv",
            summary="Liquid cooling",
            aliases=["VRT"],
            facets={"entity_type": "company", "ticker": "VRT"},
        )
        tsmc = Node(
            id="ent_tsmc",
            node_type="entity",
            name="TSMC",
            summary="Foundry and CoWoS packaging",
            aliases=["TSM"],
            facets={"entity_type": "company", "ticker": "TSM"},
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Power Bottleneck",
            summary="Rack power and cooling constraints",
            facets={"stage": "accelerating"},
        )
        ev = Node(
            id="evt_call",
            node_type="event",
            name="Thermal Call",
            summary="120kW racks need liquid cooling",
            facets={"event_type": "meeting", "source": {"file_path": "NVDA/call.md"}},
            source_doc_id="doc_call",
        )

        for idx, n in enumerate([nvda, vrt, tsmc, theme, ev]):
            db.upsert_node(n, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(id="ed1", from_id="ent_vrt", to_id="thm_power", relation="BENEFITS_FROM", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed2", from_id="evt_call", to_id="thm_power", relation="RELATES_TO", source_doc_id="doc_call", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed3", from_id="evt_call", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_call", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed4", from_id="ent_tsmc", to_id="ent_nvda", relation="SUPPLIES_TO", facets={"basis": "extracted"})
        )

        c1 = Node(
            id="vw_cons_1",
            node_type="view",
            name="Consensus: Hold NVIDIA",
            summary="Wait on mask respin",
            facets={"stance": "hold", "pillars": ["Blackwell yield stabilizes"], "view_type": "analyst_report"},
        )
        db.upsert_consensus_view("ent_nvda", c1, _unit_vec(6), supporting_ids=["evt_call"], contradicting_ids=[])
        assert db.get_entity_consensus("ent_nvda").id == "vw_cons_1"

        c2 = Node(
            id="vw_cons_2",
            node_type="view",
            name="Consensus: Buy NVIDIA",
            summary="Blackwell ramping cleanly",
            facets={"stance": "buy", "pillars": ["Hyperscaler capex >25%"], "view_type": "analyst_report"},
        )
        db.upsert_consensus_view("ent_nvda", c2, _unit_vec(7), supporting_ids=["evt_call"], contradicting_ids=[])

        active = db.get_entity_consensus("ent_nvda")
        assert active is not None
        assert active.id == "vw_cons_2"
        old = db.get_node("vw_cons_1")
        assert old is not None and old.facets["status"] == "superseded"

        theme_res = db.find_theme_companies("thm_power")
        company_ids = {item["company"]["id"] for item in theme_res["companies"]}
        assert company_ids == {"ent_vrt", "ent_nvda"}

        bfs = db.traverse_bfs("thm_power", max_hops=2)
        bfs_hops = {n["id"]: n["hop"] for n in bfs["nodes"]}
        assert bfs_hops["thm_power"] == 0
        assert bfs_hops["ent_vrt"] == 1
        assert bfs_hops["evt_call"] == 1
        assert bfs_hops["ent_nvda"] == 2


def test_query_entity_signals_sentiment_categories_and_edge_overrides() -> None:
    with OntologyDB(":memory:", embedding_dim=8) as db:
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Consumer devices and silicon",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        qcom = Node(
            id="ent_qcom",
            node_type="entity",
            name="Qualcomm",
            summary="Modem and mobile SoC supplier",
            aliases=["QCOM"],
            facets={"entity_type": "company", "ticker": "QCOM"},
        )
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU leader",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )

        # Multi-company news event: positive for AAPL, negative for QCOM, mixed for NVDA.
        evt_modem = Node(
            id="evt_modem",
            node_type="event",
            name="In-House Modem Ramp",
            summary="Apple accelerates C2 modem transition.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-18",
                "status": "occurred",
                "sentiment": "mixed",
            },
            source_doc_id="doc_1",
        )
        # Event that is BOTH event_type=news and status=rumored, with two edges to QCOM.
        evt_rumored_news = Node(
            id="evt_rumored_news",
            node_type="event",
            name="Baseband Order Cut Rumor",
            summary="Supply chain reports steeper Q2 modem cut.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-15",
                "status": "rumored",
                "sentiment": "negative",
            },
            source_doc_id="doc_1",
        )
        # Rumor view.
        vw_rumor = Node(
            id="vw_rumor",
            node_type="view",
            name="Channel Rumor: Modem Share Loss",
            summary="Rumor suggests faster share loss than guided.",
            facets={
                "view_type": "rumor",
                "stance": "bearish",
                "sentiment": "negative",
                "as_of": "2026-11-16",
            },
            source_doc_id="doc_1",
        )
        # Legacy view without explicit sentiment (derives negative from cautious stance).
        vw_legacy_cautious = Node(
            id="vw_legacy_cautious",
            node_type="view",
            name="Legacy Cautious Note",
            summary="Cautious on handset demand.",
            facets={
                "view_type": "analyst_report",
                "stance": "cautious",
                "as_of": "2026-10-01",
            },
            source_doc_id="doc_legacy",
        )
        # Legacy event without sentiment (counted in unclassified_in_scope).
        evt_legacy_news = Node(
            id="evt_legacy_news",
            node_type="event",
            name="Legacy News Item",
            summary="Earlier unannotated press release.",
            facets={
                "event_type": "news",
                "event_date": "2026-09-01",
                "status": "occurred",
            },
            source_doc_id="doc_legacy",
        )
        # Authored event (excluded by default).
        evt_authored = Node(
            id="evt_authored",
            node_type="event",
            name="QCOM Authored Release",
            summary="Press release authored by QCOM.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-19",
                "status": "occurred",
                "sentiment": "positive",
            },
            source_doc_id="doc_1",
        )
        # Consensus view (excluded by default).
        vw_cons_qcom = Node(
            id="vw_cons_qcom",
            node_type="view",
            name="Consensus: Hold Qualcomm",
            summary="Balanced risk/reward.",
            facets={
                "view_type": "consensus",
                "stance": "hold",
                "sentiment": "neutral",
                "status": "active",
                "as_of": "2026-11-20",
            },
        )

        for idx, n in enumerate(
            [
                aapl,
                qcom,
                nvda,
                evt_modem,
                evt_rumored_news,
                vw_rumor,
                vw_legacy_cautious,
                evt_legacy_news,
                evt_authored,
            ]
        ):
            db.upsert_node(n, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(
                id="ed_aapl",
                from_id="evt_modem",
                to_id="ent_aapl",
                relation="ABOUT",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_qcom",
                from_id="evt_modem",
                to_id="ent_qcom",
                relation="ABOUT",
                facets={"sentiment": "negative", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_nvda",
                from_id="evt_modem",
                to_id="ent_nvda",
                relation="ABOUT",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )
        # Two edges from evt_rumored_news to ent_qcom to verify deduplication.
        insert_legacy_edge(
            db,
            Edge(
                id="ed_rn_rel",
                from_id="evt_rumored_news",
                to_id="ent_qcom",
                relation="RELATES_TO",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            ),
        )
        db.upsert_edge(
            Edge(
                id="ed_rn_about",
                from_id="evt_rumored_news",
                to_id="ent_qcom",
                relation="ABOUT",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )
        db.upsert_edge(
            Edge(id="ed_vrumor", from_id="vw_rumor", to_id="ent_qcom", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(
                id="ed_vleg",
                from_id="vw_legacy_cautious",
                to_id="ent_qcom",
                relation="ABOUT",
                source_doc_id="doc_legacy", facets={"basis": "extracted"},
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_eleg",
                from_id="evt_legacy_news",
                to_id="ent_qcom",
                relation="ABOUT",
                source_doc_id="doc_legacy", facets={"basis": "extracted"},
            )
        )
        seed_edge(
            db,
            Edge(
                id="ed_auth",
                from_id="evt_authored",
                to_id="ent_qcom",
                relation="AUTHORED_BY",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )
        db.upsert_consensus_view("ent_qcom", vw_cons_qcom, _unit_vec(7), [], [])

        # Apple receives edge-level positive override.
        aapl_pos = db.query_entity_signals("ent_aapl", sentiments=["positive"])
        assert aapl_pos["total_matched"] == 1
        assert aapl_pos["items"][0]["id"] == "evt_modem"
        assert aapl_pos["items"][0]["effective_sentiment"] == "positive"
        assert aapl_pos["items"][0]["sentiment_source"] == "edge"

        # NVIDIA has no edge override, so it inherits node-level mixed.
        nvda_mixed = db.query_entity_signals("ent_nvda", sentiments=["mixed"])
        assert nvda_mixed["total_matched"] == 1
        assert nvda_mixed["items"][0]["sentiment_source"] == "node"

        # Qualcomm: negative rumors or news (plural aliases, no double counting).
        qcom_neg = db.query_entity_signals(
            "ent_qcom",
            sentiments=["negative"],
            categories=["rumors", "news"],
        )
        assert qcom_neg["total_matched"] == 3
        assert [it["id"] for it in qcom_neg["items"]] == [
            "evt_modem",
            "vw_rumor",
            "evt_rumored_news",
        ]
        assert qcom_neg["counts_by_sentiment"]["negative"] == 3
        assert qcom_neg["counts_by_node_type"] == {"event": 2, "view": 1}
        assert qcom_neg["rumored_event_count"] == 1
        assert qcom_neg["unclassified_in_scope"] == 1
        # Deduplication picked the ABOUT edge for evt_rumored_news.
        rn_item = next(it for it in qcom_neg["items"] if it["id"] == "evt_rumored_news")
        assert rn_item["relation"] == "ABOUT"

        # All categories with negative sentiment includes legacy cautious view via stance fallback.
        qcom_all_neg = db.query_entity_signals("ent_qcom", sentiments=["negative"])
        assert qcom_all_neg["total_matched"] == 4
        legacy_vw = next(it for it in qcom_all_neg["items"] if it["id"] == "vw_legacy_cautious")
        assert legacy_vw["sentiment_source"] == "stance"

        # Date range filter.
        qcom_window = db.query_entity_signals(
            "ent_qcom",
            sentiments=["negative"],
            date_from="2026-11-01",
            date_to="2026-11-17",
        )
        assert [it["id"] for it in qcom_window["items"]] == ["vw_rumor", "evt_rumored_news"]

        # Optional inclusion of authored events & consensus views.
        qcom_with_extra = db.query_entity_signals(
            "ent_qcom",
            include_authored=True,
            include_consensus=True,
        )
        extra_ids = {it["id"] for it in qcom_with_extra["items"]}
        assert "evt_authored" in extra_ids
        assert "vw_cons_qcom" in extra_ids

        # get_entity_overview attaches effective_sentiment and sentiment_summary.
        ov = db.get_entity_overview("ent_qcom")
        assert ov["sentiment_summary"]["counts_by_sentiment"]["negative"] == 4
        assert ov["sentiment_summary"]["unclassified_in_scope"] == 1
        ov_modem = next(ev for ev in ov["events"] if ev["id"] == "evt_modem")
        assert ov_modem["effective_sentiment"] == "negative"
        assert ov_modem["sentiment_source"] == "edge"


def test_replace_node_embeddings_and_metadata(tmp_path: Path) -> None:
    db_file = tmp_path / "reembed_test.db"
    with OntologyDB(db_file, embedding_dim=8, read_only=False) as db:
        n1 = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU leader",
            facets={"entity_type": "company"},
        )
        n2 = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Edge AI consumer hardware leader",
            facets={"entity_type": "company"},
        )
        db.upsert_node(n1, embedding=_unit_vec(0))
        db.upsert_node(n2, embedding=_unit_vec(1))
        assert len(db.list_all_nodes()) == 2

        # Inject an orphan vector row directly into node_vectors.
        with db.conn:
            db.conn.execute(
                "INSERT INTO node_vectors(node_id, embedding) VALUES (?, ?)",
                ("ent_orphan", sqlite_vec.serialize_float32(_unit_vec(2))),
            )

        # Wrong embedding dimension must fail before modifying existing vectors.
        with pytest.raises(ValueError, match="dimension mismatch"):
            db.replace_node_embeddings({"ent_nvda": [1.0, 0.0], "ent_aapl": _unit_vec(3)})
        assert db.vector_search(_unit_vec(0), limit=1)[0][0].id == "ent_nvda"

        replaced = db.replace_node_embeddings(
            {"ent_nvda": _unit_vec(4), "ent_aapl": _unit_vec(5)},
            prune_orphans=True,
        )
        assert replaced == 2
        stored = db.get_node_embeddings()
        assert set(stored.keys()) == {"ent_nvda", "ent_aapl"}
        assert "ent_orphan" not in stored
        assert db.vector_search(_unit_vec(4), limit=1)[0][0].id == "ent_nvda"

        db.set_metadata("embedding_provider", "gemini")
        db.set_metadata("embedding_model", "gemini-embedding-2")
        db.set_metadata("embedding_model", "gemini-embedding-2-updated")
        assert db.get_metadata("embedding_provider") == "gemini"
        assert db.get_metadata("embedding_model") == "gemini-embedding-2-updated"
        assert db.get_metadata("missing_key") is None
        assert db.get_all_metadata() == {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-updated",
        }

    with OntologyDB(db_file, embedding_dim=8, read_only=True) as reader:
        assert reader.get_metadata("embedding_provider") == "gemini"
        assert reader.get_all_metadata()["embedding_model"] == "gemini-embedding-2-updated"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.set_metadata("embedding_provider", "dashscope")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.replace_node_embeddings({"ent_nvda": _unit_vec(0)})

    # Legacy DB without db_metadata table gracefully returns None / {}.
    legacy_file = tmp_path / "legacy.db"
    with OntologyDB(legacy_file, embedding_dim=8, read_only=False) as db:
        with db.conn:
            db.conn.execute("DROP TABLE db_metadata")
    with OntologyDB(legacy_file, embedding_dim=8, read_only=True) as legacy_reader:
        assert legacy_reader.get_metadata("embedding_provider") is None
        assert legacy_reader.get_all_metadata() == {}


def test_transaction_rolls_back_every_nested_write_and_commits_once(tmp_path: Path) -> None:
    db_path = tmp_path / "tx.db"
    vec = [1.0, 0.0, 0.0, 0.0]
    a = Node(id="n_a", node_type="entity", name="Alpha", summary="a", facets={"entity_type": "company"})
    b = Node(id="n_b", node_type="entity", name="Beta", summary="b", facets={"entity_type": "company"})
    edge = Edge(id="e_ab", from_id="n_a", to_id="n_b", relation="COMPETES_WITH", facets={"basis": "extracted"})

    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.upsert_node(a, embedding=vec)
                with db.transaction():
                    db.upsert_node(b, embedding=vec)
                    db.upsert_edge(edge)
                raise RuntimeError("fail after inner scope exits")  # noqa: TRY003
        assert db.get_node("n_a") is None
        assert db.get_node("n_b") is None
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM node_vectors").fetchone()[0] == 0

        with db.transaction():
            db.upsert_node(a, embedding=vec)
            db.upsert_node(b, embedding=vec)
            db.upsert_edge(edge)

    with OntologyDB(db_path, embedding_dim=4, read_only=True) as ro:
        assert ro.get_node("n_a") is not None
        assert ro.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 1


def test_find_by_name_or_alias_matches_casefold_name_and_alias_by_type(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "lookup.db", embedding_dim=4, read_only=False) as db:
        db.upsert_node(
            Node(id="ent_x", node_type="entity", name="Straße Corp", summary="x", aliases=[" SCX "], facets={"entity_type": "company"})
        )
        db.upsert_node(Node(id="thm_x", node_type="theme", name="SCX", summary="theme", facets={"stage": "accelerating"}))
        # casefold (not SQL lower) so "STRASSE" matches "Straße".
        assert db.find_by_name_or_alias("STRASSE CORP").id == "ent_x"
        assert db.find_by_name_or_alias("scx", node_type="entity").id == "ent_x"
        assert db.find_by_name_or_alias("scx", node_type="theme").id == "thm_x"
        assert db.find_by_name_or_alias("missing") is None
        assert db.find_by_name_or_alias("   ") is None


# ---------------------------------------------------------------------------
# Ingestion write-integrity wiring (prompt relations, repair CLI, ingest registry)
# ---------------------------------------------------------------------------

WIRING_DIM = 8


def _wiring_vec(idx: int) -> list[float]:
    v = [0.0] * WIRING_DIM
    v[idx % WIRING_DIM] = 1.0
    return v


class _CatalogCaptureFakeLLM:
    def __init__(self) -> None:
        self.catalogs: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_wiring_vec(len(t)) for t in texts]

    def extract_document(self, *, existing_catalog: str, **_: Any) -> ExtractionResult:
        self.catalogs.append(existing_catalog)
        return ExtractionResult()


def test_extraction_catalog_lists_registry_relation_names(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "note.md").write_text("Any note.", encoding="utf-8")
    llm = _CatalogCaptureFakeLLM()

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=WIRING_DIM, read_only=False) as db:
        IngestionPipeline(db, llm, data_dir).run()

    assert len(llm.catalogs) == 1
    assert "Canonical edge relations" in llm.catalogs[0]
    for name in ("ABOUT", "BUY", "COMPETE", "OWNS", "WORKS_AT", "EXPOSED_TO"):
        assert name in llm.catalogs[0]


def test_cli_repair_reports_changes_then_zero_on_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from typer.testing import CliRunner

    from stock_ontology.cli import app

    monkeypatch.setenv("EMBEDDING_DIM", str(WIRING_DIM))
    db_path = tmp_path / "ontology.db"
    reg_path = tmp_path / "ontology_registry.json"
    with OntologyDB(db_path, embedding_dim=WIRING_DIM, read_only=False) as db:
        db.upsert_node(
            Node(id="ent_a", node_type="entity", name="Acme", summary="a", facets={"entity_type": "company"}),
            embedding=_wiring_vec(0),
        )
        db.upsert_node(
            Node(id="ent_b", node_type="entity", name="Beta", summary="b", facets={"entity_type": "company"}),
            embedding=_wiring_vec(1),
        )
        db.upsert_node(
            Node(id="evt_orphan", node_type="event", name="Orphan", summary="o", source_doc_id="doc_gone", facets={"event_type": "fact"}),
            embedding=_wiring_vec(2),
        )
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETES_WITH", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e2", from_id="evt_orphan", to_id="ent_a", relation="ABOUT", source_doc_id="doc_gone", facets={"basis": "extracted"}))
    save_registry(create_minimal_registry(), reg_path)
    args = ["repair", "--db", str(db_path), "--registry", str(reg_path), "--json"]

    runner = CliRunner()
    first = runner.invoke(app, args, input="y\n")
    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)["total_changes"] > 0
    second = runner.invoke(app, args, input="y\n")
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["total_changes"] == 0


class _CliIngestFakeLLM:
    """Minimal offline LLM for CLI ingest wiring: a person and a company linked by a custom alias."""

    def format_chain_summary(self) -> str:
        return "fake"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_wiring_vec(len(t)) for t in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        return ExtractionResult(
            entities=[
                ExtractedEntity(temp_id="p1", name="Ann Lee", summary="Analyst.", entity_type="person"),
                ExtractedEntity(temp_id="p2", name="Bo Corp", summary="A company.", entity_type="company"),
            ],
            edges=[ExtractedEdge(from_ref="p1", to_ref="p2", relation="EMPLOYED_BY_CUSTOM")],
        )


def test_cli_ingest_uses_registry_file_for_relations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module

    monkeypatch.setenv("EMBEDDING_DIM", str(WIRING_DIM))
    monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: _CliIngestFakeLLM())
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "note.md").write_text("Ann works with Bo.", encoding="utf-8")
    reg = create_minimal_registry()
    works_at = next(spec for spec in reg.relations if spec.name == "WORKS_AT")
    works_at.aliases.append("EMPLOYED_BY_CUSTOM")
    reg_path = tmp_path / "ontology_registry.json"
    save_registry(reg, reg_path)
    db_path = tmp_path / "ontology.db"
    monkeypatch.setenv("ONTOLOGY_REGISTRY", str(reg_path))

    result = CliRunner().invoke(
        cli_module.app, ["ingest", "--db", str(db_path), "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 0, result.output

    with OntologyDB(db_path, embedding_dim=WIRING_DIM, read_only=True) as db:
        relations = {r[0] for r in db.conn.execute("SELECT relation FROM edges").fetchall()}
    assert relations == {"WORKS_AT"}


def test_cli_ingest_prints_relations_held_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module

    monkeypatch.setenv("EMBEDDING_DIM", str(WIRING_DIM))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: _CliIngestFakeLLM())
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "note.md").write_text("Ann works with Bo.", encoding="utf-8")
    reg_path = tmp_path / "ontology_registry.json"
    save_registry(create_minimal_registry(), reg_path)
    monkeypatch.setenv("ONTOLOGY_REGISTRY", str(reg_path))

    result = CliRunner().invoke(
        cli_module.app, ["ingest", "--db", str(tmp_path / "ontology.db"), "--data-dir", str(data_dir)]
    )
    assert result.exit_code == 0, result.output
    assert "Relations pending review" in result.output
    assert "EMPLOYED_BY_CUSTOM (1)" in result.output


# ---------------------------------------------------------------------------
# Ingestion follow-ups: supporting unit tests
# ---------------------------------------------------------------------------


def _company(node_id: str, name: str, aliases: list[str] | None = None) -> Node:
    return Node(
        id=node_id, node_type="entity", name=name, summary=f"{name}.", aliases=aliases or [],
        facets={"entity_type": "company"},
    )


def test_node_lookup_uses_index_and_tracks_alias_edits_and_deletes(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "lk.db", embedding_dim=4, read_only=False) as db:
        node = _company("ent_k", "Kappa Corp", ["KPC"])
        db.upsert_node(node)
        plan = " ".join(
            str(r[3])
            for r in db.conn.execute(
                "EXPLAIN QUERY PLAN SELECT node_id FROM node_lookup WHERE key = ? AND node_type = ?",
                ("kpc", "entity"),
            ).fetchall()
        )
        assert "idx_node_lookup_key_type" in plan or "PRIMARY KEY" in plan or "sqlite_autoindex" in plan
        assert db.find_by_name_or_alias("kpc").id == "ent_k"

        node.aliases = ["KAPPA"]
        db.upsert_node(node)
        assert db.find_by_name_or_alias("KPC") is None
        assert db.find_by_name_or_alias("kappa").id == "ent_k"

        db.conn.execute("DELETE FROM nodes WHERE id = 'ent_k'")
        assert db.conn.execute("SELECT COUNT(*) FROM node_lookup").fetchone()[0] == 0


def test_node_lookup_backfills_old_db_and_read_only_falls_back(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        db.upsert_node(_company("ent_o", "Omicron Ltd", ["OMC"]))
        db.conn.execute("DROP TABLE node_lookup")
        db.conn.commit()

    with OntologyDB(db_path, embedding_dim=4, read_only=True) as ro:
        assert ro.find_by_name_or_alias("omc").id == "ent_o"

    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        assert db.conn.execute("SELECT COUNT(*) FROM node_lookup").fetchone()[0] == 2
        assert db.find_by_name_or_alias("Omicron Ltd").id == "ent_o"


def test_ingestion_log_migrates_old_schema_and_stores_stat(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_log.db"
    raw = sqlite3.connect(db_path)
    raw.execute(
        "CREATE TABLE ingestion_log (file_path TEXT PRIMARY KEY, doc_id TEXT NOT NULL UNIQUE, "
        "content_hash TEXT NOT NULL, ingested_at TEXT NOT NULL)"
    )
    raw.execute("INSERT INTO ingestion_log VALUES ('a.md', 'doc_a', 'h', '2026-01-01')")
    raw.commit()
    raw.close()

    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        log = db.get_ingestion_log()
        assert log["a.md"]["size"] is None and log["a.md"]["mtime_ns"] is None
        db.upsert_ingestion_log("b.md", "doc_b", "h2", size=10, mtime_ns=123)
        db.update_ingestion_stat("a.md", 7, 456)
        log = db.get_ingestion_log()
        assert (log["b.md"]["size"], log["b.md"]["mtime_ns"]) == (10, 123)
        assert (log["a.md"]["size"], log["a.md"]["mtime_ns"]) == (7, 456)


def test_get_nodes_preserves_order_and_skips_missing(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "gn.db", embedding_dim=4, read_only=False) as db:
        for nid in ("n1", "n2", "n3"):
            db.upsert_node(_company(nid, f"Co {nid}"))
        assert [n.id for n in db.get_nodes(["n3", "missing", "n1", "n3"])] == ["n3", "n1"]
        assert db.get_nodes([]) == []


def test_resolve_sentiment_takes_first_valid_candidate() -> None:
    from stock_ontology.pipeline import _resolve_sentiment

    assert _resolve_sentiment(None, "bogus", "negative", "positive") == "negative"
    assert _resolve_sentiment("POSITIVE", "negative") == "positive"
    assert _resolve_sentiment(None, None) == "neutral"


class _EmbedCountingLLM:
    def __init__(self, entities: list[ExtractedEntity]) -> None:
        self.entities = entities
        self.embed_calls = 0
        self.extract_calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        return [_wiring_vec(sum(map(ord, t))) for t in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        self.extract_calls += 1
        return ExtractionResult(entities=self.entities)


def test_probe_embeddings_are_batched_per_note(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "n.md").write_text("Three new people.", encoding="utf-8")
    people = [
        ExtractedEntity(temp_id=f"p{i}", name=f"Person {i}", summary="Analyst.", entity_type="person")
        for i in range(1, 4)
    ]
    llm = _EmbedCountingLLM(people)
    with OntologyDB(tmp_path / "b.db", embedding_dim=WIRING_DIM, read_only=False) as db:
        IngestionPipeline(db, llm, data_dir).run()
        assert len([n for n in db.list_all_nodes() if n.node_type == "entity"]) == 3
    assert llm.embed_calls == 1


def test_moves_handle_root_folder_ambiguity_reused_paths_and_force(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "sub").mkdir(parents=True)
    (data_dir / "sub" / "a.md").write_text("Note A.", encoding="utf-8")
    llm = _EmbedCountingLLM([])
    with OntologyDB(tmp_path / "m.db", embedding_dim=WIRING_DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_dir)
        pipeline.run()
        doc_a = db.get_ingestion_log()["sub/a.md"]["doc_id"]

        # Move to the root: relinked, not re-extracted.
        (data_dir / "sub" / "a.md").rename(data_dir / "a.md")
        report = pipeline.run()
        assert report.files_moved == 1 and llm.extract_calls == 1
        assert db.get_ingestion_log()["a.md"]["doc_id"] == doc_a

        # A new note at the old path must not collide with the moved note's doc ID.
        (data_dir / "sub" / "a.md").write_text("A different note.", encoding="utf-8")
        assert pipeline.run().errors == []
        log = db.get_ingestion_log()
        assert log["sub/a.md"]["doc_id"] != doc_a

        # Ambiguous: two new copies of one vanished note are both ingested normally.
        (data_dir / "a.md").rename(data_dir / "copy1.md")
        (data_dir / "copy2.md").write_text("Note A.", encoding="utf-8")
        before = llm.extract_calls
        report = pipeline.run()
        assert report.files_moved == 0
        assert llm.extract_calls == before + 2

        # --force reads and re-extracts everything.
        before = llm.extract_calls
        assert pipeline.run(force=True).files_processed == 3
        assert llm.extract_calls == before + 3


def test_cli_repair_builds_llm_only_with_reembed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module

    monkeypatch.setenv("EMBEDDING_DIM", str(WIRING_DIM))
    db_path = tmp_path / "ontology.db"
    reg_path = tmp_path / "ontology_registry.json"
    save_registry(create_minimal_registry(), reg_path)

    def seed() -> None:
        with OntologyDB(db_path, embedding_dim=WIRING_DIM, read_only=False) as db:
            db.upsert_node(_company("ent_x1", "Xi Corp"), embedding=_wiring_vec(0))
            db.upsert_node(_company("ent_x2", "xi corp"), embedding=_wiring_vec(1))

    calls: list[int] = []

    def fake_llm(_settings: Any) -> Any:
        calls.append(1)
        return _EmbedCountingLLM([])

    monkeypatch.setattr(cli_module, "create_llm_client", fake_llm)
    seed()
    args = ["repair", "--db", str(db_path), "--registry", str(reg_path), "--json"]
    plain = CliRunner().invoke(cli_module.app, args, input="y\n")
    assert plain.exit_code == 0, plain.output
    assert calls == []
    assert json.loads(plain.stdout)["reembedded"] == 0

    db_path.unlink()
    seed()
    with_flag = CliRunner().invoke(cli_module.app, [*args, "--reembed"], input="y\n")
    assert with_flag.exit_code == 0, with_flag.output
    assert calls == [1]
    assert json.loads(with_flag.stdout)["reembedded"] == 1


def test_confirmed_registry_rollout_rejects_data_changed_during_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module
    from stock_ontology.registry import create_minimal_registry, save_registry

    db_path = tmp_path / "ontology.db"
    registry_path = tmp_path / "ontology_registry.json"
    reg = create_minimal_registry()
    save_registry(reg, registry_path)
    with OntologyDB(db_path, registry=reg) as db:
        db.upsert_node(_company("first", "First"))

    def confirm_after_an_ingest(_prompt: str, **_kwargs: Any) -> bool:
        with OntologyDB(db_path, registry=reg) as db:
            db.upsert_node(_company("concurrent", "Concurrent"))
        return True

    monkeypatch.setattr(cli_module.typer, "confirm", confirm_after_an_ingest)
    result = CliRunner().invoke(
        cli_module.app, ["registry-apply", "--db", str(db_path), "--registry", str(registry_path)]
    )
    assert result.exit_code == 1, result.output
    assert "changed during review" in result.output
    with OntologyDB(db_path, read_only=True) as db:
        assert db.get_node("concurrent") is not None
        assert not any(key.startswith("registry_rollout:") for key in db.get_all_metadata())


def test_writer_opened_before_first_adoption_cannot_write_under_an_old_registry(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module
    from stock_ontology.registry import FacetSchemaError, create_minimal_registry, save_registry

    db_path = tmp_path / "ontology.db"
    registry_path = tmp_path / "ontology_registry.json"
    proposal_path = tmp_path / "proposal.json"
    baseline = create_minimal_registry()
    save_registry(baseline, registry_path)
    candidate = baseline.model_copy(deep=True)
    candidate.version += 1
    candidate.facet_schema["node"]["view"]["priority"] = {"kind": "number", "required": False}
    save_registry(candidate, proposal_path)

    runner = CliRunner()
    options = ["--db", str(db_path), "--registry", str(registry_path)]
    with OntologyDB(db_path, registry=baseline) as old_writer:
        for args in (["registry-apply"], ["registry-publish", str(proposal_path)], ["registry-apply"]):
            result = runner.invoke(cli_module.app, [*args, *options], input="y\n")
            assert result.exit_code == 0, result.output
        with pytest.raises(FacetSchemaError, match="applied registry changed"):
            old_writer.upsert_node(Node(
                id="stale",
                node_type="view",
                name="Stale registry view",
                summary="",
                facets={"view_type": "rumor", "priority": "invalid"},
            ))
    with OntologyDB(db_path, read_only=True) as db:
        assert db.get_node("stale") is None


def test_later_registry_confirmations_preserve_earlier_receipts(tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module
    from stock_ontology.registry import create_minimal_registry, save_registry

    db_path = tmp_path / "ontology.db"
    registry_path = tmp_path / "ontology_registry.json"
    proposal_path = tmp_path / "proposal.json"
    registry = create_minimal_registry()
    save_registry(registry, registry_path)
    with OntologyDB(db_path, registry=registry):
        pass
    runner = CliRunner()
    options = ["--db", str(db_path), "--registry", str(registry_path)]

    def approve(*args: str) -> None:
        result = runner.invoke(cli_module.app, [*args, *options], input="y\n")
        assert result.exit_code == 0, result.output

    approve("registry-apply")
    previous = registry.revision()
    for version in (2, 3):
        registry.version = version
        save_registry(registry, proposal_path)
        approve("registry-publish", str(proposal_path))
        approve("registry-apply")
        if version == 2:
            second = registry.revision()
            approve("registry-apply")

    with OntologyDB(db_path, read_only=True) as db:
        records = [json.loads(value) for k, value in db.get_all_metadata().items() if k.startswith("registry_rollout:")]
    assert any(record["from_revision"] == previous and record["to_revision"] == second for record in records)
    assert any(record["from_revision"] == second and record["to_revision"] == registry.revision() for record in records)
    publications = json.loads(registry_path.read_text(encoding="utf-8"))["publications"]
    assert [receipt["version"] for receipt in publications] == [2, 3]
    assert [receipt["revision"] for receipt in publications] == [second, registry.revision()]


def test_node_lookup_backfills_when_table_exists_but_misses_nodes(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.db"
    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        db.upsert_node(_company("ent_alpha", "Alpha Inc", ["ALP"]))
        db.upsert_node(_company("ent_beta2", "Beta Co"))
        # Simulate an interrupted first backfill / rows written by older code.
        db.conn.execute("DELETE FROM node_lookup")
        db.conn.commit()

    with OntologyDB(db_path, embedding_dim=4, read_only=False) as db:
        assert db.find_by_name_or_alias("Alpha Inc").id == "ent_alpha"
        assert db.find_by_name_or_alias("alp").id == "ent_alpha"
        assert db.find_by_name_or_alias("beta co").id == "ent_beta2"


# ---------------------------------------------------------------------------
# exact-entity-merge: supporting unit tests
# ---------------------------------------------------------------------------


def test_sync_merge_suggestions_drops_stale_pending_and_counts() -> None:
    from types import SimpleNamespace

    reg = create_minimal_registry()

    def pair(a: str, b: str) -> SimpleNamespace:
        return SimpleNamespace(
            node_type="company", node_a_id=a, node_a_name=a.upper(), node_b_id=b,
            node_b_name=b.upper(), reason="vector_similarity", distance=0.1,
        )

    s1 = reg.sync_suggestions([], [], [], merge_candidates=[pair("x", "y"), pair("y", "x"), pair("p", "q")])
    assert s1.pending_merges == 2 and len(reg.suggestions.merges) == 2
    reg.suggestions.merges[[m.pair_key for m in reg.suggestions.merges].index(frozenset({"p", "q"}))].status = "rejected"

    # Neither pair reported again: pending x/y is dropped, rejected p/q is kept.
    s2 = reg.sync_suggestions([], [], [], merge_candidates=[])
    assert s2.pending_merges == 0
    assert [(set(m.pair_key), m.status) for m in reg.suggestions.merges] == [({"p", "q"}, "rejected")]


class _RegistryResolveLLM:
    def __init__(self, result: ExtractionResult) -> None:
        self.result = result
        self.embed_calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        return [_wiring_vec(sum(map(ord, t))) for t in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        return self.result


def test_registry_resolves_company_by_ticker_and_theme_by_alias(tmp_path: Path) -> None:
    from stock_ontology.models import ExtractedTheme

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "n.md").write_text("Note.", encoding="utf-8")
    with OntologyDB(tmp_path / "r.db", embedding_dim=WIRING_DIM, read_only=False) as db:
        db.upsert_node(_company("ent_vrt", "Vertiv"))
        db.upsert_node(Node(id="thm_power", node_type="theme", name="AI Data Center Power & Cooling", summary="t", facets={"stage": "accelerating"}))
        db.upsert_node(Node(id="ent_vrt_person", node_type="entity", name="VRT Desk", summary="p",
                            facets={"entity_type": "person"}))
        llm = _RegistryResolveLLM(
            ExtractionResult(
                entities=[
                    # Different name, registry ticker VRT -> the stored Vertiv company.
                    ExtractedEntity(temp_id="e1", name="Vertiv Corp", summary="s", entity_type="company",
                                    facets=[{"key": "ticker", "value": "VRT"}]),
                    # A person is never resolved through the company registry.
                    ExtractedEntity(temp_id="p1", name="Vertiv Holdings Co. Analyst", summary="s",
                                    entity_type="person"),
                ],
                themes=[ExtractedTheme(temp_id="t1", name="AI Data Center Power Bottleneck", summary="s", stage="accelerating")],
            )
        )
        IngestionPipeline(db, llm, data_dir).run()
        companies = [n for n in db.list_all_nodes() if n.facets.get("entity_type") == "company"]
        assert [c.id for c in companies] == ["ent_vrt"]
        assert "Vertiv Corp" in companies[0].aliases
        themes = [n for n in db.list_all_nodes() if n.node_type == "theme"]
        assert [t.id for t in themes] == ["thm_power"]
        assert "AI Data Center Power Bottleneck" in themes[0].aliases


# ---------------------------------------------------------------------------
# typed-registry-schema: every write path checks the registry's facet schema
# ---------------------------------------------------------------------------

_SHIPPED_REGISTRY = Path(__file__).resolve().parents[1] / "ontology_registry.json"


def _typed_db(tmp_path: Path) -> OntologyDB:
    from stock_ontology.registry import load_registry

    db = OntologyDB(tmp_path / "typed.db", embedding_dim=8, registry=load_registry(_SHIPPED_REGISTRY))
    for i, nid in enumerate(("ent_a", "ent_b")):
        db.upsert_node(
            Node(id=nid, node_type="entity", name=nid, summary=nid, facets={"entity_type": "company", "sector": "Tech"}),
            embedding=_unit_vec(i),
        )
    return db


def _edge_facets(db: OntologyDB, edge_id: str) -> dict[str, Any]:
    import json

    row = db.conn.execute("SELECT facets_json FROM edges WHERE id = ?", (edge_id,)).fetchone()
    return json.loads(row[0])


def test_update_edge_refuses_dropping_required_basis(tmp_path: Path) -> None:
    from stock_ontology.registry import FacetSchemaError

    with _typed_db(tmp_path) as db:
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETE", facets={"basis": "extracted"}))
        with pytest.raises(FacetSchemaError):
            db.update_edge("e1", relation="COMPETE", from_id="ent_a", to_id="ent_b", facets={"note": "x"})
        assert _edge_facets(db, "e1") == {"basis": "extracted"}


def test_upsert_edge_merge_path_checks_merged_facets(tmp_path: Path) -> None:
    with _typed_db(tmp_path) as db:
        edge = Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETE", facets={"basis": "Extracted"})
        db.upsert_edge(edge)
        assert _edge_facets(db, "e1") == {"basis": "extracted"}
        # A legacy row without `basis`: merging facets into it still has to meet the schema.
        db.conn.execute("UPDATE edges SET facets_json = '{}' WHERE id = 'e1'")
        db.conn.commit()
        with pytest.raises(ValueError):
            db.upsert_edge(edge.model_copy(update={"facets": {"note": "x"}}))
        assert _edge_facets(db, "e1") == {}


def test_upsert_consensus_view_is_checked_and_conforms(tmp_path: Path) -> None:
    from stock_ontology.registry import FacetSchemaError

    with _typed_db(tmp_path) as db:
        bad = Node(id="vw_c", node_type="view", name="c", summary="c", facets={"target_price": "a lot", "view_type": "analyst_report"})
        with pytest.raises(FacetSchemaError):
            db.upsert_consensus_view("ent_a", bad, _unit_vec(3), [], [])
        assert db.get_node("vw_c") is None

        good = Node(id="vw_c", node_type="view", name="c", summary="c", facets={"target_price": "USD 630", "view_type": "analyst_report"})
        db.upsert_consensus_view("ent_a", good, _unit_vec(3), [], [])
        stored = db.get_node("vw_c")
        assert stored is not None
        assert stored.facets["view_type"] == "consensus" and stored.facets["target_price"] == {"amount": 630, "currency": "USD"}
        bases = {r[0] for r in db.conn.execute("SELECT json_extract(facets_json, '$.basis') FROM edges")}
        assert bases == {"synthesized"}


def test_merge_node_into_writes_no_facets_and_survivor_upsert_is_checked(tmp_path: Path) -> None:
    from stock_ontology.registry import FacetSchemaError

    with _typed_db(tmp_path) as db:
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETE", facets={"basis": "extracted"}))
        survivor = db.get_node("ent_a")
        assert survivor is not None
        with pytest.raises(FacetSchemaError):
            db.upsert_node(survivor.model_copy(update={"facets": {"ticker": "A"}}))
        db.merge_node_into("ent_b", "ent_a")
        assert db.get_node("ent_b") is None
        assert db.get_node("ent_a").facets == {"entity_type": "company", "sector": "Tech"}


def test_writable_open_stamps_fresh_db_but_preserves_existing_rows_and_stamp(tmp_path: Path) -> None:
    import json

    from stock_ontology.registry import load_registry

    reg = load_registry(_SHIPPED_REGISTRY)
    path = tmp_path / "stamp.db"

    def insert_view(db: OntologyDB, node_id: str, target_price: str) -> None:
        db.conn.execute(
            "INSERT INTO nodes (id, node_type, name, summary, facets_json, created_at, updated_at) "
            "VALUES (?, 'view', 'v', 'v', ?, '2026-01-01', '2026-01-01')",
            (node_id, json.dumps({"view_type": "rumor", "target_price": target_price})),
        )
        db.conn.commit()

    def target_price(db: OntologyDB, node_id: str) -> object:
        row = db.conn.execute("SELECT facets_json FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return json.loads(row[0])["target_price"]

    with OntologyDB(path, embedding_dim=8, registry=reg) as db:
        assert db.get_metadata("registry_version") == reg.schema_stamp()
        insert_view(db, "vw_lots", "lots")
        insert_view(db, "vw_num", "USD 630")
    # A matching stamp skips the migration: the coercible row stays as stored.
    with OntologyDB(path, embedding_dim=8, registry=reg) as db:
        assert target_price(db, "vw_num") == "USD 630"
        # Older metadata is preserved until an approved rollout.
        db.set_metadata("registry_version", str(reg.version + 5))
    with pytest.raises(ValueError, match="explicit registry adoption"):
        OntologyDB(path, embedding_dim=8, registry=reg)
    with OntologyDB(path, embedding_dim=8, read_only=True) as db:
        assert db.get_metadata("registry_version") == str(reg.version + 5)
        assert target_price(db, "vw_num") == "USD 630"
        assert target_price(db, "vw_lots") == "lots"


def test_db_without_registry_enforces_the_default_schema_but_never_stamps(tmp_path: Path) -> None:
    from stock_ontology.registry import FacetSchemaError

    with OntologyDB(tmp_path / "plain.db", embedding_dim=8) as db:
        with pytest.raises(FacetSchemaError):
            db.upsert_node(Node(id="vw", node_type="view", name="v", summary="v", facets={"target_price": "lots", "view_type": "analyst_report"}))
        for i, nid in enumerate(("ent_a", "ent_b")):
            db.upsert_node(Node(id=nid, node_type="entity", name=nid, summary=nid, facets={"entity_type": "company"}), embedding=_unit_vec(i))
        with pytest.raises(FacetSchemaError):
            db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETE", facets={}))
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETE", facets={"basis": "extracted"}))
        with pytest.raises(FacetSchemaError):
            db.update_edge("e1", relation="COMPETE", from_id="ent_a", to_id="ent_b", facets={"basis": "guessed"})
        bad = Node(id="vw_c", node_type="view", name="c", summary="c", facets={"as_of": "someday"})
        with pytest.raises(FacetSchemaError):
            db.upsert_consensus_view("ent_a", bad, _unit_vec(3), [], [])
        db.merge_node_into("ent_b", "ent_a")
        assert db.get_node("ent_a").facets == {"entity_type": "company"}
        assert db.get_metadata("registry_version") is None


# ---------------------------------------------------------------------------
# registry-schema-v2: unmapped relations on update, the schema stamp
# ---------------------------------------------------------------------------


def test_update_edge_refuses_relation_the_registry_does_not_map(tmp_path: Path) -> None:
    import json

    from stock_ontology.registry import FacetSchemaError

    with _typed_db(tmp_path) as db:
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETE", facets={"basis": "extracted"}))
        with pytest.raises(FacetSchemaError, match="FROBNICATES"):
            db.update_edge("e1", relation="FROBNICATES", from_id="ent_a", to_id="ent_b", facets={"basis": "extracted"})
        row = db.conn.execute("SELECT relation, facets_json FROM edges WHERE id = 'e1'").fetchone()
        assert (row["relation"], json.loads(row["facets_json"])) == ("COMPETE", {"basis": "extracted"})
        # A mapped alias is accepted and stored by its normalized name, as before.
        db.update_edge("e1", relation="competes-with", from_id="ent_a", to_id="ent_b", facets={"basis": "extracted"})


def test_schema_stamp_is_stable_for_identical_content_and_key_order() -> None:
    import json

    from stock_ontology.registry import OntologyRegistry, load_registry

    reg = load_registry(_SHIPPED_REGISTRY)
    raw = json.loads(_SHIPPED_REGISTRY.read_text(encoding="utf-8"))

    def reverse_keys(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: reverse_keys(value[k]) for k in reversed(list(value))}
        return value

    reordered = {**raw, **{k: reverse_keys(raw[k]) for k in ("facet_vocabularies", "facet_schema", "metadata_max_length")}}
    assert OntologyRegistry.model_validate(reordered).schema_stamp() == reg.schema_stamp()
    # The human-facing version label is not an input.
    assert OntologyRegistry.model_validate({**raw, "version": raw["version"] + 1}).schema_stamp() == reg.schema_stamp()
    assert reg.schema_stamp().startswith("sha256:")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["facet_vocabularies"]["node"]["view"]["stance"]["members"].update({"bullish": "Changed."}),
        lambda raw: raw["facet_schema"]["node"]["view"].update({"horizon": {"kind": "text", "required": False}}),
        lambda raw: raw["metadata_max_length"].update({"summary": 999}),
    ],
    ids=["facet_vocabularies", "facet_schema", "metadata_max_length"],
)
def test_schema_stamp_changes_with_each_input(mutate) -> None:
    import json

    from stock_ontology.registry import OntologyRegistry, load_registry

    raw = json.loads(_SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    mutate(raw)
    # Built without load validation, so a vocabulary edit code does not share still hashes.
    changed = OntologyRegistry.model_construct(**raw)
    assert changed.schema_stamp() != load_registry(_SHIPPED_REGISTRY).schema_stamp()


# ---------------------------------------------------------------------------
# registry-schema-v2 R1: the `pending_edges` table
# ---------------------------------------------------------------------------


def _pending_rows(db: OntologyDB) -> list[tuple[str, str, str, str | None]]:
    return [
        tuple(r)
        for r in db.conn.execute("SELECT id, from_id, to_id, source_doc_id FROM pending_edges ORDER BY id").fetchall()
    ]


def test_pending_edges_table_holds_raw_relation_and_cascades_with_endpoints(tmp_path: Path) -> None:
    import json

    with _typed_db(tmp_path) as db:
        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(pending_edges)")}
        assert {"id", "from_id", "to_id", "relation", "facets_json", "source_doc_id", "created_at"} <= cols
        db.upsert_node(
            Node(id="ent_c", node_type="entity", name="ent_c", summary="c", facets={"entity_type": "company", "sector": "Tech"})
        )
        db.insert_pending_edge(Edge(id="p1", from_id="ent_a", to_id="ent_b", relation="partners-with", facets={"basis": "extracted", "x": [1]}))
        db.insert_pending_edge(Edge(id="p2", from_id="ent_b", to_id="ent_c", relation="FROBNICATES", facets={"basis": "extracted"}))
        row = db.conn.execute("SELECT relation, facets_json FROM pending_edges WHERE id = 'p1'").fetchone()
        assert (row["relation"], json.loads(row["facets_json"])) == ("partners-with", {"basis": "extracted", "x": [1]})
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0

        db.insert_pending_edge(Edge(id="p3", from_id="ent_a", to_id="ent_c", relation="X", facets={"basis": "extracted"}))

        # A merge repoints the loser's pending rows; one between the merged pair would be a self-loop.
        db.merge_node_into("ent_a", "ent_b")
        rows = db.conn.execute("SELECT id, from_id, to_id FROM pending_edges ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [("p2", "ent_b", "ent_c"), ("p3", "ent_b", "ent_c")]
        db.conn.execute("DELETE FROM nodes WHERE id = 'ent_c'")
        db.conn.commit()
        assert _pending_rows(db) == []


def test_delete_document_artifacts_clears_only_that_docs_pending_edges(tmp_path: Path) -> None:
    with _typed_db(tmp_path) as db:
        for doc in ("doc_1", "doc_2"):
            db.upsert_node(
                Node(id=f"vw_{doc}", node_type="view", name=doc, summary=doc, source_doc_id=doc, facets={"view_type": "rumor"})
            )
            db.insert_pending_edge(Edge(id=f"p_{doc}", from_id=f"vw_{doc}", to_id="ent_a", relation="X", source_doc_id=doc))
            # Entity-to-entity pending rows survive only through `source_doc_id`.
            db.insert_pending_edge(Edge(id=f"pe_{doc}", from_id="ent_a", to_id="ent_b", relation="X", source_doc_id=doc))
        assert db.list_artifact_doc_ids() == {"doc_1", "doc_2"}
        db.delete_document_artifacts("doc_1")
        assert [r[0] for r in _pending_rows(db)] == ["p_doc_2", "pe_doc_2"]


def test_read_only_db_without_pending_table_lists_no_pending_edges(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with OntologyDB(path, embedding_dim=8) as db:
        db.conn.execute("DROP TABLE pending_edges")
        db.conn.commit()
    with OntologyDB(path, embedding_dim=8, read_only=True) as ro:
        assert ro.list_pending_edges_with_endpoints() == []


def test_note_entity_membership_follows_canonical_merge_and_document_removal() -> None:
    with OntologyDB(":memory:", embedding_dim=8) as db:
        for node_id in ("old", "canonical"):
            db.upsert_node(Node(id=node_id, name=node_id, node_type="entity", summary="",
                                facets={"entity_type": "institution"}))
        db.upsert_ingestion_log("note.md", "doc", "content", entity_ids=("old", "canonical"))
        db.upsert_ingestion_log("empty.txt", "empty", "empty", entity_ids=())
        db.upsert_ingestion_log("legacy.txt", "legacy", "legacy")

        assert db.get_note_state("empty.txt")["entities_recorded"]
        assert not db.get_note_state("legacy.txt")["entities_recorded"]
        db.merge_node_into("old", "canonical")
        assert [node.id for node in db.list_note_entities("doc")] == ["canonical"]
        db.delete_document_artifacts("doc")
        assert db.list_note_entities("doc") == []
        assert db.get_node("canonical") is not None


def test_job_tables_are_added_to_a_database_created_before_them(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "old.db"
    with OntologyDB(db_path, embedding_dim=WIRING_DIM) as db:
        db.upsert_node(_company("ent_old", "Old Corp"), embedding=_wiring_vec(0))
        db.upsert_ingestion_log("old.md", "old", "hash", entity_ids=("ent_old",))
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE jobs")
        conn.execute("DROP TABLE consensus_refresh")

    with OntologyDB(db_path, embedding_dim=WIRING_DIM, read_only=True) as db:
        assert db.jobs.get("job_any") is None, "an old read-only database has no jobs yet"
        assert db.jobs.consensus_state("ent_old") is None
    with OntologyDB(db_path, embedding_dim=WIRING_DIM) as db:
        assert db.get_node("ent_old") is not None
        assert db.get_note_state("old.md") is not None
        assert db.jobs.list() == [] and db.jobs.list_consensus_refresh() == []
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"jobs", "consensus_refresh", "nodes", "ingestion_log"} <= tables


def test_search_nodes_by_name_matches_names_and_aliases_within_types(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "graph.db", embedding_dim=8) as db:
        for node in (
            Node(id="nvda", name="NVIDIA", summary="chip maker", aliases=["Green Team"], node_type="entity",
                 facets={"entity_type": "company"}),
            Node(id="jensen", name="Jensen Huang", summary="", node_type="entity", facets={"entity_type": "person"}),
            Node(id="ai", name="AI chips", summary="", node_type="theme", facets={"stage": "emerging"}),
            Node(id="pct", name="100% Club", summary="", node_type="theme", facets={"stage": "emerging"}),
        ):
            db.upsert_node(node)
        ids = lambda query, **kwargs: [node.id for node in db.search_nodes_by_name(query, **kwargs)]  # noqa: E731
        assert ids("nvi") == ["nvda"]
        assert ids("green") == ["nvda"]  # alias
        assert ids("chip") == ["ai"]  # names only, not summaries
        assert ids("n", types=["entity:person"]) == ["jensen"]
        assert ids("i", types=["theme", "entity:company"]) == ["ai", "nvda"]
        assert ids("a") == ["ai", "jensen", "nvda"]
        assert ids("%") == ["pct"]  # LIKE wildcards are literal
        assert ids("n", limit=1) == ["nvda"]  # "NVIDIA" starts with it, "Jensen Huang" only contains it
        assert ids("  ") == []


# ---------------------------------------------------------------------------
# Claim graph (proposal theme-catalysts-phase-1): theses and thesis memberships
# ---------------------------------------------------------------------------


def _claim_db(path: Path) -> OntologyDB:
    db = OntologyDB(path, embedding_dim=8)
    for idx, node in enumerate([
        Node(id="thm_dc", node_type="theme", name="Data Center Rollout", summary="s", facets={"stage": "emerging"}),
        Node(id="thm_dc2", node_type="theme", name="DC Rollout", summary="s", facets={"stage": "emerging"}),
        Node(id="ent_a", node_type="entity", name="Supplier A", summary="s",
             facets={"entity_type": "company", "sector": "Tech"}),
        Node(id="ent_a2", node_type="entity", name="Supplier A Holdings", summary="s",
             facets={"entity_type": "company", "sector": "Tech"}),
    ]):
        db.upsert_node(node, embedding=_unit_vec(idx))
    return db


def test_claim_tables_round_trip_on_a_fresh_and_an_upgraded_database(tmp_path: Path) -> None:
    claim_tables = {"claim_theses", "claim_memberships", "claim_catalysts", "claim_predictions"}
    with _claim_db(tmp_path / "fresh.db") as db:
        thesis = db.claims.add_thesis("thm_dc", "The rollout benefits optical suppliers.")
        member = db.claims.add_membership(thesis, "ent_a", "candidate", "", ("Qualification", "2027-06-30", "Volume orders."))
        assert db.claims.get_thesis(thesis)["statement"] == "The rollout benefits optical suppliers."
        assert db.claims.get_membership(member)["catalyst"] == {
            "id": db.claims.get_membership(member)["catalyst"]["id"],
            "event": "Qualification", "by_date": "2027-06-30", "expected_effect": "Volume orders.",
        }

    # A database from before the claim graph gains its tables on the next writable open.
    legacy = tmp_path / "legacy.db"
    with _claim_db(legacy) as db:
        for table in ("claim_predictions", "claim_catalysts", "claim_memberships", "claim_theses"):
            db.conn.execute(f"DROP TABLE {table}")
        db.conn.commit()
    with OntologyDB(legacy, embedding_dim=8, read_only=True) as db:
        assert db.claims.list_theses("thm_dc") == [], "a read-only open of an older database reads no claims"
        assert db.claims.covered_company_ids("thm_dc") == set()
    with OntologyDB(legacy, embedding_dim=8) as db:
        tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert claim_tables <= tables
        thesis = db.claims.add_thesis("thm_dc", "Upgraded.")
        assert [t["id"] for t in db.claims.list_theses("thm_dc")] == [thesis]


def test_one_membership_per_company_and_thesis_and_many_predictions_per_catalyst(tmp_path: Path) -> None:
    with _claim_db(tmp_path / "claims.db") as db:
        thesis = db.claims.add_thesis("thm_dc", "T")
        member = db.claims.add_membership(thesis, "ent_a", "in", "Ships in volume.")
        with pytest.raises(sqlite3.IntegrityError):
            db.claims.add_membership(thesis, "ent_a", "candidate", "", ("E", "2027-01-01", "X"))
        # A catalyst can carry more than one prediction.
        db.claims.edit_membership(member, "candidate", "", ("Qualification", "2027-06-30", "Entry effect."))
        catalyst_id = db.claims.get_membership(member)["catalyst"]["id"]
        db.conn.execute(
            "INSERT INTO claim_predictions (id, catalyst_id, direction, expected_effect, created_at, updated_at) "
            "VALUES ('prd_exit', ?, 'exit', 'Would remove exposure.', 'now', 'now')",
            (catalyst_id,),
        )
        db.conn.commit()
        count = db.conn.execute("SELECT COUNT(*) FROM claim_predictions WHERE catalyst_id = ?", (catalyst_id,))
        assert count.fetchone()[0] == 2
        assert db.claims.get_membership(member)["catalyst"]["expected_effect"] == "Entry effect."
        # Removing the thesis removes its memberships, catalysts, and predictions.
        assert db.claims.remove_thesis(thesis)
        for table in ("claim_memberships", "claim_catalysts", "claim_predictions"):
            assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_a_watching_membership_commits_with_its_catalyst_or_not_at_all(tmp_path: Path) -> None:
    with _claim_db(tmp_path / "claims.db") as db:
        thesis = db.claims.add_thesis("thm_dc", "T")
        # The catalyst insert fails after the membership row is written (by_date is NOT NULL).
        with pytest.raises(sqlite3.IntegrityError):
            db.claims.add_membership(thesis, "ent_a", "candidate", "", ("Qualification", None, "Volume orders."))  # type: ignore[arg-type]
        for table in ("claim_memberships", "claim_catalysts", "claim_predictions"):
            assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_merge_node_into_moves_theses_and_resolves_membership_collisions(tmp_path: Path) -> None:
    with _claim_db(tmp_path / "claims.db") as db:
        thesis = db.claims.add_thesis("thm_dc2", "T")
        survivor_member = db.claims.add_membership(thesis, "ent_a", "in", "Ships in volume.")
        loser_member = db.claims.add_membership(thesis, "ent_a2", "candidate", "", ("Qualification", "2027-06-30", "X"))

        db.merge_node_into("thm_dc2", "thm_dc")
        assert db.claims.get_thesis(thesis)["theme_id"] == "thm_dc"

        db.merge_node_into("ent_a2", "ent_a")
        rows = db.claims.list_memberships(thesis)
        assert [(m["id"], m["company_id"], m["status"]) for m in rows] == [(survivor_member, "ent_a", "in")]
        assert db.claims.get_membership(loser_member) is None
        assert rows[0]["catalyst"]["event"] == "Qualification", "the survivor keeps the loser's catalyst"
        dangling = db.conn.execute(
            "SELECT COUNT(*) FROM claim_memberships m LEFT JOIN nodes n ON n.id = m.company_id WHERE n.id IS NULL"
        ).fetchone()[0]
        assert dangling == 0


def test_a_node_a_claim_points_at_cannot_be_deleted_out_from_under_it(tmp_path: Path) -> None:
    with _claim_db(tmp_path / "claims.db") as db:
        db.claims.add_thesis("thm_dc", "T")
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute("DELETE FROM nodes WHERE id = 'thm_dc'")
