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


def test_registry_without_facet_vocabularies_is_refused_not_filled_from_code(tmp_path: Path) -> None:
    raw = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    raw.pop("facet_vocabularies")
    path = tmp_path / "ontology_registry.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    assert "facet_vocabularies" in str(excinfo.value)


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
            facets={"role": "CEO", "confidence": "high", "sentiment": "positive", "basis": "extracted"},
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


# ---------------------------------------------------------------------------
# typed-registry-schema: required facets, value kinds, regeneration, versioning
# ---------------------------------------------------------------------------

BASELINE_GRAPH = Path(__file__).resolve().parent / "fixtures" / "typed_registry_baseline_graph.json"
SAMPLE_DATA = Path(__file__).resolve().parent / "fixtures" / "sample_data"


def _shipped_registry():
    return load_registry(SHIPPED_REGISTRY)


def _view(facets: dict) -> Node:
    return Node(id="vw_x", node_type="view", name="X view", summary="x", facets=facets)


def _node_count(db: OntologyDB) -> int:
    return int(db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])


@pytest.mark.parametrize(
    "facets",
    [
        {"stance": "bullish", "as_of": "2026-10-15"},
        {"view_type": "analyst_report", "target_price": "about six hundred"},
    ],
    ids=["missing-view_type", "non-numeric-target_price"],
)
def test_upsert_node_refuses_missing_required_or_wrong_kind_facet(tmp_path: Path, facets: dict) -> None:
    with OntologyDB(tmp_path / "w.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        with pytest.raises(ValueError):
            db.upsert_node(_view(facets))
        assert _node_count(db) == 0


@pytest.mark.parametrize(
    "facets",
    [
        {"stance": "bullish", "as_of": "2026-10-15"},
        {"view_type": "analyst_report", "target_price": "about six hundred"},
    ],
    ids=["missing-view_type", "non-numeric-target_price"],
)
def test_default_db_without_registry_refuses_missing_required_or_wrong_kind_facet(
    tmp_path: Path, facets: dict
) -> None:
    with OntologyDB(tmp_path / "d.db", embedding_dim=DIM) as db:
        with pytest.raises(ValueError):
            db.upsert_node(_view(facets))
        assert _node_count(db) == 0


def test_upsert_edge_refuses_edge_without_basis(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "e.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        for nid in ("ent_a", "ent_b"):
            db.upsert_node(
                Node(
                    id=nid,
                    node_type="entity",
                    name=nid,
                    summary=nid,
                    facets={"entity_type": "company", "sector": "Semiconductors"},
                )
            )
        with pytest.raises(ValueError):
            db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="SUPPLIES_TO", facets={}))
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_conforming_view_with_free_form_facets_round_trips(tmp_path: Path) -> None:
    facets = {
        "view_type": "analyst_report",
        "target_price": {"amount": 630, "currency": "USD"},
        "as_of": "2026-10-15",
        "house_flavor": {"nested": ["a", 1]},
        "author": "Morgan Tech Research",
    }
    with OntologyDB(tmp_path / "r.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        db.upsert_node(_view(facets))
        stored = db.get_node("vw_x")
    assert stored is not None and stored.facets == facets


class _RegeneratingFakeLLM:
    """Omits `view_type` on the first `omit_times` extractions of a note, then supplies it."""

    def __init__(self, omit_times: int) -> None:
        self.omit_times = omit_times
        self.extract_calls: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [((ord(c) % 7) + 1.0) for c in (t + "x" * DIM)[:DIM]]
            norm = sum(v * v for v in vec) ** 0.5
            out.append([v / norm for v in vec])
        return out

    def extract_document(self, *, text, source_meta, existing_catalog, known_facets):
        from stock_ontology.models import ExtractionResult

        self.extract_calls.append(source_meta["file_path"])
        view = {"temp_id": "v1", "name": "Omega rumor", "summary": "Omega may slip a quarter.", "stance": "bearish"}
        if len(self.extract_calls) > self.omit_times:
            view["view_type"] = "rumor"
        # Parsed like a provider response: the raw payload simply has no `view_type` key.
        return ExtractionResult.model_validate(
            {
                "entities": [
                    {
                        "temp_id": "e1",
                        "name": "Omega Corp",
                        "summary": "Omega.",
                        "entity_type": "company",
                        "facets": [{"key": "sector", "value": "Semiconductors"}],
                    }
                ],
                "views": [view],
                "edges": [{"from_ref": "v1", "to_ref": "e1", "relation": "ABOUT"}],
            }
        )

    def synthesize_consensus(self, **kwargs):
        raise RuntimeError("consensus not under test")  # noqa: TRY003

    def generate_agent_reply(self, **kwargs):
        raise NotImplementedError


def _one_note(tmp_path: Path) -> tuple[Path, str]:
    data = tmp_path / "data"
    (data / "OMGA").mkdir(parents=True)
    rel = "OMGA/2026-11-20_rumor.md"
    (data / rel).write_text("Omega may slip a quarter.", encoding="utf-8")
    return data, rel


def test_ingest_regenerates_extraction_missing_required_view_type(tmp_path: Path) -> None:
    from stock_ontology.pipeline import IngestionPipeline

    data, rel = _one_note(tmp_path)
    llm = _RegeneratingFakeLLM(omit_times=1)
    reg = _shipped_registry()
    with OntologyDB(tmp_path / "o.db", embedding_dim=DIM, registry=reg) as db:
        IngestionPipeline(db, llm, data, registry=reg).run()
        assert llm.extract_calls == [rel, rel]
        assert rel in db.get_ingestion_log()
        views = [n for n in db.list_all_nodes() if n.node_type == "view"]
        assert [v.facets["view_type"] for v in views] == ["rumor"]


def test_ingest_fails_note_after_regeneration_cap(tmp_path: Path) -> None:
    from stock_ontology.pipeline import IngestionPipeline

    data, rel = _one_note(tmp_path)
    llm = _RegeneratingFakeLLM(omit_times=99)
    reg = _shipped_registry()
    with OntologyDB(tmp_path / "o.db", embedding_dim=DIM, registry=reg) as db:
        report = IngestionPipeline(db, llm, data, registry=reg).run()
        assert llm.extract_calls == [rel, rel, rel]
        assert [path for path, _ in report.errors] == [rel]
        assert rel not in db.get_ingestion_log()
        assert _node_count(db) == 0
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


class _DollarTargetFakeLLM(_RegeneratingFakeLLM):
    """Supplies `view_type` on every call, with a `target_price` facet that cannot be a number."""

    def __init__(self) -> None:
        super().__init__(omit_times=0)

    def extract_document(self, *, text, source_meta, existing_catalog, known_facets):
        from stock_ontology.models import ExtractionResult

        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult.model_validate(
            {
                "entities": [
                    {
                        "temp_id": "e1",
                        "name": "Omega Corp",
                        "summary": "Omega.",
                        "entity_type": "company",
                        "facets": [{"key": "sector", "value": "Semiconductors"}],
                    }
                ],
                "views": [
                    {
                        "temp_id": "v1",
                        "name": "Omega target",
                        "summary": "Omega is worth $650.",
                        "view_type": "analyst_report",
                        "stance": "bullish",
                        "facets": [
                            {"key": "target_price", "value": "$650"},
                            {"key": "author", "value": "Desk"},
                        ],
                    }
                ],
                "edges": [{"from_ref": "v1", "to_ref": "e1", "relation": "ABOUT"}],
            }
        )


def test_ingest_drops_uncoercible_optional_facet_and_keeps_note(tmp_path: Path) -> None:
    from stock_ontology.pipeline import IngestionPipeline

    data, rel = _one_note(tmp_path)
    llm = _DollarTargetFakeLLM()
    reg = _shipped_registry()
    with OntologyDB(tmp_path / "o.db", embedding_dim=DIM, registry=reg) as db:
        report = IngestionPipeline(db, llm, data, registry=reg).run()
        # A bad money value regenerates; still bad after the last attempt, only that facet is dropped.
        assert llm.extract_calls == [rel, rel, rel]
        assert report.invalid_facets_dropped == {"target_price": 1}
        # Consensus synthesis is not under test here; the note itself must not fail.
        assert [path for path, _ in report.errors if not path.startswith("consensus:")] == []
        assert rel in db.get_ingestion_log()
        views = [n for n in db.list_all_nodes() if n.node_type == "view"]
        assert len(views) == 1
        assert "target_price" not in views[0].facets
        assert views[0].facets["view_type"] == "analyst_report" and views[0].facets["author"] == "Desk"


def _seed_old_stamp(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, registry=_shipped_registry()) as db:
        db.conn.execute(
            "INSERT INTO nodes (id, node_type, name, summary, facets_json, created_at, updated_at) "
            "VALUES ('vw_old', 'view', 'Old', 'old', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            (json.dumps({"view_type": "analyst_report", "target_price": "USD 630"}),),
        )
        db.conn.commit()
        db.set_metadata("registry_version", "0")


def _stored_target_price(db: OntologyDB):
    row = db.conn.execute("SELECT facets_json FROM nodes WHERE id = 'vw_old'").fetchone()
    return json.loads(row[0])["target_price"]


def test_writable_open_migrates_rows_and_stamps_older_registry_version(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    _seed_old_stamp(db_path)
    reg = _shipped_registry()
    with OntologyDB(db_path, embedding_dim=DIM, registry=reg) as db:
        price = _stored_target_price(db)
        assert price == {"amount": 630, "currency": "USD"}
        assert db.get_metadata("registry_version") == reg.schema_stamp()


def test_read_only_open_of_old_or_unstamped_db_reads_without_writing(tmp_path: Path) -> None:
    for stamp in ("0", None):
        db_path = tmp_path / f"ro_{stamp}.db"
        _seed_old_stamp(db_path)
        if stamp is None:
            with OntologyDB(db_path, embedding_dim=DIM) as db:
                db.conn.execute("DELETE FROM db_metadata WHERE key = 'registry_version'")
                db.conn.commit()
        before = db_path.read_bytes()
        with OntologyDB(db_path, embedding_dim=DIM, read_only=True, registry=_shipped_registry()) as db:
            assert _stored_target_price(db) == "USD 630"
            assert db.get_metadata("registry_version") == stamp
            run_ontology_audit(db, _shipped_registry())
        assert db_path.read_bytes() == before


def _graph_snapshot(db: OntologyDB) -> dict:
    """Nodes and edges by `type:name`, so random ids and ingest timestamps do not count."""
    rows = db.conn.execute("SELECT id, node_type, name, facets_json FROM nodes").fetchall()
    label = {r["id"]: f"{r['node_type']}:{r['name']}" for r in rows}

    def scrub(value):
        if isinstance(value, dict):
            return {
                k: scrub(v) for k, v in sorted(value.items()) if not k.endswith("_at") and k != "doc_id"
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return label.get(value, value) if isinstance(value, str) else value

    nodes = sorted([label[r["id"]], scrub(json.loads(r["facets_json"]))] for r in rows)
    edges = sorted(
        [label[r["from_id"]], label[r["to_id"]], r["relation"], scrub(json.loads(r["facets_json"]))]
        for r in db.conn.execute("SELECT from_id, to_id, relation, facets_json FROM edges")
    )
    return {"nodes": nodes, "edges": edges}


def test_shipped_fixture_ingest_matches_baseline_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    from datetime import UTC, datetime

    import stock_ontology.pipeline as pipeline_module

    class _FrozenDatetime(datetime):
        """The baseline was captured on 2026-11-23; consensus `as_of` is the run date."""

        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 23, 12, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(pipeline_module, "datetime", _FrozenDatetime)

    from test_pipeline import DIM as PIPE_DIM
    from test_pipeline import FakePipelineLLM

    from stock_ontology.pipeline import IngestionPipeline

    data = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, data)
    with OntologyDB(tmp_path / "g.db", embedding_dim=PIPE_DIM) as db:
        report = IngestionPipeline(db, FakePipelineLLM(), data).run()
        assert report.errors == []
        snapshot = _graph_snapshot(db)
    assert snapshot == json.loads(BASELINE_GRAPH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# registry-schema-v2: per-entity-type specs, unmapped edges, schema-less refusal,
# optional enum membership, metadata length, schema-derived stamp
# ---------------------------------------------------------------------------


def _write_registry(tmp_path: Path, mutate, name: str = "ontology_registry.json") -> Path:
    """The shipped registry JSON with only `mutate(raw)` applied; no source is edited."""
    raw = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / name
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path


def _require_product_process_node(raw: dict) -> None:
    raw["facet_schema"]["node"].setdefault("entity:product", {})["process_node"] = {
        "kind": "text",
        "required": True,
    }


# Facets the shipped registry requires per entity type, so witness entities conform.
_CONFORMING = {
    "company": {"sector": "Semiconductors"},
    "person": {"role": "CEO", "organization": "Omega Corp"},
}


def _entity(nid: str, entity_type: str, **facets) -> Node:
    return Node(
        id=nid,
        node_type="entity",
        name=nid,
        summary=nid,
        facets={"entity_type": entity_type, **_CONFORMING.get(entity_type, {}), **facets},
    )


def test_entity_type_required_facet_is_a_registry_edit_enforced_on_write(tmp_path: Path) -> None:
    reg = load_registry(_write_registry(tmp_path, _require_product_process_node))
    with OntologyDB(tmp_path / "t.db", embedding_dim=DIM, registry=reg) as db:
        with pytest.raises(ValueError):
            db.upsert_node(_entity("ent_p1", "product"))
        assert _node_count(db) == 0
        db.upsert_node(_entity("ent_p2", "product", process_node="3nm"))
        db.upsert_node(_entity("ent_c1", "company"))
        assert {n.id for n in db.list_all_nodes()} == {"ent_p2", "ent_c1"}


def test_upsert_edge_refuses_relation_the_registry_does_not_map(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "u.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        db.upsert_node(_entity("ent_a", "company"))
        db.upsert_node(_entity("ent_b", "company"))
        with pytest.raises(ValueError):
            db.upsert_edge(
                Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="FROBNICATES", facets={"basis": "extracted"})
            )
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


class _ScriptedFakeLLM(_RegeneratingFakeLLM):
    """Returns one fixed extraction payload on every call."""

    def __init__(self, payload: dict) -> None:
        super().__init__(omit_times=0)
        self.payload = payload

    def extract_document(self, *, text, source_meta, existing_catalog, known_facets):
        from stock_ontology.models import ExtractionResult

        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult.model_validate(self.payload)


_OMEGA = {
    "temp_id": "e1",
    "name": "Omega Corp",
    "summary": "Omega.",
    "entity_type": "company",
    "facets": [{"key": "sector", "value": "Semiconductors"}],
}


def _ingest(tmp_path: Path, payload: dict):
    from stock_ontology.pipeline import IngestionPipeline

    data, rel = _one_note(tmp_path)
    llm = _ScriptedFakeLLM(payload)
    reg = _shipped_registry()
    db = OntologyDB(tmp_path / "o.db", embedding_dim=DIM, registry=reg)
    report = IngestionPipeline(db, llm, data, registry=reg).run()
    return db, report, rel


def _note_errors(report) -> list[str]:
    return [path for path, _ in report.errors if not path.startswith("consensus:")]


def test_ingest_skips_unmapped_edge_keeps_mapped_edge_and_note(tmp_path: Path) -> None:
    payload = {
        "entities": [_OMEGA],
        "views": [
            {"temp_id": "v1", "name": "Omega rumor", "summary": "Omega may slip.", "view_type": "rumor"}
        ],
        "edges": [
            {"from_ref": "v1", "to_ref": "e1", "relation": "ABOUT"},
            {"from_ref": "v1", "to_ref": "e1", "relation": "FROBNICATES"},
        ],
    }
    db, report, rel = _ingest(tmp_path, payload)
    with db:
        assert _note_errors(report) == []
        assert rel in db.get_ingestion_log()
        relations = [r[0] for r in db.conn.execute("SELECT relation FROM edges")]
        assert relations == ["ABOUT"]


def test_load_registry_refuses_registry_without_facet_schema(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, lambda raw: raw.pop("facet_schema"))
    with pytest.raises(ValueError) as excinfo:
        load_registry(path)
    assert "facet_schema" in str(excinfo.value)


def test_upsert_node_refuses_optional_enum_outside_vocabulary(tmp_path: Path) -> None:
    with OntologyDB(tmp_path / "s.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        with pytest.raises(ValueError):
            db.upsert_node(_view({"view_type": "rumor", "stance": "maybe"}))
        assert _node_count(db) == 0


def test_ingest_drops_optional_enum_outside_vocabulary_and_keeps_note(tmp_path: Path) -> None:
    payload = {
        "entities": [_OMEGA],
        "views": [
            {
                "temp_id": "v1",
                "name": "Omega rumor",
                "summary": "Omega may slip.",
                "view_type": "rumor",
                "facets": [{"key": "status", "value": "maybe"}, {"key": "author", "value": "Desk"}],
            }
        ],
        "edges": [{"from_ref": "v1", "to_ref": "e1", "relation": "ABOUT"}],
    }
    db, report, rel = _ingest(tmp_path, payload)
    with db:
        assert _note_errors(report) == []
        assert rel in db.get_ingestion_log()
        views = [n for n in db.list_all_nodes() if n.node_type == "view"]
        assert len(views) == 1
        assert "status" not in views[0].facets
        assert views[0].facets["author"] == "Desk"


@pytest.mark.parametrize(("field", "limit"), [("name", 200), ("summary", 1000)])
def test_upsert_node_refuses_metadata_over_declared_max_length(tmp_path: Path, field: str, limit: int) -> None:
    with OntologyDB(tmp_path / "m.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        at_limit = _entity("ent_ok", "company").model_copy(update={field: "x" * limit})
        db.upsert_node(at_limit)
        over = _entity("ent_long", "company").model_copy(update={field: "x" * (limit + 1)})
        with pytest.raises(ValueError):
            db.upsert_node(over)
        assert {n.id for n in db.list_all_nodes()} == {"ent_ok"}


def _add_optional_view_facet(raw: dict) -> None:
    raw["facet_schema"]["node"]["view"]["horizon"] = {"kind": "text", "required": False}


def test_schema_change_without_version_bump_migrates_and_restamps(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    shipped = _shipped_registry()
    with OntologyDB(db_path, embedding_dim=DIM, registry=shipped) as db:
        db.conn.execute(
            "INSERT INTO nodes (id, node_type, name, summary, facets_json, created_at, updated_at) "
            "VALUES ('vw_old', 'view', 'Old', 'old', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            (json.dumps({"view_type": "analyst_report", "target_price": "USD 630"}),),
        )
        db.conn.commit()
        stamp_before = db.get_metadata("registry_version")
    assert stamp_before is not None

    changed = load_registry(_write_registry(tmp_path, _add_optional_view_facet))
    assert changed.version == shipped.version
    with OntologyDB(db_path, embedding_dim=DIM, registry=changed) as db:
        price = _stored_target_price(db)
        assert price == {"amount": 630, "currency": "USD"}
        assert db.get_metadata("registry_version") != stamp_before


def test_undeclared_edge_facets_round_trip(tmp_path: Path) -> None:
    facets = {"basis": "extracted", "role": "CEO", "house_flavor": {"nested": ["a", 1]}}
    with OntologyDB(tmp_path / "f.db", embedding_dim=DIM, registry=_shipped_registry()) as db:
        db.upsert_node(_entity("ent_a", "person"))
        db.upsert_node(_entity("ent_b", "company"))
        db.upsert_edge(Edge(id="e1", from_id="ent_a", to_id="ent_b", relation="WORKS_AT", facets=facets))
        row = db.conn.execute("SELECT facets_json FROM edges WHERE id = 'e1'").fetchone()
    assert json.loads(row[0]) == facets


# R1: unmapped relations are held in `pending_edges`, suggested by audit, promoted by repair.

_FROBNICATES_PAYLOAD = {
    "entities": [_OMEGA],
    "views": [{"temp_id": "v1", "name": "Omega rumor", "summary": "Omega may slip.", "view_type": "rumor"}],
    "edges": [{"from_ref": "v1", "to_ref": "e1", "relation": "FROBNICATES"}],
}


def _pending_count(db: OntologyDB) -> int:
    return int(db.conn.execute("SELECT COUNT(*) FROM pending_edges").fetchone()[0])


def _edge_count(db: OntologyDB) -> int:
    return int(db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])


def _map_frobnicates(raw: dict) -> None:
    raw["relations"].append(
        {
            "name": "FROBNICATES",
            "description": "A view frobnicates the entity it concerns.",
            "from_types": ["view"],
            "to_types": ["entity"],
            "aliases": [],
            "inverse_aliases": [],
            "alias_facets": {},
            "symmetric": False,
            "traversal_group": "core",
        }
    )


def test_unmapped_edge_is_held_pending_suggested_by_audit_and_promoted_by_repair(tmp_path: Path) -> None:
    db, report, rel = _ingest(tmp_path, _FROBNICATES_PAYLOAD)
    db_path = tmp_path / "o.db"
    with db:
        assert _note_errors(report) == []
        assert rel in db.get_ingestion_log()
        assert _edge_count(db) == 0
        assert _pending_count(db) == 1

    before = db_path.read_bytes()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True, registry=_shipped_registry()) as ro:
        audit = run_ontology_audit(ro, _shipped_registry())
    assert "FROBNICATES" in {s.name for s in audit.unmapped_relations}
    assert db_path.read_bytes() == before

    mapped = load_registry(_write_registry(tmp_path, _map_frobnicates, name="mapped_registry.json"))
    with OntologyDB(db_path, embedding_dim=DIM, registry=mapped) as db:
        repair_ontology(db, mapped)
        rows = db.conn.execute("SELECT relation, facets_json FROM edges").fetchall()
        assert [r[0] for r in rows] == ["FROBNICATES"]
        assert json.loads(rows[0][1])["basis"] == "extracted"
        assert _pending_count(db) == 0


def test_pending_edges_are_cleared_with_their_note(tmp_path: Path) -> None:
    from stock_ontology.pipeline import IngestionPipeline

    db, _, rel = _ingest(tmp_path, _FROBNICATES_PAYLOAD)
    data = tmp_path / "data"
    reg = _shipped_registry()
    with db:
        assert _pending_count(db) == 1
        # Re-ingesting the changed note replaces its pending rows instead of adding to them.
        (data / rel).write_text("Omega may slip two quarters.", encoding="utf-8")
        IngestionPipeline(db, _ScriptedFakeLLM(_FROBNICATES_PAYLOAD), data, registry=reg).run()
        assert _pending_count(db) == 1
        # Deleting the note removes its pending rows.
        (data / rel).unlink()
        report = IngestionPipeline(db, _ScriptedFakeLLM(_FROBNICATES_PAYLOAD), data, registry=reg).run()
        assert report.files_deleted == 1
        assert _pending_count(db) == 0
