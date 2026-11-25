"""Review source-bound edits on read-only graph state before the worker applies them."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from stock_ontology.config import note_revision
from stock_ontology.db import EdgeRejected, OntologyDB
from stock_ontology.registry import FacetSchemaError, normalize_name_key
from stock_ontology.services.errors import ServiceError
from stock_ontology.services.registry import (
    changed_fields,
    edit_aliases,
    edit_text,
    identity_aliases,
    identity_labels,
    labels_taken,
)
from stock_ontology.vocab import ACCURACY, is_synthesized_edge

_PERSON_FIELDS = {"name", "aliases", "role", "organization", ACCURACY.group}
_EDGE_FIELDS = {"from_id", "to_id", "relation", "facets"}


def relationship_source_evidence(db: OntologyDB, record: str) -> dict[str, list[str]]:
    """Group the note evidence connecting a graph record to each eligible extraction."""
    node = db.get_node(record)
    if node is None:
        return {}
    sources: dict[str, list[str]] = defaultdict(list)
    for doc_id in db.note_entity_doc_ids(record):
        sources[doc_id].append("membership")
    if node.source_doc_id:
        sources[node.source_doc_id].append("node")
    for edge in db.get_incident_edges(record):
        if edge["source_doc_id"] and not is_synthesized_edge(edge["facets"]):
            sources[edge["source_doc_id"]].append(f"edge:{edge['edge_id']}")
    return {doc_id: sorted(evidence) for doc_id, evidence in sources.items()}


def _rumor_company_ids(db: OntologyDB, person_id: str) -> list[str]:
    """Companies that a rumor authored by `person_id` is about: their consensus weighs the person's accuracy."""
    companies: set[str] = set()
    for authored in db.get_incident_edges(person_id):
        view = authored["neighbor"]
        if authored["relation"] != "AUTHORED_BY" or authored["direction"] != "incoming" or (
            view["node_type"] != "view" or view["facets"].get("view_type") != "rumor"
        ):
            continue
        companies.update(
            item["neighbor"]["id"] for item in db.get_incident_edges(view["id"])
            if item["neighbor"]["node_type"] == "entity" and item["neighbor"]["facets"].get("entity_type") == "company"
        )
    return sorted(companies)


