"""Offline operator workflows spanning audit, publication, and database adoption."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from stock_ontology.cli import app
from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, Node
from stock_ontology.registry import (
    CompanySpec,
    FacetSchemaError,
    RelationSpec,
    create_minimal_registry,
    load_registry,
    save_registry,
)


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    db_path = tmp_path / "test.db"
    registry_path = tmp_path / "ontology_registry.json"
    registry = create_minimal_registry()
    save_registry(registry, registry_path)

    with OntologyDB(db_path, registry=registry) as db:
        for name, ticker in [("Apple", "AAPL"), ("AMD", "AMD")]:
            db.upsert_node(Node(
                id=ticker,
                node_type="entity",
                name=name,
                summary=f"Research subject {name}.",
                facets={"entity_type": "company", "ticker": ticker, "sector": "Technology"},
            ))
        db.insert_pending_edge(Edge(
            id="pending-collaboration",
            from_id="AAPL",
            to_id="AMD",
            relation="COLLABORATES_WITH",
            facets={"basis": "extracted"},
        ))
    return db_path, registry_path, ["--db", str(db_path), "--registry", str(registry_path)]


def _graph_state(db_path: Path) -> tuple[list[str], str | None, str | None]:
    """Graph rows, the applied registry revision, and the facet stamp; job bookkeeping excluded."""
    with OntologyDB(db_path, read_only=True) as db:
        return (
            db.registry_rollout_rows(),
            db.get_metadata("applied_registry_revision"),
            db.get_metadata("registry_version"),
        )


def _registry_status(runner: CliRunner, options: list[str]) -> dict:
    result = runner.invoke(app, ["audit", *options, "--no-sync-suggestions", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["registry"]


def test_audit_writes_proposals_without_changing_official_registry(tmp_path: Path) -> None:
    db_path, registry_path, options = _seed_workspace(tmp_path)
    original_registry = registry_path.read_bytes()
    original_database = db_path.read_bytes()

    result = CliRunner().invoke(app, ["audit", *options, "--sync-suggestions"])

    assert result.exit_code == 0, result.output
    assert registry_path.read_bytes() == original_registry
    assert db_path.read_bytes() == original_database
    proposals = json.loads(registry_path.with_suffix(".suggestions.json").read_text(encoding="utf-8"))
    assert "AMD" in json.dumps(proposals)
    assert "COLLABORATES_WITH" in json.dumps(proposals)


def test_publish_and_apply_require_separate_interactive_decisions(tmp_path: Path) -> None:
    db_path, registry_path, options = _seed_workspace(tmp_path)
    runner = CliRunner()
    initial = load_registry(registry_path)
    proposed = initial.model_copy(deep=True)
    proposed.version += 1
    proposed.companies.append(CompanySpec(name="AMD", ticker="AMD"))
    proposed.relations.append(RelationSpec(
        name="COLLABORATES_WITH",
        from_types=["entity:company"],
        to_types=["entity:company"],
    ))
    assert proposed.schema_stamp() == initial.schema_stamp()
    proposal_path = tmp_path / "proposal.json"
    save_registry(proposed, proposal_path)

    bootstrap = runner.invoke(app, ["registry-apply", *options], input="y\n")
    assert bootstrap.exit_code == 0, bootstrap.output
    status = _registry_status(runner, options)
    assert status["applied_version"] == initial.version
    assert status["published_version"] == initial.version
    applied_database = db_path.read_bytes()
    official_bytes = registry_path.read_bytes()

    publication = ["registry-publish", str(proposal_path), *options]
    declined = runner.invoke(app, publication, input="n\n")
    assert "COLLABORATES_WITH" in declined.output
    assert registry_path.read_bytes() == official_bytes
    assert db_path.read_bytes() == applied_database

    applied_graph = _graph_state(db_path)
    accepted = runner.invoke(app, publication, input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert load_registry(registry_path).version == proposed.version
    # A confirmed publish runs as a worker job: only job bookkeeping may change in the database.
    assert _graph_state(db_path) == applied_graph
    with OntologyDB(db_path, read_only=True) as db:
        assert [job.state for job in db.jobs.list(kind="registry.publish")] == ["succeeded"]
    status = _registry_status(runner, options)
    assert status["published_version"] == proposed.version
    assert status["applied_version"] == initial.version
    with OntologyDB(db_path, registry=load_registry(registry_path)) as db:
        assert db.registry.resolve_company("AMD") is None

    declined = runner.invoke(app, ["registry-apply", *options], input="n\n")
    assert "COLLABORATES_WITH" in declined.output
    assert load_registry(registry_path).version == proposed.version
    assert _graph_state(db_path) == applied_graph
    assert _registry_status(runner, options)["applied_version"] == initial.version

    accepted = runner.invoke(app, ["registry-apply", *options], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert _registry_status(runner, options)["applied_version"] == proposed.version
    with OntologyDB(db_path, read_only=True) as db:
        assert [edge["relation"] for edge in db.list_edges_with_endpoints()] == ["COLLABORATES_WITH"]
        assert db.list_pending_edges_with_endpoints() == []
    with OntologyDB(db_path, registry=load_registry(registry_path)) as db:
        assert db.registry.resolve_company("AMD") is not None


def test_writable_open_does_not_migrate_to_candidate_registry(tmp_path: Path) -> None:
    db_path, registry_path, _ = _seed_workspace(tmp_path)
    applied = load_registry(registry_path)
    candidate = applied.model_copy(deep=True)
    candidate.facet_schema["node"]["view"]["priority"] = {"kind": "number", "required": False}
    with OntologyDB(db_path, registry=applied) as db:
        db.upsert_node(Node(
            id="note-view",
            node_type="view",
            name="Analyst view",
            summary="Test fixture for a facet type change.",
            facets={"view_type": "analyst_report", "priority": "8"},
        ))
    try:
        with OntologyDB(db_path, registry=candidate):
            pass
    except FacetSchemaError:
        pass
    with OntologyDB(db_path, read_only=True) as db:
        view = db.get_node("note-view")
        assert view is not None
        assert view.facets["priority"] == "8"


def test_incompatible_rollout_preserves_applied_registry_and_graph(tmp_path: Path) -> None:
    db_path, registry_path, options = _seed_workspace(tmp_path)
    runner = CliRunner()
    bootstrap = runner.invoke(app, ["registry-apply", *options], input="y\n")
    assert bootstrap.exit_code == 0, bootstrap.output
    initial = load_registry(registry_path)
    proposed = initial.model_copy(deep=True)
    proposed.version += 1
    proposed.facet_schema["node"].setdefault("entity:company", {})["required_identifier"] = {
        "kind": "text",
        "required": True,
    }
    proposal_path = tmp_path / "proposal.json"
    save_registry(proposed, proposal_path)
    publication = runner.invoke(app, ["registry-publish", str(proposal_path), *options], input="y\n")
    assert publication.exit_code == 0, publication.output
    before = db_path.read_bytes()

    rollout = runner.invoke(app, ["registry-apply", *options], input="y\n")

    assert rollout.exit_code != 0, rollout.output
    assert "required_identifier" in rollout.output
    assert db_path.read_bytes() == before
    status = _registry_status(runner, options)
    assert status["published_version"] == proposed.version
    assert status["applied_version"] == initial.version


def test_registry_service_reads_the_applied_registry_not_the_published_file(tmp_path: Path) -> None:
    from stock_ontology.config import Settings
    from stock_ontology.services import RegistryService

    db_path, registry_path, options = _seed_workspace(tmp_path)
    applied = load_registry(registry_path)
    assert CliRunner().invoke(app, ["registry-apply", *options], input="y\n").exit_code == 0
    published = applied.model_copy(deep=True)
    published.version += 1
    published.companies.append(CompanySpec(name="AMD", ticker="AMD"))
    save_registry(published, registry_path)

    service = RegistryService(Settings(db_path=db_path, registry_path=registry_path))
    with OntologyDB(db_path, read_only=True) as db:
        assert service.get_applied(db).revision() == applied.revision() != published.revision()
    fresh = tmp_path / "fresh.db"
    with OntologyDB(fresh) as db:
        assert service.get_applied(db).revision() == published.revision()


def test_record_edits_person_corrections_and_rollout_share_one_identity_rule() -> None:
    import ast
    import inspect
    import textwrap

    import pytest

    from stock_ontology import worker
    from stock_ontology.services import corrections
    from stock_ontology.services.errors import ServiceError
    from stock_ontology.services.registry import RegistryService, identity_aliases, identity_labels, labels_taken

    registry = create_minimal_registry()
    limit = registry.metadata_max_length["name"]
    assert identity_aliases(registry, "Old", "New", ["new", "Alt", "alt"], summary="",
                            keep_previous_name=True) == ["Alt", "Old"]
    assert identity_aliases(registry, "Old", "New", ["Alt"], summary="", keep_previous_name=False) == ["Alt"]
    with pytest.raises(ServiceError) as too_long:
        identity_aliases(registry, "Old", "New", ["x" * (limit + 1)], summary="", keep_previous_name=False)
    assert (too_long.value.code, too_long.value.key) == ("invalid", "service_error.alternate_name_too_long")
    with pytest.raises(FacetSchemaError):
        identity_aliases(registry, "Old", "x" * (limit + 1), [], summary="", keep_previous_name=False)
    assert identity_labels("Acme", None, "ACME", "") == {"acme"}
    assert labels_taken({"acme"}, [{"beta"}, {"acme", "acme corp"}])
    assert not labels_taken({"acme"}, [{"beta"}])

    def calls(function: object) -> set[str]:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))  # type: ignore[arg-type]
        return {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                for node in ast.walk(tree) if isinstance(node, ast.Call)}

    # A registry record edit and a person correction assemble names and check collisions the same way;
    # the rollout preview maps a registry diff onto nodes but checks collisions by the same rule.
    for function in (RegistryService.review_record_edit, corrections.review_note_correction):
        assert {"identity_aliases", "labels_taken"} <= calls(function), function
        assert "unique_labels" not in calls(function), function
    assert "labels_taken" in calls(worker._rollout_record_metadata)
