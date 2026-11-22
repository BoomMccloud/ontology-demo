"""Builder unit tests for official-edge-facets: load-check drift, audit key report, repair counter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_ontology.audit import run_ontology_audit
from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, Node
from stock_ontology.registry import create_minimal_registry, load_registry
from stock_ontology.repair import repair_ontology

SHIPPED_REGISTRY = Path(__file__).resolve().parents[1] / "ontology_registry.json"
DIM = 8


def _write_mutated(tmp_path: Path, mutate) -> Path:
    raw = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    mutate(raw["facet_vocabularies"])
    path = tmp_path / "ontology_registry.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("mutate", "named"),
    [
        (lambda fv: fv["node"]["view"]["stance"]["aliases"].update({"moonshot": "buy"}), "aliases"),
        (lambda fv: fv["node"]["entity"]["entity_type"].update({"fallback": "person"}), "fallback"),
        (lambda fv: fv["edge"]["basis"]["members"].update({"extracted": "Something else."}), "'extracted'"),
        (lambda fv: fv["edge"].pop("basis"), "edge.basis"),
        (lambda fv: fv["node"].update({"widget": {}}), "node.widget"),
    ],
    ids=["alias-drift", "fallback-drift", "definition-drift", "missing-vocab", "extra-node-type"],
)
def test_load_registry_rejects_alias_fallback_definition_and_shape_drift(tmp_path: Path, mutate, named) -> None:
    path = _write_mutated(tmp_path, mutate)
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    assert named in str(excinfo.value)


def test_registry_without_facet_vocabularies_gets_codes_copy() -> None:
    raw = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    raw.pop("facet_vocabularies")
    from stock_ontology.registry import OntologyRegistry

    reg = OntologyRegistry.model_validate(raw)
    assert reg.facet_vocabularies == create_minimal_registry().facet_vocabularies


def _seed(db: OntologyDB) -> None:
    for i, node in enumerate(
        [
            Node(id="ent_a", node_type="entity", name="A", summary="a", facets={"entity_type": "person"}),
            Node(id="ent_b", node_type="entity", name="B", summary="b", facets={"entity_type": "company"}),
        ]
    ):
        db.upsert_node(node, embedding=[1.0 if j == i else 0.0 for j in range(DIM)])
    db.upsert_edge(
        Edge(
            id="e1",
            from_id="ent_a",
            to_id="ent_b",
            relation="WORKS_AT",
            facets={"role": "CEO", "confidence": "high", "sentiment": "positive"},
        )
    )


def test_audit_reports_non_official_edge_facet_keys_without_failing(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        _seed(db)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        report = run_ontology_audit(db, create_minimal_registry())
    keys = {k.key: k.count for k in report.non_official_edge_facet_keys}
    assert keys == {"confidence": 1, "role": 1}
    assert report.summary.non_official_edge_facet_key_count == 2


def test_repair_counts_basis_backfill_in_total_changes(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "repair.db", embedding_dim=DIM, read_only=False) as db:
        _seed(db)
        db.conn.execute("UPDATE edges SET facets_json = json_remove(facets_json, '$.basis')")
        report = repair_ontology(db, create_minimal_registry())
        assert report.edge_basis_backfilled == 1
        assert report.total_changes == 1
        basis = db.conn.execute("SELECT json_extract(facets_json, '$.basis') FROM edges").fetchall()
        assert all(row[0] == "extracted" for row in basis)
