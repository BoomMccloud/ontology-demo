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
                    summary="Should fail",
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
            summary="Hyperscaler AI spend",
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
            Edge(id="e1", from_id="evt_1", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1")
        )
        db.upsert_edge(
            Edge(id="e2", from_id="vw_1", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1")
        )
        db.upsert_edge(
            Edge(id="e3", from_id="evt_1", to_id="thm_ai", relation="RELATES_TO", source_doc_id="doc_1")
        )
        db.upsert_edge(
            Edge(id="e4", from_id="evt_2", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_2")
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
            Edge(id="ed1", from_id="ent_vrt", to_id="thm_power", relation="BENEFITS_FROM")
        )
        db.upsert_edge(
            Edge(id="ed2", from_id="evt_call", to_id="thm_power", relation="RELATES_TO", source_doc_id="doc_call")
        )
        db.upsert_edge(
            Edge(id="ed3", from_id="evt_call", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_call")
        )
        db.upsert_edge(
            Edge(id="ed4", from_id="ent_tsmc", to_id="ent_nvda", relation="SUPPLIES_TO")
        )

        c1 = Node(
            id="vw_cons_1",
            node_type="view",
            name="Consensus: Hold NVIDIA",
            summary="Wait on mask respin",
            facets={"stance": "hold", "pillars": ["Blackwell yield stabilizes"]},
        )
        db.upsert_consensus_view("ent_nvda", c1, _unit_vec(6), supporting_ids=["evt_call"], contradicting_ids=[])
        assert db.get_entity_consensus("ent_nvda").id == "vw_cons_1"

        c2 = Node(
            id="vw_cons_2",
            node_type="view",
            name="Consensus: Buy NVIDIA",
            summary="Blackwell ramping cleanly",
            facets={"stance": "buy", "pillars": ["Hyperscaler capex >25%"]},
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
                facets={"sentiment": "positive"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_qcom",
                from_id="evt_modem",
                to_id="ent_qcom",
                relation="ABOUT",
                facets={"sentiment": "negative"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_nvda",
                from_id="evt_modem",
                to_id="ent_nvda",
                relation="ABOUT",
                source_doc_id="doc_1",
            )
        )
        # Two edges from evt_rumored_news to ent_qcom to verify deduplication.
        db.upsert_edge(
            Edge(
                id="ed_rn_rel",
                from_id="evt_rumored_news",
                to_id="ent_qcom",
                relation="RELATES_TO",
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_rn_about",
                from_id="evt_rumored_news",
                to_id="ent_qcom",
                relation="ABOUT",
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(id="ed_vrumor", from_id="vw_rumor", to_id="ent_qcom", relation="ABOUT", source_doc_id="doc_1")
        )
        db.upsert_edge(
            Edge(
                id="ed_vleg",
                from_id="vw_legacy_cautious",
                to_id="ent_qcom",
                relation="ABOUT",
                source_doc_id="doc_legacy",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_eleg",
                from_id="evt_legacy_news",
                to_id="ent_qcom",
                relation="ABOUT",
                source_doc_id="doc_legacy",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_auth",
                from_id="evt_authored",
                to_id="ent_qcom",
                relation="AUTHORED_BY",
                source_doc_id="doc_1",
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
    edge = Edge(id="e_ab", from_id="n_a", to_id="n_b", relation="COMPETES_WITH")

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
            Node(id="ent_x", node_type="entity", name="Straße Corp", summary="x", aliases=[" SCX "])
        )
        db.upsert_node(Node(id="thm_x", node_type="theme", name="SCX", summary="theme"))
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
            Node(id="evt_orphan", node_type="event", name="Orphan", summary="o", source_doc_id="doc_gone"),
            embedding=_wiring_vec(2),
        )
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="COMPETES_WITH"))
        db.upsert_edge(Edge(id="e2", from_id="evt_orphan", to_id="ent_a", relation="ABOUT", source_doc_id="doc_gone"))
    save_registry(create_minimal_registry(), reg_path)
    args = ["repair", "--db", str(db_path), "--registry", str(reg_path), "--json"]

    runner = CliRunner()
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["total_changes"] > 0
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["total_changes"] == 0


class _CliIngestFakeLLM:
    """Minimal offline LLM for CLI ingest wiring: two people linked by a custom alias."""

    def format_chain_summary(self) -> str:
        return "fake"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_wiring_vec(len(t)) for t in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        return ExtractionResult(
            entities=[
                ExtractedEntity(temp_id="p1", name="Ann Lee", summary="Analyst.", entity_type="person"),
                ExtractedEntity(temp_id="p2", name="Bo Kim", summary="Analyst.", entity_type="person"),
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
    plain = CliRunner().invoke(cli_module.app, args)
    assert plain.exit_code == 0, plain.output
    assert calls == []
    assert json.loads(plain.output)["reembedded"] == 0

    db_path.unlink()
    seed()
    with_flag = CliRunner().invoke(cli_module.app, [*args, "--reembed"])
    assert with_flag.exit_code == 0, with_flag.output
    assert calls == [1]
    assert json.loads(with_flag.output)["reembedded"] == 1


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
        db.upsert_node(Node(id="thm_power", node_type="theme", name="AI Data Center Power & Cooling", summary="t"))
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
                themes=[ExtractedTheme(temp_id="t1", name="AI Data Center Power Bottleneck", summary="s")],
            )
        )
        IngestionPipeline(db, llm, data_dir).run()
        companies = [n for n in db.list_all_nodes() if n.facets.get("entity_type") == "company"]
        assert [c.id for c in companies] == ["ent_vrt"]
        assert "Vertiv Corp" in companies[0].aliases
        themes = [n for n in db.list_all_nodes() if n.node_type == "theme"]
        assert [t.id for t in themes] == ["thm_power"]
        assert "AI Data Center Power Bottleneck" in themes[0].aliases