def _edit_accuracy(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    accuracy = ACCURACY.coerce(value)
    if accuracy is None:
        raise ServiceError("invalid", "Choose high, medium or low accuracy, or leave it unrated.", key="service_error.choose_accuracy")
    return accuracy


def _organization(db: OntologyDB, name: str) -> str | None:
    key = normalize_name_key(name)
    matches = [
        node.id for node in db.list_nodes(node_type="entity", limit=-1)
        if node.facets.get("entity_type") in {"company", "institution"}
        and key in {normalize_name_key(label) for label in [node.name, *node.aliases]}
    ] if key else []
    return matches[0] if len(matches) == 1 else None


_EDGE_REJECTIONS = {
    "relation": ("Choose a relationship type from the applied registry.", "service_error.choose_relationship_type"),
    "endpoints": ("Choose two different existing endpoints.", "service_error.choose_two_endpoints"),
    "not_allowed": ("The applied registry does not allow that relationship between these nodes.",
                    "service_error.relationship_not_allowed"),
}


def _review_edge(
    db: OntologyDB, before: dict[str, Any], changes: dict[str, Any], *, all_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    after = {key: before.get(key) for key in ("from_id", "to_id", "relation", "facets")}
    for key in ("from_id", "to_id", "relation"):
        if key in changes:
            after[key] = edit_text(changes[key], key)
    relation = db.registry.resolve_relation(after["relation"] or "")
    updates = changes.get("facets", {})
    editable = db.registry.edge_facet_keys(relation.canonical) - {"basis"} if relation else set()
    if relation and (not isinstance(updates, dict) or updates.keys() - editable):
        raise ServiceError("invalid", "Choose editable relationship fields from the applied registry.", key="service_error.choose_relationship_fields_registry")
    facets = dict(after["facets"] or {"basis": "extracted"})
    for field, value in updates.items():
        if value is None:
            facets.pop(field, None)
        else:
            facets[field] = value
    try:
        after = db.check_edge(after["relation"] or "", after["from_id"] or "", after["to_id"] or "", facets)
    except EdgeRejected as exc:
        message, key = _EDGE_REJECTIONS[exc.reason]
        raise ServiceError("invalid", message, key=key) from exc
    except FacetSchemaError as exc:
        raise ServiceError("invalid", str(exc)) from exc
    if any(
        row["edge_id"] != before.get("edge_id") and not row.get("pending") and
        (row["from_id"], row["to_id"], row["relation"]) == (after["from_id"], after["to_id"], after["relation"])
        for row in all_edges
    ):
        raise ServiceError("conflict", "This note already records that relationship.", key="service_error.relationship_exists")
    return after


def _note_edges(db: OntologyDB, doc_id: str) -> list[dict[str, Any]]:
    """The note's edges, then its pending (unmapped) edges marked `pending`, each sorted by ID."""
    return [
        {**row, "pending": True} if pending else row
        for pending in (False, True)
        for row in sorted(db.list_note_edges(doc_id, pending=pending), key=lambda item: item["edge_id"])
    ]


def review_note_correction(
    db: OntologyDB, path: Path, data_dir: Path, *,
    kind: str, changes: dict[str, Any], record: str = "", edge_id: str = "",
    keep_previous_name: bool = False,
) -> dict[str, Any]:
    """Return exact before and after graph values, bound to a processed source revision."""
    file = path.relative_to(data_dir.resolve()).as_posix()
    digest = note_revision(path.read_text(encoding="utf-8"))
    note = db.get_note_state(file)
    if not note or not note["entities_recorded"] or note["content_hash"] != digest:
        raise ServiceError("conflict", "Review the latest processed version of this source note.", key="service_error.stale_source_note")
    doc_id = note["doc_id"]
    all_edges = _note_edges(db, doc_id)
    edges: list[dict[str, Any]] = []
    person = None
    diff = []
    source_evidence = None
    if kind == "person":
        if not changes or changes.keys() - _PERSON_FIELDS:
            raise ServiceError("invalid", "Choose person details or identity fields.", key="service_error.choose_person_fields")
        node = db.get_node(record)
        if (
            node is None or node.node_type != "entity" or node.facets.get("entity_type") != "person"
            or doc_id not in db.note_entity_doc_ids(record)
        ):
            raise ServiceError("not_found", "That person is not in the selected note's extraction.", key="service_error.person_missing")
        before = {"name": node.name, "aliases": node.aliases,
                  **{key: node.facets.get(key) for key in ("role", "organization", ACCURACY.group)}}
        after = before.copy()
        for field, value in changes.items():
            if field == ACCURACY.group:
                after[field] = _edit_accuracy(value)
            else:
                after[field] = edit_aliases(value) if field == "aliases" else edit_text(value, field)
        db.registry.check_metadata(after["name"], node.summary)
        after["aliases"] = identity_aliases(
            node.name, after["name"], after["aliases"],
            keep_previous_name=keep_previous_name, max_length=db.registry.metadata_max_length["name"],
        )
        introduced = identity_labels(after["name"], *after["aliases"]) - identity_labels(node.name, *node.aliases)
        if labels_taken(introduced, (
            identity_labels(other.name, *other.aliases)
            for other in db.list_nodes(node_type="entity", limit=-1) if other.id != node.id
        )):
            raise ServiceError("conflict", "A proposed name or alternate name identifies another entity.", key="service_error.name_taken")
        facets = {**node.facets, **{field: after[field] for field in ("role", "organization", ACCURACY.group) if field in changes}}
        if facets.get(ACCURACY.group) is None:
            facets.pop(ACCURACY.group, None)
        facets = db.registry.check_facets("entity", facets)
        person = {"before": node.model_dump(mode="json"), "name": after["name"], "aliases": after["aliases"],
                  "facets": facets}
        diff = changed_fields(before, after)
        if before[ACCURACY.group] != after[ACCURACY.group]:
            person["rumor_company_ids"] = _rumor_company_ids(db, record)

        old_org = before["organization"]
        if any(change["field"] in {"role", "organization"} for change in diff):
            old_company = _organization(db, old_org) if isinstance(old_org, str) else None
            for row in all_edges:
                if row.get("pending") or row["relation"] != "WORKS_AT" or row["from_id"] != record or row["to_id"] != old_company:
                    continue
                edge_changes = {}
                if before["organization"] != after["organization"]:
                    new_company = _organization(db, after["organization"])
                    if new_company is None:
                        raise ServiceError("invalid", "Choose an unambiguous organization for the supporting employment relationship.", key="service_error.ambiguous_employer")
                    edge_changes["to_id"] = new_company
                if (
                    before["role"] != after["role"] and row["facets"].get("role") == before["role"]
                    and "role" in db.registry.edge_facet_keys("WORKS_AT")
                ):
                    edge_changes["facets"] = {"role": after["role"]}
                if edge_changes:
                    replacement = _review_edge(db, row, edge_changes, all_edges=all_edges)
                    edges.append({"before": row, "after": replacement})
                    diff.extend({**change, "relationship": row["edge_id"]} for change in changed_fields(row, replacement))
    elif kind in {"relationship", "relationship_add"}:
        if not changes or changes.keys() - _EDGE_FIELDS:
            raise ServiceError("invalid", "Choose relationship fields to change.", key="service_error.choose_relationship_fields")
        before = next((row for row in all_edges if row["edge_id"] == edge_id), None)
        if kind == "relationship" and before is None:
            raise ServiceError("not_found", "That relationship is not in the selected note's extraction.", key="service_error.relationship_missing")
        if kind == "relationship_add":
            if edge_id or (record and record not in (changes.get("from_id"), changes.get("to_id"))):
                raise ServiceError("invalid", "The new relationship must connect to the current record.", key="service_error.relationship_off_record")
            # From a record's page, the note must already connect to that record. The note reader's
            # own note is the source, so it names no record.
            if record:
                source_evidence = relationship_source_evidence(db, record).get(doc_id)
                if not source_evidence:
                    raise ServiceError("conflict", "Choose a processed source note connected to the current record.", key="service_error.choose_source_note")
            before = {}
        assert before is not None
        after = _review_edge(db, before, changes, all_edges=all_edges)
        edges.append({"before": before, "after": after})
        diff = changed_fields(before, after)
    elif kind == "relationship_delete":
        before = next((row for row in all_edges if row["edge_id"] == edge_id), None)
        if before is None:
            raise ServiceError("not_found", "That relationship is not in the selected note's extraction.", key="service_error.relationship_missing")
        edges.append({"before": before, "after": {}})
        diff = [{"field": field, "before": before[field], "after": None} for field in ("from_id", "relation", "to_id")]
    else:
        raise ServiceError("invalid", "Choose a person or relationship correction.", key="service_error.choose_correction")

    if not diff:
        raise ServiceError("invalid", "Change at least one field before reviewing.", key="service_error.no_changes")
    return {
        "file": file, "expected_hash": digest, "doc_id": doc_id, "ingested_at": note["ingested_at"],
        "registry_revision": db.registry.revision(), "person": person, "edges": edges, "diff": diff,
        **({"source_evidence": source_evidence} if source_evidence else {}),
        "request": {"kind": kind, "record": record, "edge_id": edge_id, "changes": changes,
                    "keep_previous_name": keep_previous_name},
    }


# Note-reader relationship requests, by the job kind they were once queued as. New ones are reviewed
# at submit; jobs of these kinds queued before that change are reviewed by the worker.
READER_RELATIONSHIP_KINDS = {
    "note.relationship": "relationship",
    "note.relationship.add": "relationship_add",
    "note.relationship.delete": "relationship_delete",
}


def review_reader_correction(
    db: OntologyDB, path: Path, data_dir: Path, job_kind: str, params: dict[str, Any],
) -> dict[str, Any]:
    """Review a note-reader relationship request with the same rules as an Ontology page correction.

    The reader sends `relation`, `from_id` and `to_id` (or `reverse` to swap the current endpoints),
    `facets` for an add, and the note revision it rendered as `expected_hash`."""
    kind = READER_RELATIONSHIP_KINDS[job_kind]
    edge_id = str(params.get("edge_id") or "")
    changes: dict[str, Any] = {}
    if kind != "relationship_delete":
        changes = {key: params[key] for key in ("from_id", "relation", "to_id") if params.get(key) is not None}
        if kind == "relationship_add" and params.get("facets"):
            changes["facets"] = params["facets"]
        if kind == "relationship" and params.get("reverse"):
            note = db.get_note_state(path.relative_to(data_dir.resolve()).as_posix())
            row = next((row for row in _note_edges(db, note["doc_id"]) if row["edge_id"] == edge_id), None) if note else None
            if row is not None:
                changes["from_id"], changes["to_id"] = (
                    changes.get("to_id", row["to_id"]), changes.get("from_id", row["from_id"]),
                )
    reviewed = review_note_correction(db, path, data_dir, kind=kind, changes=changes, edge_id=edge_id)
    expected = params.get("expected_hash")
    if expected and expected != reviewed["expected_hash"]:
        raise ServiceError("conflict", "Review the latest processed version of this source note.", key="service_error.stale_source_note")
    return reviewed
