"""Per-relation facets, endpoint rules, money magnitudes, and the removed `product` entity type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stock_ontology.audit import run_ontology_audit
from stock_ontology.db import OntologyDB
from stock_ontology.llm.prompts import EXTRACTION_SYSTEM_PROMPT
from stock_ontology.models import Edge, ExtractionResult, Node
from stock_ontology.pipeline import IngestionPipeline
from stock_ontology.registry import FacetSchemaError, load_registry, save_registry
from stock_ontology.repair import repair_ontology
from stock_ontology.vocab import ENTITY_TYPE, coerce_facet_value
from test_db import insert_legacy_edge

DIM = 8
SHIPPED = Path(__file__).resolve().parents[1] / "ontology_registry.json"


def _company(node_id: str) -> Node:
    return Node(id=node_id, node_type="entity", name=node_id, summary="c", facets={"entity_type": "company", "sector": "Tech"})


def _theme(node_id: str) -> Node:
    return Node(id=node_id, node_type="theme", name=node_id, summary="t", facets={"stage": "emerging"})


def _person(node_id: str) -> Node:
    facets = {"entity_type": "person", "role": "CEO", "organization": "Acme"}
    return Node(id=node_id, node_type="entity", name=node_id, summary="p", facets=facets)


class _FakeLLM:
    def __init__(self, edges: list[dict[str, Any]]) -> None:
        self.edges = edges
        self.calls = 0

    def format_chain_summary(self) -> str:
        return "fake"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        self.calls += 1
        return ExtractionResult.model_validate(
            {
                "entities": [
                    {"temp_id": "c1", "name": "Acme", "summary": "c", "entity_type": "company",
                     "facets": [{"key": "sector", "value": "Tech"}]},
                    {"temp_id": "p1", "name": "Jo Lee", "summary": "p", "entity_type": "person",
                     "facets": [{"key": "role", "value": "CEO"}, {"key": "organization", "value": "Acme"}]},
                ],
                "themes": [{"temp_id": "t1", "name": "AI Capex", "summary": "t", "stage": "emerging"}],
                "edges": self.edges,
            }
        )


def _ingest(tmp_path: Path, llm: _FakeLLM, registry: Any) -> tuple[Path, Any]:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "note.md").write_text("Acme note.", encoding="utf-8")
    db_path = tmp_path / "o.db"
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        report = IngestionPipeline(db, llm, data, registry=registry).run()
    return db_path, report


def _edited_registry(tmp_path: Path, edit: Any) -> Any:
    raw = json.loads(SHIPPED.read_text(encoding="utf-8"))
    edit(raw)
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_registry(path)


def test_exposed_to_requires_sentiment_only_on_that_relation(tmp_path: Path) -> None:
    reg = load_registry(SHIPPED)
    assert reg.relation_required_facets() == {"EXPOSED_TO": ["sentiment"]}
    with OntologyDB(tmp_path / "t.db", embedding_dim=DIM, registry=reg) as db:
        db.upsert_node(_company("c"))
        db.upsert_node(_company("d"))
        db.upsert_node(_theme("t"))
        with pytest.raises(FacetSchemaError):
            db.upsert_edge(Edge(id="e1", from_id="c", to_id="t", relation="EXPOSED_TO", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e2", from_id="c", to_id="t", relation="EXPOSED_TO", facets={"basis": "extracted", "sentiment": "positive"}))
        db.upsert_edge(Edge(id="e3", from_id="c", to_id="d", relation="COMPETE", facets={"basis": "extracted"}))


def test_relation_layer_types_only_its_own_relation(tmp_path: Path) -> None:
    reg = load_registry(SHIPPED)
    with OntologyDB(tmp_path / "t.db", embedding_dim=DIM, registry=reg) as db:
        db.upsert_node(_company("c"))
        db.upsert_node(_company("d"))
        with pytest.raises(FacetSchemaError):
            db.upsert_edge(Edge(id="e1", from_id="c", to_id="d", relation="BUY", facets={"basis": "extracted", "confidence": "certain"}))
        with pytest.raises(FacetSchemaError):
            db.upsert_edge(Edge(id="e2", from_id="c", to_id="d", relation="OWNS", facets={"basis": "extracted", "transaction_value": "$1.45B"}))
        db.upsert_edge(Edge(id="e3", from_id="c", to_id="d", relation="OWNS", facets={"basis": "extracted", "transaction_value": "USD 1.45B"}))
        # `confidence` is undeclared on COMPETE, so it stays free-form there.
        db.upsert_edge(Edge(id="e4", from_id="c", to_id="d", relation="COMPETE", facets={"basis": "extracted", "confidence": "certain"}))
        row = db.conn.execute("SELECT facets_json FROM edges WHERE id = 'e3'").fetchone()
    assert json.loads(row[0])["transaction_value"] == {"amount": 1450000000, "currency": "USD"}


def test_registry_refuses_a_relation_layer_for_an_unknown_relation(tmp_path: Path) -> None:
    def edit(raw: dict) -> None:
        raw["facet_schema"]["relation"]["FROBNICATES"] = {"x": {"kind": "text", "required": False}}

    with pytest.raises(ValueError, match="FROBNICATES"):
        _edited_registry(tmp_path, edit)


def test_write_boundary_refuses_endpoints_the_relation_does_not_allow(tmp_path: Path) -> None:
    reg = load_registry(SHIPPED)
    with OntologyDB(tmp_path / "t.db", embedding_dim=DIM, registry=reg) as db:
        db.upsert_node(_company("c"))
        db.upsert_node(_theme("t"))
        db.upsert_node(_person("p"))
        with pytest.raises(FacetSchemaError):
            db.upsert_edge(Edge(id="e1", from_id="c", to_id="p", relation="WORKS_AT", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e2", from_id="p", to_id="c", relation="WORKS_AT", facets={"basis": "extracted"}))
        with pytest.raises(FacetSchemaError):
            db.update_edge("e2", relation="WORKS_AT", from_id="p", to_id="t", facets={"basis": "extracted"})


def test_symmetric_relation_accepts_allowed_types_in_either_stored_order(tmp_path: Path) -> None:
    def allow(raw: dict) -> None:
        spec = next(r for r in raw["relations"] if r["name"] == "COMPETE")
        spec["from_types"] = ["theme"]
        spec["to_types"] = ["entity:company"]

    reg = _edited_registry(tmp_path, allow)
    with OntologyDB(tmp_path / "t.db", embedding_dim=DIM, registry=reg) as db:
        db.upsert_node(_company("a_company"))
        db.upsert_node(_theme("z_theme"))
        db.upsert_edge(Edge(id="e", from_id="a_company", to_id="z_theme", relation="COMPETE", facets={"basis": "extracted"}))


def test_endpoint_violation_is_held_reported_and_promoted_once_allowed(tmp_path: Path) -> None:
    reg = load_registry(SHIPPED)
    llm = _FakeLLM([{"from_ref": "t1", "to_ref": "p1", "relation": "COMPETE"}])
    db_path, report = _ingest(tmp_path, llm, reg)
    assert report.errors == [] and report.unmapped_relations_pending == {"COMPETE": 1} and llm.calls == 1

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
        audit = run_ontology_audit(db, reg)
    assert audit.summary.pending_endpoint_edges == 1
    issue = audit.pending_endpoint_issues[0]
    # COMPETE is symmetric, so the stored direction follows the node ids.
    assert (issue.relation, {issue.from_type, issue.to_type}, issue.count) == ("COMPETE", {"theme", "entity:person"}, 1)
    assert audit.unmapped_relations == []

    with OntologyDB(db_path, embedding_dim=DIM) as db:
        assert repair_ontology(db, reg).pending_edges_promoted == 0
        assert db.conn.execute("SELECT COUNT(*) FROM pending_edges").fetchone()[0] == 1

    def allow(raw: dict) -> None:
        spec = next(r for r in raw["relations"] if r["name"] == "COMPETE")
        spec["from_types"].append("theme")
        spec["to_types"].append("entity:person")

    allowed = _edited_registry(tmp_path, allow)
    with OntologyDB(db_path, embedding_dim=DIM) as db:
        assert repair_ontology(db, allowed).pending_edges_promoted == 1
        assert db.conn.execute("SELECT COUNT(*) FROM pending_edges").fetchone()[0] == 0
        assert [r[0] for r in db.conn.execute("SELECT relation FROM edges")] == ["COMPETE"]


def test_cli_adoption_promotes_a_relation_in_a_published_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import stock_ontology.cli as cli_module

    reg = load_registry(SHIPPED)
    llm = _FakeLLM([{"from_ref": "p1", "to_ref": "c1", "relation": "MENTORS"}])
    db_path, _ = _ingest(tmp_path, llm, reg)

    def approve(raw: dict) -> None:
        raw["version"] += 1
        raw["relations"].append(
            {"name": "MENTORS", "description": "Mentorship.", "from_types": ["entity:person"],
             "to_types": ["entity:company"], "aliases": [], "inverse_aliases": [], "alias_facets": {},
             "symmetric": False, "traversal_group": "core"}
        )

    _edited_registry(tmp_path, approve)
    official = tmp_path / "official.json"
    save_registry(reg, official)
    monkeypatch.setenv("EMBEDDING_DIM", str(DIM))
    monkeypatch.setenv("ONTOLOGY_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    options = ["--db", str(db_path), "--registry", str(official)]
    bootstrap = runner.invoke(cli_module.app, ["registry-apply", *options], input="y\n")
    assert bootstrap.exit_code == 0, bootstrap.output
    publish = runner.invoke(
        cli_module.app, ["registry-publish", str(tmp_path / "edited.json"), *options], input="y\n"
    )
    assert publish.exit_code == 0, publish.output
    result = runner.invoke(cli_module.app, ["registry-apply", *options], input="y\n")
    assert result.exit_code == 0, result.output
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        assert [r[0] for r in db.conn.execute("SELECT relation FROM edges")] == ["MENTORS"]


def test_ingest_regenerates_when_exposed_to_has_no_sentiment(tmp_path: Path) -> None:
    llm = _FakeLLM([{"from_ref": "c1", "to_ref": "t1", "relation": "EXPOSED_TO"}])
    _, report = _ingest(tmp_path, llm, load_registry(SHIPPED))
    assert llm.calls == 3
    assert [path for path, _ in report.errors] == ["note.md"]


def test_extraction_catalog_lists_required_edge_facets(tmp_path: Path) -> None:
    reg = load_registry(SHIPPED)
    (tmp_path / "data").mkdir()
    with OntologyDB(tmp_path / "o.db", embedding_dim=DIM, registry=reg) as db:
        catalog = IngestionPipeline(db, _FakeLLM([]), tmp_path / "data", registry=reg)._build_existing_catalog()
    assert "Required edge facets" in catalog and "- EXPOSED_TO: sentiment" in catalog


@pytest.mark.parametrize(
    ("raw", "amount"),
    [("USD 1.45B", 1_450_000_000), ("US$2.5M", 2_500_000), ("EUR 3K", 3_000), ("USD 1T", 1_000_000_000_000)],
)
def test_money_parses_magnitudes_exactly(raw: str, amount: int) -> None:
    value = coerce_facet_value("money", raw)["amount"]
    assert value == amount and isinstance(value, int)


def test_repair_migrates_edge_money_from_its_source_note(tmp_path: Path) -> None:
    reg = load_registry(SHIPPED)
    data = tmp_path / "data"
    data.mkdir()
    (data / "note.md").write_text("Acme bought Beta for $1.45B.", encoding="utf-8")
    with OntologyDB(tmp_path / "o.db", embedding_dim=DIM) as db:
        db.upsert_node(_company("a"))
        db.upsert_node(_company("b"))
        db.upsert_ingestion_log("note.md", "doc_1", "hash", "2026-01-01")
        insert_legacy_edge(
            db,
            Edge(id="e", from_id="a", to_id="b", relation="OWNS", source_doc_id="doc_1",
                 facets={"basis": "extracted", "transaction_value": "$1.45B"}),
        )
        report = repair_ontology(db, reg, data_dir=data)
        row = db.conn.execute("SELECT facets_json FROM edges WHERE id = 'e'").fetchone()
    assert (report.money_facets_migrated, report.money_facets_unresolved) == (1, 0)
    assert json.loads(row[0])["transaction_value"] == {"amount": 1450000000, "currency": "USD"}


def test_product_is_no_longer_an_entity_type(tmp_path: Path) -> None:
    assert "product" not in ENTITY_TYPE.members
    assert "Product/Tech" not in EXTRACTION_SYSTEM_PROMPT
    assert "Do not extract products" in EXTRACTION_SYSTEM_PROMPT
    reg = load_registry(SHIPPED)
    with OntologyDB(tmp_path / "t.db", embedding_dim=DIM, registry=reg) as db, pytest.raises(FacetSchemaError):
        db.upsert_node(Node(id="x", node_type="entity", name="x", summary="x", facets={"entity_type": "product"}))
