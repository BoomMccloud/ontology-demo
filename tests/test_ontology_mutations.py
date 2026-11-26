"""Every job kind that writes `ontology.db`, run through the worker on offline test data
(proposal `ontology-mutation-suite`).

Each kind in `services.processing.JOB_KINDS` has a good case, which must leave the expected
node, edge, pending edge, and note membership rows, and a bad case, which must fail or be
refused and leave the graph unchanged. After every case the graph must pass
`assert_ontology_invariants`, which keeps no copy of a rule: content rules come from the
registry (`OntologyRegistry`, `validate_rollout`, `run_ontology_audit`), and structure rules
from SQLite and the product's own rebuild and repair code.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlite_vec

from stock_ontology.config import Settings, note_revision
from stock_ontology.db import OntologyDB
from stock_ontology.models import (
    ConsensusSynthesis,
    Edge,
    ExtractedEdge,
    ExtractedEntity,
    ExtractedEvent,
    ExtractedTheme,
    ExtractionResult,
    FacetKV,
    Node,
)
from stock_ontology.audit import run_ontology_audit
from stock_ontology.registry import FacetSchemaError, OntologyRegistry, RelationSpec, load_registry, save_registry
from stock_ontology.repair import RepairReport, _delete_orphan_artifacts, validate_rollout
from stock_ontology.services import ProcessingService
from stock_ontology.services.corrections import review_note_correction
from stock_ontology.services.processing import JOB_KINDS, JobKind
from stock_ontology.services.registry import RegistryService
from stock_ontology.worker import Worker, load_repair_registry, plan_rollout
from web_support import note_tree

DIM = 8
SHIPPED_REGISTRY = Path(__file__).resolve().parents[1] / "ontology_registry.json"


# ---------------------------------------------------------------------------
# The invariant check
# ---------------------------------------------------------------------------


def _scratch_rules(db: OntologyDB) -> list[tuple[str, str]]:
    """Rules the product states as code that rewrites rows, run on a disposable copy: the
    node_lookup rows `rebuild_node_lookup` derives, and the doc artifacts `repair` deletes as orphans."""
    problems: list[tuple[str, str]] = []
    lookup = "SELECT key, node_id, node_type FROM node_lookup"
    stored = set(map(tuple, db.conn.execute(lookup)))
    with tempfile.TemporaryDirectory(prefix="ontology-invariants-") as temp_dir:
        copy = Path(temp_dir) / "check.db"
        db.copy_to(copy)
        with OntologyDB(copy, embedding_dim=db.embedding_dim) as scratch:
            scratch.rebuild_node_lookup()
            derived = set(map(tuple, scratch.conn.execute(lookup)))
            report = RepairReport()
            _delete_orphan_artifacts(scratch, report)
    for row in sorted(stored ^ derived):
        problems.append(("stale node_lookup", f"{'extra' if row in stored else 'missing'} row {row}"))
    if report.orphan_nodes_deleted or report.orphan_edges_deleted:
        problems.append(
            (
                "orphan doc artifact",
                f"{report.orphan_nodes_deleted} nodes and {report.orphan_edges_deleted} "
                "edges cite a document with no ingestion log entry",
            )
        )
    return problems


def ontology_problems(db: OntologyDB, registry: OntologyRegistry) -> list[tuple[str, str]]:
    """Every broken graph rule as (rule, detail). Structure comes from SQLite and the product's
    rebuild and repair code; content from `registry`. Nothing here restates a rule."""
    problems: list[tuple[str, str]] = []
    # Structure: cascades only run, and references are only checked, with foreign keys on.
    if db.conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        problems.append(("foreign keys off", "this connection does not enforce the schema's references"))
    for table, rowid, parent, _ in db.conn.execute("PRAGMA foreign_key_check"):
        problems.append(("dangling reference", f"{table} row {rowid} names a missing {parent} row"))
    integrity = [row[0] for row in db.conn.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        problems.extend(("schema integrity", message) for message in integrity)
    problems.extend(_scratch_rules(db))

    # Content: every node and edge against the registry's metadata, facet, and endpoint rules.
    try:
        validate_rollout(db, registry)
    except FacetSchemaError as exc:
        problems.append(("registry rule", str(exc)))
    summary = run_ontology_audit(db, registry).summary
    if summary.unmapped_edges:
        problems.append(("unmapped edge", f"{summary.unmapped_edges} edges have a relation the registry does not map"))
    if summary.direction_issue_edges:
        problems.append(("edge direction", f"{summary.direction_issue_edges} edges break their relation's direction"))

    # One edge per (from, canonical relation, to, source note), after the registry's canonicalization.
    def canonical(edge: dict[str, Any]) -> Any:
        return registry.canonicalize_edge(
            edge["relation"],
            from_id=edge["from_id"],
            from_type=edge["from_type"],
            from_entity_type=edge["from_entity_type"],
            to_id=edge["to_id"],
            to_type=edge["to_type"],
            to_entity_type=edge["to_entity_type"],
            facets=edge["facets"],
        )

    keys = Counter()
    for edge in db.list_edges_with_endpoints():
        canon = canonical(edge)
        keys[(canon.from_id, canon.relation, canon.to_id, edge["source_doc_id"])] += 1
    problems.extend(("duplicate canonical edge", f"{key} x{count}") for key, count in sorted(keys.items()) if count > 1)
    # A pending edge waits only while the registry refuses it; one it allows, `repair` would promote.
    for edge in db.list_pending_edges_with_endpoints():
        canon = canonical(edge)
        if canon.matched and canon.endpoints_ok:
            problems.append(
                ("promotable pending edge", f"{edge['edge_id']} ({edge['relation']}) is allowed as {canon.relation}")
            )
    return problems


def assert_ontology_invariants(db: OntologyDB, registry: OntologyRegistry) -> None:
    problems = ontology_problems(db, registry)
    assert not problems, "ontology invariants failed:\n" + "\n".join(f"- {rule}: {detail}" for rule, detail in problems)


# ---------------------------------------------------------------------------
# Offline workspace: the shipped registry, two processed notes, and a fake LLM
# ---------------------------------------------------------------------------


def _vec(index: int) -> list[float]:
    vec = [0.0] * DIM
    vec[index % DIM] = 1.0
    return vec


def _facets(**values: str) -> list[FacetKV]:
    return [FacetKV(key=key, value=value) for key, value in values.items()]


def _company(temp_id: str, name: str, **facets: str) -> ExtractedEntity:
    return ExtractedEntity(
        temp_id=temp_id, name=name, summary=f"{name} in context.", entity_type="company", facets=_facets(**facets)
    )


def _event(temp_id: str, name: str) -> ExtractedEvent:
    return ExtractedEvent(temp_id=temp_id, name=name, summary=f"{name}.", event_type="fact", event_date="2026-11-20")


def _edge(from_ref: str, relation: str, to_ref: str, **facets: str) -> ExtractedEdge:
    return ExtractedEdge(from_ref=from_ref, relation=relation, to_ref=to_ref, facets=_facets(**facets))


# What the fake LLM extracts from each note, by file name.
EXTRACTIONS: dict[str, Callable[[], ExtractionResult]] = {
    "note.md": lambda: ExtractionResult(
        entities=[
            _company("e_nvda", "NVIDIA", sector="Semiconductors"),
            _company("e_tsmc", "TSMC", sector="Semiconductors"),
            ExtractedEntity(
                temp_id="e_dana",
                name="Dana Lee",
                summary="Supply chain analyst.",
                entity_type="person",
                facets=_facets(role="analyst", organization="NVIDIA"),
            ),
        ],
        themes=[
            ExtractedTheme(temp_id="t_ai", name="AI Infrastructure & Capex", summary="AI capex.", stage="accelerating")
        ],
        events=[_event("ev_ramp", "NVIDIA rack ramp")],
        edges=[
            _edge("ev_ramp", "ABOUT", "e_nvda"),
            _edge("e_nvda", "EXPOSED_TO", "t_ai", sentiment="positive"),
            _edge("e_dana", "WORKS_AT", "e_nvda"),
            _edge("e_nvda", "BUY", "e_tsmc"),
            _edge("e_nvda", "PARTNERS_WITH", "e_tsmc"),  # unmapped: held pending
        ],
    ),
    "peer.md": lambda: ExtractionResult(
        entities=[_company("e_vrt", "Vertiv", sector="Industrials")],
        events=[_event("ev_vrt", "Vertiv cooling orders")],
        edges=[_edge("ev_vrt", "ABOUT", "e_vrt")],
    ),
    # The note the `process` and `ingest` good cases add. `SUPPLIES_TO` is an inverse alias of BUY.
    "new.md": lambda: ExtractionResult(
        entities=[_company("e_acme", "Acme Robotics", sector="Industrials"), _company("e_nvda", "NVIDIA")],
        events=[_event("ev_acme", "Acme orders up 40%")],
        edges=[_edge("ev_acme", "ABOUT", "e_acme"), _edge("e_acme", "SUPPLIES_TO", "e_nvda")],
    ),
    # A company without its required `sector`: every regeneration is refused.
    "no_sector.md": lambda: ExtractionResult(
        entities=[_company("e_bad", "Sectorless Co")],
        events=[_event("ev_bad", "Sectorless news")],
        edges=[_edge("ev_bad", "ABOUT", "e_bad")],
    ),
    # A name over the registry's `metadata_max_length`.
    "long_name.md": lambda: ExtractionResult(
        entities=[_company("e_long", "L" * 201, sector="Industrials")],
    ),
}


class _FakeLLM:
    """Offline extraction, consensus, and embeddings. `embed_index` picks the returned vector;
    `drop_embeddings` returns none, as a provider that answers short."""

    def __init__(self, *, embed_index: int = 0, drop_embeddings: bool = False) -> None:
        self.embed_index = embed_index
        self.drop_embeddings = drop_embeddings

    def format_chain_summary(self) -> str:
        return "fake"

    def close(self) -> None:
        return None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [] if self.drop_embeddings else [_vec(self.embed_index) for _ in texts]

    def extract_document(self, *, source_meta: dict[str, Any], **_: Any) -> ExtractionResult:
        return EXTRACTIONS[Path(str(source_meta["file_path"])).name]()

    def synthesize_consensus(self, *, company: Node, events: list[Node], **_: Any) -> ConsensusSynthesis:
        return ConsensusSynthesis(
            stance="buy",
            support_strength="strong",
            conviction="high",
            summary=f"Consensus on {company.name}.",
            pillars=["Demand"],
            supporting_node_ids=[event.id for event in events],
        )


@dataclasses.dataclass
class Workspace:
    settings: Settings
    llm: _FakeLLM = dataclasses.field(default_factory=_FakeLLM)

    @property
    def jobs(self) -> ProcessingService:
        return ProcessingService(self.settings)

    def run(self) -> None:
        Worker(self.settings, llm_factory=lambda _settings: self.llm).run_once(scan=False)

    def run_ok(self, job_id: str) -> dict[str, Any]:
        """Run the worker for a setup job, which must succeed."""
        self.run()
        status = self.jobs.get_status(job_id)
        assert status["state"] == "succeeded", (status["error_code"], status["error"])
        return status

    @contextmanager
    def read(self) -> Iterator[OntologyDB]:
        with OntologyDB(self.settings.db_path, embedding_dim=DIM, read_only=True) as db:
            yield db

    @contextmanager
    def write(self) -> Iterator[OntologyDB]:
        """A direct write, for seeding a defect or a legacy job; product writes go through jobs."""
        with OntologyDB(self.settings.db_path, embedding_dim=DIM) as db:
            yield db

    def note(self, name: str, text: str | None = None) -> str:
        (self.settings.data_dir / name).write_text(text or f"{name} source text.\n", encoding="utf-8")
        return name

    def revision(self, file: str) -> str:
        return note_revision((self.settings.data_dir / file).read_text(encoding="utf-8"))

    def node_id(self, name: str) -> str:
        with self.read() as db:
            node = db.find_by_name_or_alias(name)
        assert node is not None, name
        return node.id

    def edge_id(self, from_name: str, relation: str, to_name: str, *, pending: bool = False) -> str:
        table = "pending_edges" if pending else "edges"
        with self.read() as db:
            row = db.conn.execute(
                f"SELECT e.id FROM {table} e JOIN nodes f ON f.id = e.from_id JOIN nodes t ON t.id = e.to_id "  # noqa: S608
                "WHERE f.name = ? AND e.relation = ? AND t.name = ?",
                (from_name, relation, to_name),
            ).fetchone()
        assert row is not None, (from_name, relation, to_name, table)
        return str(row[0])


def _workspace_at(root: Path) -> Workspace:
    return Workspace(
        Settings(
            db_path=root / "ontology.db",
            embedding_dim=DIM,
            data_dir=root / "notes",
            registry_path=root / "registry.json",
        )
    )


@pytest.fixture(scope="module")
def base_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The shipped registry, adopted, and two notes processed through the worker."""
    root = tmp_path_factory.mktemp("base")
    ws = _workspace_at(root)
    ws.settings.data_dir.mkdir()
    shutil.copy(SHIPPED_REGISTRY, ws.settings.registry_path)
    registry = load_registry(ws.settings.registry_path)
    with OntologyDB(ws.settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")
    for name in ("note.md", "peer.md"):
        ref = ws.jobs.request_processing(ws.note(name))
        ws.run_ok(ref.job_id)
    return root


@pytest.fixture
def ws(base_root: Path, tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    shutil.copytree(base_root, root)
    return _workspace_at(root)


# ---------------------------------------------------------------------------
# Graph views: what a case expects, and what a refused case must leave untouched
# ---------------------------------------------------------------------------


def _graph(db: OntologyDB) -> dict[str, set[tuple[Any, ...]]]:
    """Extracted graph rows by name: nodes, edges, pending edges, and note memberships.
    Consensus views and synthesized edges are left out; consensus refresh rewrites them."""
    names = {node.id: node.name for node in db.list_all_nodes()}
    files = {entry["doc_id"]: path for path, entry in db.get_ingestion_log().items()}

    def edges(table: str) -> set[tuple[Any, ...]]:
        return {
            (names.get(row["from_id"]), row["relation"], names.get(row["to_id"]), files.get(row["source_doc_id"]))
            for row in db.conn.execute(f"SELECT * FROM {table}")  # noqa: S608
            if json.loads(row["facets_json"]).get("basis") != "synthesized"
        }

    return {
        "nodes": {
            (node.node_type, node.name) for node in db.list_all_nodes() if node.facets.get("view_type") != "consensus"
        },
        "edges": edges("edges"),
        "pending": edges("pending_edges"),
        "members": {
            (files.get(row["doc_id"]), names.get(row["entity_id"]))
            for row in db.conn.execute("SELECT doc_id, entity_id FROM note_entities")
        },
    }


def _stored_state(ws: Workspace) -> dict[str, Any]:
    """Every row outside the `jobs` table (the worker records a refused job there), the
    registry file, and the notes."""
    with ws.read() as db:
        tables = [
            row[0]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'jobs' AND sql NOT LIKE 'CREATE VIRTUAL TABLE%' ORDER BY name"
            )
        ]
        rows = {table: sorted(map(tuple, db.conn.execute(f"SELECT * FROM {table}")), key=repr) for table in tables}  # noqa: S608
    return {"rows": rows, "registry": ws.settings.registry_path.read_bytes(), "notes": note_tree(ws.settings.data_dir)}


def _check_invariants(ws: Workspace) -> None:
    with ws.read() as db:
        applied = db.applied_registry()
        assert applied is not None
        assert_ontology_invariants(db, applied)


# ---------------------------------------------------------------------------
# One good and one bad case per job kind
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Case:
    """`submit` prepares the workspace and returns the job to run. A good case lists the rows the
    job adds and removes per `_graph` table (a table it omits must not change) and may `check`
    more. A bad case names the error code its job fails with, or the note a succeeding `ingest`
    refuses (`refuses`), and a fragment of the reason (`because`); it must leave `_stored_state`
    unchanged."""

    kind: str
    name: str
    submit: Callable[[Workspace], str]
    added: dict[str, set[tuple[Any, ...]]] = dataclasses.field(default_factory=dict)
    removed: dict[str, set[tuple[Any, ...]]] = dataclasses.field(default_factory=dict)
    check: Callable[[Workspace, dict[str, Any]], None] | None = None
    fails_with: str | None = None
    refuses: str | None = None
    because: str = ""


# --- note processing


def _process(file: str) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        return ws.jobs.request_processing(ws.note(file)).job_id

    return submit


def _ingest(file: str) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        ws.note(file)
        return ws.jobs.submit_operator(
            "ingest",
            {
                "data_dir": str(ws.settings.data_dir),
                "registry_path": str(ws.settings.registry_path),
            },
        ).job_id

    return submit


NEW_NOTE_ROWS = {
    "nodes": {("entity", "Acme Robotics"), ("event", "Acme orders up 40%")},
    # `Acme SUPPLIES_TO NVIDIA` is stored as its canonical BUY, buyer first.
    "edges": {("Acme orders up 40%", "ABOUT", "Acme Robotics", "new.md"), ("NVIDIA", "BUY", "Acme Robotics", "new.md")},
    "members": {("new.md", "Acme Robotics"), ("new.md", "NVIDIA")},
}


# --- note-reader corrections. The base note `note.md` holds NVIDIA, TSMC, and Dana Lee;
# `peer.md` holds Vertiv.


def _correction(kind: str, params: Callable[[Workspace], dict[str, Any]]) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        return ws.jobs.submit_correction(
            kind, "note.md", {**params(ws), "expected_hash": ws.revision("note.md")}
        ).job_id

    return submit


def _relink(replacement: Callable[[Workspace], str]) -> Callable[[Workspace], str]:
    return _correction(
        "note.relink",
        lambda ws: {
            "entity_id": ws.node_id("TSMC"),
            "replacement_id": replacement(ws),
            "new_entity": None,
        },
    )


def _member(kind: str, entity: Callable[[Workspace], str]) -> Callable[[Workspace], str]:
    return _correction(kind, lambda ws: {"entity_id": entity(ws)})


def _review(ws: Workspace) -> dict[str, Any]:
    """The Ontology page's reviewed correction: add NVIDIA OWNS TSMC to `note.md`."""
    with ws.read() as db:
        return review_note_correction(
            db,
            (ws.settings.data_dir / "note.md").resolve(),
            ws.settings.data_dir,
            kind="relationship_add",
            changes={"from_id": ws.node_id("NVIDIA"), "relation": "OWNS", "to_id": ws.node_id("TSMC")},
        )


def _reviewed_correction(*, edit_note_after_review: bool) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        review = _review(ws)
        if edit_note_after_review:
            ws.note("note.md", "Edited after the review.\n")
        return ws.jobs.submit_correction("note.ontology.correction", "note.md", review).job_id

    return submit


BUY = ("NVIDIA", "BUY", "TSMC", "note.md")
PENDING = ("NVIDIA", "PARTNERS_WITH", "TSMC", "note.md")


# --- operator jobs


def _reembed(llm: _FakeLLM) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        ws.llm = llm
        return ws.jobs.submit_operator("reembed", {}).job_id

    return submit


def _all_vectors_are(index: int) -> Callable[[Workspace, dict[str, Any]], None]:
    def check(ws: Workspace, _status: dict[str, Any]) -> None:
        with ws.read() as db:
            vectors = dict(db.conn.execute("SELECT node_id, embedding FROM node_vectors").fetchall())
            node_ids = {node.id for node in db.list_all_nodes()}
        assert set(vectors) == node_ids
        assert set(vectors.values()) == {sqlite_vec.serialize_float32(_vec(index))}

    return check


def _seed_orphan(ws: Workspace) -> None:
    """An event and edge citing a document with no ingestion log entry, as an interrupted delete leaves."""
    with ws.write() as db:
        db.upsert_node(
            Node(
                id="evt_orphan",
                node_type="event",
                name="Orphan event",
                summary="",
                facets={"event_type": "fact"},
                source_doc_id="doc_gone",
            )
        )
        db.upsert_edge(
            Edge(
                id="edge_orphan",
                from_id="evt_orphan",
                to_id=ws.node_id("NVIDIA"),
                relation="ABOUT",
                source_doc_id="doc_gone",
                facets={"basis": "extracted"},
            )
        )
    with ws.read() as db:
        assert "orphan doc artifact" in {rule for rule, _ in ontology_problems(db, db.registry)}


def _repair(*, change_graph_after_review: bool) -> Callable[[Workspace], str]:
    """The good case repairs a seeded orphan; the bad one reviews the clean graph, then a write lands."""

    def submit(ws: Workspace) -> str:
        if not change_graph_after_review:
            _seed_orphan(ws)
        plan = plan_rollout(ws.settings, load_repair_registry(ws.settings.registry_path), adoption=False)
        if change_graph_after_review:
            with ws.write() as db:
                db.upsert_node(
                    Node(
                        id="ent_late",
                        node_type="entity",
                        name="Late Co",
                        summary="",
                        facets={"entity_type": "company", "sector": "Industrials"},
                    )
                )
        return ws.jobs.submit_operator("repair", plan.job_payload(ws.settings, adoption=False)).job_id

    return submit


def _write_proposal(ws: Workspace) -> tuple[Path, OntologyRegistry]:
    """The next registry version, which maps the pending PARTNERS_WITH between companies."""
    current = load_registry(ws.settings.registry_path)
    proposal = current.model_copy(
        update={
            "version": current.version + 1,
            "relations": [
                *current.relations,
                RelationSpec(
                    name="PARTNERS_WITH",
                    description="A commercial partnership between two companies.",
                    from_types=["entity:company"],
                    to_types=["entity:company"],
                    traversal_group="core",
                ),
            ],
        }
    )
    path = ws.settings.registry_path.with_name("proposal.json")
    save_registry(proposal, path)
    return path, current


def _publish(*, current_revision: str | None = None) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        path, current = _write_proposal(ws)
        return ws.jobs.submit_operator(
            "registry.publish",
            {
                "registry_path": str(ws.settings.registry_path),
                "proposal_path": str(path),
                "proposed_revision": load_registry(path).revision(),
                "current_revision": current_revision or current.revision(),
            },
        ).job_id

    return submit


def _published_not_applied(ws: Workspace, _status: dict[str, Any]) -> None:
    published = load_registry(ws.settings.registry_path)
    proposal = load_registry(ws.settings.registry_path.with_name("proposal.json"))
    assert (published.version, published.revision()) == (proposal.version, proposal.revision())
    assert published.publications[-1].revision == proposal.revision()
    with ws.read() as db:
        applied = db.applied_registry()
    assert applied is not None and applied.revision() != published.revision()


def _apply(*, change_registry_after_review: bool) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        ws.run_ok(_publish()(ws))
        plan = plan_rollout(ws.settings, load_registry(ws.settings.registry_path), adoption=True)
        if change_registry_after_review:
            changed = load_registry(ws.settings.registry_path)
            save_registry(changed.model_copy(update={"version": changed.version + 1}), ws.settings.registry_path)
        return ws.jobs.submit_operator("registry.apply", plan.job_payload(ws.settings, adoption=True)).job_id

    return submit


def _adopted_published(ws: Workspace, _status: dict[str, Any]) -> None:
    with ws.read() as db:
        applied = db.applied_registry()
    assert applied is not None and applied.revision() == load_registry(ws.settings.registry_path).revision()


def _preview(*, browser_record: bool) -> Callable[[Workspace], str]:
    def submit(ws: Workspace) -> str:
        if browser_record:
            with ws.read() as db:
                review = RegistryService(ws.settings).review_record_edit(
                    db, "companies", "NVIDIA", {"sector": "Compute"}
                )
            ws.run_ok(ws.jobs.submit_operator("registry.publish", review["payload"]).job_id)
        else:
            ws.run_ok(_publish()(ws))
        return ws.jobs.submit_operator("registry.apply.preview", {"confirmation": "fixture"}).job_id

    return submit


def _previewed_linked_record(ws: Workspace, status: dict[str, Any]) -> None:
    diff = status["result"]["diff"]
    assert [(entry["record"], entry["effect"]) for entry in diff] == [("NVIDIA", "linked")], diff
    with ws.read() as db:
        applied = db.applied_registry()
        nvidia = db.get_node(ws.node_id("NVIDIA"))
    assert applied is not None and applied.resolve_company("NVIDIA").spec.sector == "Semiconductors"
    assert nvidia is not None and nvidia.facets["sector"] == "Semiconductors", "the preview wrote the live graph"


GOOD_CASES: list[Case] = [
    Case("process", "new-note", _process("new.md"), added=NEW_NOTE_ROWS),
    Case("ingest", "scan-finds-new-note", _ingest("new.md"), added=NEW_NOTE_ROWS),
    Case(
        "note.relink",
        "to-existing-entity",
        _relink(lambda ws: ws.node_id("Vertiv")),
        added={
            "edges": {("NVIDIA", "BUY", "Vertiv", "note.md")},
            "pending": {("NVIDIA", "PARTNERS_WITH", "Vertiv", "note.md")},
            "members": {("note.md", "Vertiv")},
        },
        removed={"edges": {BUY}, "pending": {PENDING}, "members": {("note.md", "TSMC")}},
    ),
    Case(
        "note.entity.add",
        "existing-entity",
        _member("note.entity.add", lambda ws: ws.node_id("Vertiv")),
        added={"members": {("note.md", "Vertiv")}},
    ),
    Case(
        "note.entity.delete",
        "with-incident-edges",
        _member("note.entity.delete", lambda ws: ws.node_id("TSMC")),
        removed={"edges": {BUY}, "pending": {PENDING}, "members": {("note.md", "TSMC")}},
    ),
    Case(
        "note.ontology.correction",
        "relationship-add",
        _reviewed_correction(edit_note_after_review=False),
        added={"edges": {("NVIDIA", "OWNS", "TSMC", "note.md")}},
    ),
    Case("reembed", "all-nodes", _reembed(_FakeLLM(embed_index=3)), check=_all_vectors_are(3)),
    Case(
        "repair",
        "orphan-doc-artifacts",
        _repair(change_graph_after_review=False),
        removed={"nodes": {("event", "Orphan event")}, "edges": {("Orphan event", "ABOUT", "NVIDIA", None)}},
    ),
    Case("registry.publish", "next-version", _publish(), check=_published_not_applied),
    Case(
        "registry.apply",
        "promotes-newly-mapped-pending",
        _apply(change_registry_after_review=False),
        added={"edges": {("NVIDIA", "PARTNERS_WITH", "TSMC", "note.md")}},
        removed={"pending": {PENDING}},
        check=_adopted_published,
    ),
    Case(
        "registry.apply.preview", "browser-record-edit", _preview(browser_record=True), check=_previewed_linked_record
    ),
]

BAD_CASES: list[Case] = [
    Case(
        "process",
        "missing-required-facet",
        _process("no_sector.md"),
        fails_with="invalid",
        because="missing required facet 'sector'",
    ),
    Case(
        "ingest", "over-length-name", _ingest("long_name.md"), refuses="long_name.md", because="over the registry max"
    ),
    Case(
        "note.relink",
        "to-missing-entity",
        _relink(lambda ws: "ent_missing"),
        fails_with="invalid",
        because="Select an existing entity",
    ),
    Case(
        "note.entity.add",
        "missing-entity",
        _member("note.entity.add", lambda ws: "ent_missing"),
        fails_with="invalid",
        because="Select an existing entity",
    ),
    Case(
        "note.entity.delete",
        "missing-membership",
        _member("note.entity.delete", lambda ws: ws.node_id("Vertiv")),
        fails_with="invalid",
        because="not in this note's extraction",
    ),
    Case(
        "note.ontology.correction",
        "note-changed-after-review",
        _reviewed_correction(edit_note_after_review=True),
        fails_with="conflict",
        because="latest processed version",
    ),
    Case(
        "reembed",
        "provider-answers-short",
        _reembed(_FakeLLM(drop_embeddings=True)),
        fails_with="invalid",
        because="Embedding count mismatch",
    ),
    Case(
        "repair",
        "graph-changed-after-review",
        _repair(change_graph_after_review=True),
        fails_with="invalid",
        because="changed during review",
    ),
    Case(
        "registry.publish",
        "published-registry-changed",
        _publish(current_revision="sha256:stale"),
        fails_with="invalid",
        because="published registry changed during review",
    ),
    Case(
        "registry.apply",
        "registry-changed-after-review",
        _apply(change_registry_after_review=True),
        fails_with="invalid",
        because="changed during review",
    ),
    Case(
        "registry.apply.preview",
        "not-a-browser-record-edit",
        _preview(browser_record=False),
        fails_with="conflict",
        because="Only an outstanding browser record edit",
    ),
]


def _uncovered(cases: list[Case], kinds: dict[str, JobKind]) -> list[str]:
    return sorted(set(kinds) - {case.kind for case in cases})


def test_every_declared_job_kind_has_a_good_and_a_bad_case() -> None:
    assert {"good": _uncovered(GOOD_CASES, JOB_KINDS), "bad": _uncovered(BAD_CASES, JOB_KINDS)} == {
        "good": [],
        "bad": [],
    }
    assert {case.kind for case in GOOD_CASES + BAD_CASES} <= set(JOB_KINDS), "a case names an undeclared kind"


def test_inventory_fails_when_a_new_job_kind_lands_without_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(JOB_KINDS, "note.unexercised", JobKind(0, "correction"))
    assert _uncovered(GOOD_CASES, JOB_KINDS) == _uncovered(BAD_CASES, JOB_KINDS) == ["note.unexercised"]


@pytest.mark.parametrize("case", GOOD_CASES, ids=lambda case: f"{case.kind}-{case.name}")
def test_good_job_leaves_expected_rows_and_a_sound_graph(ws: Workspace, case: Case) -> None:
    job_id = case.submit(ws)
    with ws.read() as db:
        before = _graph(db)
    ws.run()
    status = ws.jobs.get_status(job_id)
    assert (status["kind"], status["state"]) == (case.kind, "succeeded"), status
    with ws.read() as db:
        after = _graph(db)
    assert {table: after[table] - before[table] for table in after} == {
        table: case.added.get(table, set()) for table in after
    }
    assert {table: before[table] - after[table] for table in after} == {
        table: case.removed.get(table, set()) for table in after
    }
    if case.check is not None:
        case.check(ws, status)
    _check_invariants(ws)


@pytest.mark.parametrize("case", BAD_CASES, ids=lambda case: f"{case.kind}-{case.name}")
def test_bad_job_fails_and_leaves_the_graph_unchanged(ws: Workspace, case: Case) -> None:
    job_id = case.submit(ws)
    before = _stored_state(ws)
    ws.run()
    status = ws.jobs.get_status(job_id)
    assert status["kind"] == case.kind, status
    if case.refuses is not None:
        assert status["state"] == "succeeded", status
        [(file, error)] = status["result"]["errors"]
        assert file == case.refuses, status
    else:
        assert (status["state"], status["error_code"]) == ("failed", case.fails_with), status
        error = status["error"]
    assert case.because and case.because in error, (case.because, error)
    assert _stored_state(ws) == before
    _check_invariants(ws)


# ---------------------------------------------------------------------------
# The invariant check fails on deliberately corrupted databases
# ---------------------------------------------------------------------------


def _doc_id(db: sqlite3.Connection, file: str) -> str:
    return str(db.execute("SELECT doc_id FROM ingestion_log WHERE file_path = ?", (file,)).fetchone()[0])


def _corrupt_dangling_edge(db: sqlite3.Connection) -> None:
    db.execute("UPDATE edges SET to_id = 'ghost' WHERE relation = 'WORKS_AT'")


def _corrupt_membership(db: sqlite3.Connection) -> None:
    db.execute("INSERT INTO note_entities (doc_id, entity_id) VALUES (?, 'ghost')", (_doc_id(db, "note.md"),))


def _corrupt_duplicate_edge(db: sqlite3.Connection) -> None:
    # `SUPPLIES_TO` is the inverse alias of BUY: TSMC -> NVIDIA is the stored NVIDIA BUY TSMC again.
    db.execute(
        "INSERT INTO edges (id, from_id, to_id, relation, facets_json, source_doc_id, created_at) "
        "SELECT 'edge_dup', to_id, from_id, 'SUPPLIES_TO', facets_json, source_doc_id, created_at "
        "FROM edges WHERE relation = 'BUY'"
    )


def _corrupt_required_facet(db: sqlite3.Connection) -> None:
    db.execute("UPDATE nodes SET facets_json = json_remove(facets_json, '$.sector') WHERE name = 'TSMC'")


def _corrupt_orphan_artifact(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO nodes (id, node_type, name, summary, facets_json, source_doc_id, created_at, updated_at) "
        "VALUES ('evt_orphan', 'event', 'Orphan', '', '{\"event_type\": \"fact\"}', 'doc_gone', "
        "'2026-11-26T00:00:00+00:00', '2026-11-26T00:00:00+00:00')"
    )
    db.execute("INSERT INTO node_lookup (key, node_id, node_type) VALUES ('orphan', 'evt_orphan', 'event')")


def _corrupt_lookup(db: sqlite3.Connection) -> None:
    db.execute("UPDATE nodes SET name = 'Vertiv Holdings' WHERE name = 'Vertiv'")


def _corrupt_unmapped_relation(db: sqlite3.Connection) -> None:
    db.execute("UPDATE edges SET relation = 'MYSTERY_LINK' WHERE relation = 'WORKS_AT'")


def _corrupt_long_name(db: sqlite3.Connection) -> None:
    db.execute("UPDATE nodes SET name = ? WHERE node_type = 'event' AND name = 'NVIDIA rack ramp'", ("N" * 201,))
    db.execute("UPDATE node_lookup SET key = ? WHERE key = 'nvidia rack ramp'", ("n" * 201,))


def _corrupt_promotable_pending(db: sqlite3.Connection) -> None:
    db.execute("UPDATE pending_edges SET relation = 'OWNS' WHERE relation = 'PARTNERS_WITH'")


CORRUPTIONS = [
    pytest.param(_corrupt_dangling_edge, "dangling reference", id="dangling-edge-endpoint"),
    pytest.param(_corrupt_membership, "dangling reference", id="membership-to-missing-node"),
    pytest.param(_corrupt_duplicate_edge, "duplicate canonical edge", id="duplicate-canonical-edge"),
    pytest.param(_corrupt_required_facet, "registry rule", id="required-facet-missing"),
    pytest.param(_corrupt_orphan_artifact, "orphan doc artifact", id="orphan-doc-artifact"),
    pytest.param(_corrupt_lookup, "stale node_lookup", id="stale-node-lookup"),
    pytest.param(_corrupt_unmapped_relation, "unmapped edge", id="unmapped-edge-relation"),
    pytest.param(_corrupt_long_name, "registry rule", id="over-length-name"),
    pytest.param(_corrupt_promotable_pending, "promotable pending edge", id="pending-edge-the-registry-allows"),
]


def test_invariant_check_passes_the_processed_base_graph(ws: Workspace) -> None:
    _check_invariants(ws)


@pytest.mark.parametrize(("corrupt", "rule"), CORRUPTIONS)
def test_invariant_check_fails_on_a_corrupted_database(
    ws: Workspace,
    corrupt: Callable[[sqlite3.Connection], None],
    rule: str,
) -> None:
    raw = sqlite3.connect(ws.settings.db_path)  # foreign keys stay off, as in a damaged file
    with raw:
        corrupt(raw)
    raw.close()
    with ws.read() as db:
        applied = db.applied_registry()
        assert applied is not None
        rules = {found for found, _ in ontology_problems(db, applied)}
    assert rule in rules, rules
    with pytest.raises(AssertionError, match=rule), ws.read() as db:
        assert_ontology_invariants(db, applied)


def test_invariant_check_requires_foreign_keys_on_the_connection(ws: Workspace) -> None:
    with ws.read() as db:
        db.conn.execute("PRAGMA foreign_keys = OFF")
        applied = db.applied_registry()
        assert applied is not None
        assert "foreign keys off" in {rule for rule, _ in ontology_problems(db, applied)}
