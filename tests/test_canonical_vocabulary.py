"""Offline witnesses for the canonical-vocabulary proposal (enum facets, relation names, signal filters)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_ontology.audit import run_ontology_audit
from stock_ontology.db import OntologyDB
from stock_ontology.models import (
    ConsensusSynthesis,
    Edge,
    ExtractedEdge,
    ExtractedEntity,
    ExtractedEvent,
    ExtractedTheme,
    ExtractedView,
    ExtractionResult,
    Node,
)
from stock_ontology.pipeline import IngestionPipeline
from stock_ontology.registry import create_minimal_registry, normalize_relation_name
from stock_ontology.repair import repair_ontology
from stock_ontology.search import SearchFilters, search_ontology

DIM = 16


def _embed(text: str) -> list[float]:
    digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
    vec = [(digest[i % len(digest)] / 255.0) - 0.5 for i in range(DIM)]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class _VocabFakeLLM:
    """Offline LLM stub; `extraction` is returned for every note."""

    def __init__(self, extraction: ExtractionResult) -> None:
        self.extraction = extraction

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_embed(t) for t in texts]

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        return self.extraction

    def synthesize_consensus(
        self,
        *,
        company: Node,
        events: list[Node],
        views: list[Node],
        themes: list[Node],
        prior_consensus: Node | None,
    ) -> ConsensusSynthesis:
        return ConsensusSynthesis(
            stance="buy",
            support_strength="moderate",
            conviction="medium",
            summary=f"Consensus buy for {company.name}.",
            pillars=["Demand"],
            supporting_node_ids=[n.id for n in events],
            contradicting_node_ids=[],
        )


def _ingest(tmp_path: Path, extraction: ExtractionResult) -> OntologyDB:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "2026-11-21_note.md").write_text("Vocabulary note.", encoding="utf-8")
    db = OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False)
    report = IngestionPipeline(db, _VocabFakeLLM(extraction), data_dir).run()
    assert report.errors == []
    assert report.files_processed == 1
    return db


def _one(db: OntologyDB, name: str, node_type: str) -> Node:
    node = db.find_by_name_or_alias(name, node_type=node_type)  # type: ignore[arg-type]
    assert node is not None, f"{node_type} {name!r} was not stored"
    return node


def _facets(node: Node, *keys: str) -> dict[str, Any]:
    return {k: node.facets.get(k) for k in keys}


# ---------------------------------------------------------------------------
# Ingest write path
# ---------------------------------------------------------------------------


def test_ingest_stores_mixed_case_and_alias_enum_values_canonically(tmp_path: Path) -> None:
    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(temp_id="e_acme", name="Acme Robotics", summary="Robots.", entity_type="Company"),
            ExtractedEntity(temp_id="e_beta", name="Beta Motion", summary="Actuators.", entity_type="COMPANY"),
            ExtractedEntity(temp_id="p_jane", name="Jane Roe", summary="CFO.", entity_type="Person"),
        ],
        events=[
            ExtractedEvent(
                temp_id="ev1",
                name="Acme Delay Rumor",
                summary="Rumored delay.",
                event_type="News",
                event_date="2026-11-21",
                status="Rumored",
                sentiment="Negative",
            )
        ],
        views=[
            ExtractedView(
                temp_id="vw1",
                name="Desk Rumour On Acme",
                summary="Desk hears of a big order.",
                view_type="Rumour",
                stance="Bullish",
                support_strength="Strong",
                conviction="HIGH",
                as_of="2026-11-21",
            ),
            ExtractedView(
                temp_id="vw2",
                name="Broker Outperform On Acme",
                summary="Broker rates Acme outperform.",
                view_type="Analyst_Report",
                stance="Outperform",
                sentiment="Positive",
                as_of="2026-11-21",
            ),
        ],
        themes=[
            ExtractedTheme(temp_id="t1", name="Warehouse Automation", summary="Robots in warehouses.", stage="Emerging"),
        ],
        edges=[
            ExtractedEdge(from_ref="ev1", to_ref="e_acme", relation="ABOUT"),
            ExtractedEdge(from_ref="vw1", to_ref="e_acme", relation="ABOUT"),
            ExtractedEdge(from_ref="vw2", to_ref="e_acme", relation="ABOUT"),
            ExtractedEdge(from_ref="e_acme", to_ref="e_beta", relation="competes-with"),
        ],
    )
    with _ingest(tmp_path, extraction) as db:
        assert _one(db, "Acme Robotics", "entity").facets["entity_type"] == "company"
        assert _one(db, "Beta Motion", "entity").facets["entity_type"] == "company"
        assert _one(db, "Jane Roe", "entity").facets["entity_type"] == "person"
        assert _facets(_one(db, "Acme Delay Rumor", "event"), "event_type", "status", "sentiment") == {
            "event_type": "news",
            "status": "rumored",
            "sentiment": "negative",
        }
        assert _facets(
            _one(db, "Desk Rumour On Acme", "view"),
            "view_type",
            "stance",
            "sentiment",
            "support_strength",
            "conviction",
        ) == {
            "view_type": "rumor",
            "stance": "bullish",
            "sentiment": "positive",
            "support_strength": "strong",
            "conviction": "high",
        }
        # Decision 3: `outperform` is an alias of `buy`.
        assert _facets(_one(db, "Broker Outperform On Acme", "view"), "view_type", "stance", "sentiment") == {
            "view_type": "analyst_report",
            "stance": "buy",
            "sentiment": "positive",
        }
        assert _one(db, "Warehouse Automation", "theme").facets["stage"] == "emerging"
        note_relations = {
            r["relation"]
            for r in db.conn.execute("SELECT relation FROM edges WHERE source_doc_id IS NOT NULL").fetchall()
        }
        assert note_relations == {"ABOUT", "COMPETE"}
        # Acme's consensus view adds its own ABOUT link and SUPPORTS edges from the fake synthesis.
        relations = {r["relation"] for r in db.conn.execute("SELECT relation FROM edges").fetchall()}
        assert relations == {"ABOUT", "COMPETE", "SUPPORTS"}


def test_ingest_stores_field_fallback_for_out_of_vocabulary_values(tmp_path: Path) -> None:
    extraction = ExtractionResult(
        entities=[
            ExtractedEntity(temp_id="e_acme", name="Acme Robotics", summary="Robots.", entity_type="Spaceship"),
        ],
        events=[
            ExtractedEvent(
                temp_id="ev1",
                name="Acme Gossip",
                summary="Hallway gossip.",
                event_type="Gossip",
                event_date="2026-11-21",
                status="Maybe",
                sentiment="Ecstatic",
            )
        ],
        views=[
            ExtractedView(
                temp_id="vw1",
                name="Acme Hunch",
                summary="A hunch.",
                view_type="Hunch",
                stance="Moonshot",
                sentiment="Ecstatic",
                support_strength="Huge",
                conviction="Total",
                as_of="2026-11-21",
            ),
            ExtractedView(
                temp_id="vw2",
                name="Acme Bear Case",
                summary="Bearish.",
                view_type="pm_view",
                stance="bearish",
                sentiment="Ecstatic",
                as_of="2026-11-21",
            ),
        ],
        themes=[ExtractedTheme(temp_id="t1", name="Warehouse Automation", summary="Robots.", stage="Zombie")],
        edges=[
            ExtractedEdge(from_ref="ev1", to_ref="e_acme", relation="ABOUT"),
            ExtractedEdge(from_ref="vw1", to_ref="e_acme", relation="ABOUT"),
            ExtractedEdge(from_ref="vw2", to_ref="e_acme", relation="ABOUT"),
        ],
    )
    with _ingest(tmp_path, extraction) as db:
        assert _one(db, "Acme Robotics", "entity").facets["entity_type"] == "company"
        assert _facets(_one(db, "Acme Gossip", "event"), "event_type", "status", "sentiment") == {
            "event_type": "fact",
            "status": "occurred",
            "sentiment": "neutral",
        }
        assert _facets(
            _one(db, "Acme Hunch", "view"),
            "view_type",
            "stance",
            "sentiment",
            "support_strength",
            "conviction",
        ) == {
            "view_type": "analyst_report",
            "stance": "neutral",
            "sentiment": "neutral",
            "support_strength": "moderate",
            "conviction": "medium",
        }
        # Unknown sentiment is treated as missing, so the stance-derived value applies.
        assert _one(db, "Acme Bear Case", "view").facets["sentiment"] == "negative"
        assert _one(db, "Warehouse Automation", "theme").facets["stage"] == "accelerating"


def test_retired_consensus_view_is_stored_as_superseded(tmp_path: Path) -> None:
    extraction = ExtractionResult(
        entities=[ExtractedEntity(temp_id="e_acme", name="Acme Robotics", summary="Robots.", entity_type="company")],
        events=[
            ExtractedEvent(temp_id="ev1", name="Acme Order", summary="Big order.", event_type="news", event_date="2026-11-21")
        ],
        edges=[ExtractedEdge(from_ref="ev1", to_ref="e_acme", relation="ABOUT")],
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    note = data_dir / "2026-11-21_note.md"
    note.write_text("Acme order.", encoding="utf-8")
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, _VocabFakeLLM(extraction), data_dir)
        assert pipeline.run().errors == []
        acme = _one(db, "Acme Robotics", "entity")
        cons = db.get_entity_consensus(acme.id)
        assert cons is not None

        note.unlink()
        assert pipeline.run().files_deleted == 1
        retired = db.get_node(cons.id)
        assert retired is not None
        assert retired.facets["status"] == "superseded"


# ---------------------------------------------------------------------------
# Relation write boundary
# ---------------------------------------------------------------------------


def _plain_entity(node_id: str, name: str, entity_type: str = "company") -> Node:
    return Node(id=node_id, node_type="entity", name=name, summary=f"{name}.", facets={"entity_type": entity_type})


def test_upsert_edge_and_update_edge_store_normalize_relation_name_output(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(_plain_entity("ent_a", "Acme"), embedding=_embed("a"))
        db.upsert_node(_plain_entity("ent_b", "Beta"), embedding=_embed("b"))
        db.upsert_node(_plain_entity("ent_j", "Jane", "person"), embedding=_embed("j"))

        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation=" supplies--to ", source_doc_id=None))
        db.upsert_edge(Edge(id="e2", from_id="ent_j", to_id="ent_a", relation="placeholder", source_doc_id=None))
        db.update_edge("e2", relation="works-at", from_id="ent_j", to_id="ent_a", facets={})

        stored = {
            str(r["id"]): str(r["relation"])
            for r in db.conn.execute("SELECT id, relation FROM edges").fetchall()
        }
        assert stored["e1"] == normalize_relation_name(" supplies--to ") == "SUPPLIES_TO"
        assert stored["e2"] == normalize_relation_name("works-at") == "WORKS_AT"


# ---------------------------------------------------------------------------
# Repair of legacy rows + audit reporting
# ---------------------------------------------------------------------------


def _force_facets(db: OntologyDB, node_id: str, facets: dict[str, Any]) -> None:
    """Simulate a legacy row written before write-time coercion existed."""
    with db.transaction():
        db.conn.execute("UPDATE nodes SET facets_json = ? WHERE id = ?", (json.dumps(facets), node_id))


def _force_edge_facets(db: OntologyDB, edge_id: str, facets: dict[str, Any]) -> None:
    with db.transaction():
        db.conn.execute("UPDATE edges SET facets_json = ? WHERE id = ?", (json.dumps(facets), edge_id))


def _seed_legacy(db: OntologyDB) -> None:
    db.upsert_ingestion_log("notes/legacy.md", "doc_legacy", "hash_legacy", datetime.now(UTC).isoformat())
    nodes = [
        Node(id="ent_acme", node_type="entity", name="Acme Robotics", summary="Robots."),
        Node(id="evt_1", node_type="event", name="Acme Rumor", summary="Rumor.", source_doc_id="doc_legacy"),
        Node(id="vw_1", node_type="view", name="Acme Desk View", summary="Desk.", source_doc_id="doc_legacy"),
        Node(id="vw_cons_acme", node_type="view", name="Consensus: Buy Acme", summary="Consensus."),
        Node(id="thm_1", node_type="theme", name="Warehouse Automation", summary="Robots."),
        Node(id="vw_odd", node_type="view", name="Acme Odd View", summary="Odd.", source_doc_id="doc_legacy"),
    ]
    for i, node in enumerate(nodes):
        db.upsert_node(node, embedding=_embed(str(i)))
    db.upsert_edge(Edge(id="e_about", from_id="evt_1", to_id="ent_acme", relation="ABOUT", source_doc_id="doc_legacy"))
    _force_facets(db, "ent_acme", {"entity_type": "Company", "ticker": "ACME"})
    _force_facets(db, "evt_1", {"event_type": "News", "status": "Rumored", "sentiment": "Negative"})
    _force_facets(
        db,
        "vw_1",
        {
            "view_type": "Analyst_Report",
            "stance": "Bullish",
            "sentiment": "Positive",
            "support_strength": "Strong",
            "conviction": "High",
        },
    )
    _force_facets(
        db,
        "vw_cons_acme",
        {"view_type": "consensus", "stance": "buy", "sentiment": "positive", "status": "stale"},
    )
    _force_facets(db, "thm_1", {"stage": "Emerging"})
    _force_facets(db, "vw_odd", {"view_type": "pm_view", "stance": "Moonshot", "sentiment": "neutral"})
    _force_edge_facets(db, "e_about", {"sentiment": "Negative"})


def test_repair_canonicalizes_legacy_enum_facets_and_is_idempotent(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed_legacy(db)
        first = repair_ontology(db, create_minimal_registry())
        assert first.total_changes > 0

        def node(node_id: str) -> Node:
            found = db.get_node(node_id)
            assert found is not None
            return found

        assert node("ent_acme").facets["entity_type"] == "company"
        assert _facets(node("evt_1"), "event_type", "status", "sentiment") == {
            "event_type": "news",
            "status": "rumored",
            "sentiment": "negative",
        }
        assert _facets(node("vw_1"), "view_type", "stance", "sentiment", "support_strength", "conviction") == {
            "view_type": "analyst_report",
            "stance": "bullish",
            "sentiment": "positive",
            "support_strength": "strong",
            "conviction": "high",
        }
        assert node("vw_cons_acme").facets["status"] == "superseded"
        assert node("thm_1").facets["stage"] == "emerging"
        edge_facets = json.loads(
            db.conn.execute("SELECT facets_json FROM edges WHERE id = 'e_about'").fetchone()[0]
        )
        assert edge_facets["sentiment"] == "negative"

        second = repair_ontology(db, create_minimal_registry())
        assert second.total_changes == 0


def test_repair_lowercases_but_keeps_out_of_vocabulary_value_and_audit_reports_it(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed_legacy(db)
        repair_ontology(db, create_minimal_registry())
        odd = db.get_node("vw_odd")
        assert odd is not None
        # Repair never maps an unknown legacy value to the ingest fallback.
        assert odd.facets["stance"] == "moonshot"
        audit_dump = run_ontology_audit(db, create_minimal_registry()).model_dump_json()
        assert "moonshot" in audit_dump.casefold()


# ---------------------------------------------------------------------------
# Agent vs web signal filter parity
# ---------------------------------------------------------------------------


def _seed_signals(db: OntologyDB) -> None:
    nodes = [
        Node(id="ent_acme", node_type="entity", name="Acme Robotics", summary="Robots.", facets={"entity_type": "company"}),
        Node(id="evt_news", node_type="event", name="Acme News", summary=".", facets={"event_type": "news", "status": "occurred", "sentiment": "positive", "event_date": "2026-11-01"}),
        Node(id="evt_rum", node_type="event", name="Acme Rumored", summary=".", facets={"event_type": "news", "status": "rumored", "sentiment": "neutral", "event_date": "2026-11-02"}),
        Node(id="evt_fact", node_type="event", name="Acme Fact", summary=".", facets={"event_type": "fact", "status": "occurred", "event_date": "2026-11-03"}),
        Node(id="evt_cat", node_type="event", name="Acme Catalyst", summary=".", facets={"event_type": "catalyst", "status": "upcoming", "sentiment": "mixed", "event_date": "2026-11-04"}),
        Node(id="vw_rum", node_type="view", name="Acme Rumor View", summary=".", facets={"view_type": "rumor", "stance": "bearish", "as_of": "2026-11-05"}),
        Node(id="vw_ar", node_type="view", name="Acme Analyst", summary=".", facets={"view_type": "analyst_report", "stance": "buy", "sentiment": "mixed", "as_of": "2026-11-06"}),
        Node(id="vw_pm", node_type="view", name="Acme PM", summary=".", facets={"view_type": "pm_view", "stance": "hold", "as_of": "2026-11-07"}),
        Node(id="vw_cc", node_type="view", name="Acme Channel", summary=".", facets={"view_type": "channel_check", "stance": "neutral", "sentiment": "neutral", "as_of": "2026-11-08"}),
    ]
    for i, node in enumerate(nodes):
        db.upsert_node(node, embedding=_embed(str(i)))
    edges = [
        ("evt_news", {}),
        ("evt_rum", {"sentiment": "negative"}),
        ("evt_fact", {}),
        ("evt_cat", {"sentiment": "positive"}),
        ("vw_rum", {}),
        ("vw_ar", {}),
        ("vw_pm", {"sentiment": "positive"}),
        ("vw_cc", {}),
    ]
    for nid, facets in edges:
        db.upsert_edge(Edge(id=f"e_{nid}", from_id=nid, to_id="ent_acme", relation="ABOUT", facets=facets))


def test_agent_and_web_signal_filters_return_identical_items(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed_signals(db)
        sentiments = [None, "positive", "negative", "neutral", "mixed", "unclassified", "Unknown", " NONE "]
        categories = [None, "rumor", "Rumors", "news", "fact", "Facts", "catalyst", "analyst_report", "Analyst Reports", "pm_view", "channel_check", "earnings"]
        mismatches = []
        for sent in sentiments:
            for cat in categories:
                agent = db.query_entity_signals(
                    "ent_acme",
                    sentiments=[sent] if sent is not None else None,
                    categories=[cat] if cat is not None else None,
                )
                agent_ids = {item["id"] for item in agent["items"]}
                web = search_ontology(
                    db,
                    None,
                    "",
                    filters=SearchFilters.from_raw(entity_id="ent_acme", subtype=cat, sentiment=sent),
                    limit=500,
                )
                web_ids = {h.node.id for h in web.signals}
                if agent_ids != web_ids:
                    mismatches.append((sent, cat, sorted(agent_ids), sorted(web_ids)))
        assert mismatches == []
        # Sanity: the grid exercises non-empty matches for the rumor rule.
        rumor = db.query_entity_signals("ent_acme", categories=["rumor"])
        assert {i["id"] for i in rumor["items"]} == {"evt_rum", "vw_rum"}
