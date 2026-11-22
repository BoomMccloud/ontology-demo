"""Offline tests for `stock_ontology.repair.repair_ontology` over temporary databases."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, Node
from stock_ontology.registry import create_minimal_registry

DIM = 8


def _load_repair_ontology() -> Callable[..., Any]:
    try:
        module = importlib.import_module("stock_ontology.repair")
    except ModuleNotFoundError:
        pytest.fail("stock_ontology.repair.repair_ontology is missing: repair behavior not implemented")
    fn = getattr(module, "repair_ontology", None)
    assert callable(fn), "stock_ontology.repair has no callable repair_ontology"
    return fn


def _vec(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[idx % DIM] = 1.0
    return v


def _entity(node_id: str, name: str, entity_type: str, aliases: list[str] | None = None) -> Node:
    return Node(
        id=node_id,
        node_type="entity",
        name=name,
        summary=f"{name} summary.",
        aliases=aliases or [],
        facets={"entity_type": entity_type},
    )


def _event(node_id: str, name: str, doc_id: str) -> Node:
    return Node(id=node_id, node_type="event", name=name, summary=f"{name}.", source_doc_id=doc_id)


def _edge(edge_id: str, from_id: str, relation: str, to_id: str, doc_id: str | None) -> Edge:
    return Edge(id=edge_id, from_id=from_id, to_id=to_id, relation=relation, source_doc_id=doc_id)


def _seed(db: OntologyDB) -> None:
    for i, node in enumerate(
        [
            _entity("ent_acme", "Acme Robotics", "company"),
            _entity("ent_beta", "Beta Motion", "company"),
            _entity("ent_jane", "Jane Roe", "person"),
            _event("evt_live", "Live Event", "doc_live"),
            _event("evt_orphan", "Orphan Event", "doc_orphan"),
        ]
    ):
        db.upsert_node(node, embedding=_vec(i))
    db.upsert_ingestion_log("notes/live.md", "doc_live", "hash_live", datetime.now(UTC).isoformat())
    for edge in [
        _edge("e_live_about", "evt_live", "ABOUT", "ent_acme", "doc_live"),
        _edge("e_orphan_about", "evt_orphan", "ABOUT", "ent_beta", "doc_orphan"),
        _edge("e_partner", "ent_acme", "COMPETES_WITH", "ent_beta", "doc_live"),
        _edge("e_employee", "ent_acme", "HAS_EMPLOYEE", "ent_jane", "doc_live"),
    ]:
        db.upsert_edge(edge)


def _edges(db: OntologyDB) -> set[tuple[str, str, str]]:
    return {
        (r["from_id"], r["relation"], r["to_id"])
        for r in db.conn.execute("SELECT from_id, relation, to_id FROM edges").fetchall()
    }


def _has_vector(db: OntologyDB, node_id: str) -> bool:
    row = db.conn.execute("SELECT COUNT(*) FROM node_vectors WHERE node_id = ?", (node_id,)).fetchone()
    return int(row[0]) > 0


def _snapshot(db: OntologyDB) -> tuple[Any, ...]:
    nodes = sorted(
        tuple(r) for r in db.conn.execute(
            "SELECT id, node_type, name, aliases_json, facets_json, source_doc_id FROM nodes"
        ).fetchall()
    )
    edges = sorted(
        tuple(r) for r in db.conn.execute(
            "SELECT from_id, to_id, relation, facets_json, source_doc_id FROM edges"
        ).fetchall()
    )
    vectors = sorted(r[0] for r in db.conn.execute("SELECT node_id FROM node_vectors").fetchall())
    return nodes, edges, vectors


def test_repair_removes_orphan_artifacts_and_canonicalizes_edges(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed(db)
        assert ("ent_acme", "COMPETES_WITH", "ent_beta") in _edges(db)
        repair_ontology = _load_repair_ontology()
        repair_ontology(db, create_minimal_registry())

        # Orphan doc (no ingestion log entry): its node, vector, and edges are gone.
        assert db.get_node("evt_orphan") is None
        assert not _has_vector(db, "evt_orphan")
        assert db.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_doc_id = 'doc_orphan'"
        ).fetchone()[0] == 0
        # Logged doc artifacts and canonical entities are kept.
        assert db.get_node("evt_live") is not None
        assert db.get_node("ent_beta") is not None

        edges = _edges(db)
        assert ("evt_live", "ABOUT", "ent_acme") in edges
        assert ("ent_acme", "COMPETE", "ent_beta") in edges
        assert ("ent_jane", "WORKS_AT", "ent_acme") in edges
        assert {rel for _, rel, _ in edges}.isdisjoint({"COMPETES_WITH", "HAS_EMPLOYEE"})


def test_repair_merges_exact_duplicates_within_same_type_only(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(_entity("ent_gamma_a", "Gamma Labs", "company", ["GML"]), embedding=_vec(0))
        db.upsert_node(_entity("ent_gamma_b", "gamma labs", "company", ["Gamma Laboratories"]), embedding=_vec(1))
        db.upsert_node(_entity("ent_gamma_person", "Gamma Labs", "person"), embedding=_vec(2))
        db.upsert_node(_event("evt_g", "Gamma Event", "doc_g"), embedding=_vec(3))
        db.upsert_ingestion_log("notes/g.md", "doc_g", "hash_g", datetime.now(UTC).isoformat())
        db.upsert_edge(_edge("e_g_a", "evt_g", "ABOUT", "ent_gamma_a", "doc_g"))
        db.upsert_edge(_edge("e_g_b", "evt_g", "MENTIONS", "ent_gamma_b", "doc_g"))

        repair_ontology = _load_repair_ontology()
        repair_ontology(db, create_minimal_registry())

        companies = [
            n for n in db.list_all_nodes()
            if n.node_type == "entity" and n.facets.get("entity_type") == "company"
        ]
        assert len(companies) == 1
        survivor = companies[0]
        loser = ({"ent_gamma_a", "ent_gamma_b"} - {survivor.id}).pop()
        assert db.get_node(loser) is None
        assert not _has_vector(db, loser)
        assert {"GML", "Gamma Laboratories"} <= set(survivor.aliases)
        # Edges are repointed to the survivor, not dropped.
        assert {("evt_g", "ABOUT", survivor.id), ("evt_g", "MENTIONS", survivor.id)} <= _edges(db)
        # A same-named entity of a different entity_type is not merged.
        assert db.get_node("ent_gamma_person") is not None


def test_repair_is_idempotent(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed(db)
        repair_ontology = _load_repair_ontology()
        registry = create_minimal_registry()
        repair_ontology(db, registry)
        after_first = _snapshot(db)
        repair_ontology(db, registry)
        assert _snapshot(db) == after_first


# ---------------------------------------------------------------------------
# Ingestion follow-ups: self-loop counts, merged survivors, re-embedding
# ---------------------------------------------------------------------------


def _seed_duplicates_with_cross_edge(db: OntologyDB) -> None:
    """Two exact-duplicate companies joined by an edge that becomes a self-loop after merge."""
    db.upsert_node(_entity("ent_delta_a", "Delta Power", "company", ["DPW"]), embedding=_vec(0))
    db.upsert_node(_entity("ent_delta_b", "delta power", "company", ["Delta Power Systems"]), embedding=_vec(1))
    db.upsert_edge(_edge("e_delta_loop", "ent_delta_a", "SUPPLIES_TO", "ent_delta_b", None))


def test_repair_counts_self_loops_and_lists_merged_survivors(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed_duplicates_with_cross_edge(db)
        report = _load_repair_ontology()(db, create_minimal_registry())

        survivors = [n.id for n in db.list_all_nodes() if n.node_type == "entity"]
        assert len(survivors) == 1
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
        assert report.nodes_merged == 1

        assert getattr(report, "self_loops_deleted", None) == 1, (
            "repair deleted a self-loop edge but did not count it"
        )
        assert getattr(report, "merged_survivor_ids", None) == survivors, (
            "repair does not report the IDs of merged survivors"
        )
        assert report.total_changes == 2


class _RepairEmbedLLM:
    def __init__(self) -> None:
        self.seen_texts: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.seen_texts.extend(texts)
        out = []
        for text in texts:
            v = [0.0] * DIM
            v[(len(text) % (DIM - 2)) + 2] = 1.0
            out.append(v)
        return out


def _load_reembed_nodes() -> Callable[..., Any] | None:
    for module_name in ("stock_ontology.repair", "stock_ontology.pipeline"):
        fn = getattr(importlib.import_module(module_name), "reembed_nodes", None)
        if callable(fn):
            return fn
    return None


def test_reembed_gives_merged_survivor_a_fresh_embedding(tmp_path: Path) -> None:
    from stock_ontology.pipeline import node_embedding_text

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        _seed_duplicates_with_cross_edge(db)
        report = _load_repair_ontology()(db, create_minimal_registry())
        survivor_id = next(n.id for n in db.list_all_nodes() if n.node_type == "entity")
        stale = db.get_node_embeddings([survivor_id])[survivor_id]

        reembed_nodes = _load_reembed_nodes()
        assert reembed_nodes is not None, (
            "no reembed_nodes(db, llm, node_ids) to recompute merged survivors' embeddings"
        )
        llm = _RepairEmbedLLM()
        reembed_nodes(db, llm, getattr(report, "merged_survivor_ids", [survivor_id]))

        survivor = db.get_node(survivor_id)
        assert survivor is not None
        expected_text = node_embedding_text(survivor)
        # The fresh text includes the loser's labels unioned into the survivor.
        assert "Delta Power Systems" in expected_text
        assert expected_text in llm.seen_texts
        fresh = db.get_node_embeddings([survivor_id])[survivor_id]
        assert fresh == pytest.approx(llm.embed_texts([expected_text])[0])
        assert fresh != pytest.approx(stale)
