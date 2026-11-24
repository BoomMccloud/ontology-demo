"""Review source-bound edits on read-only graph state before the worker applies them."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from stock_ontology.db import OntologyDB
from stock_ontology.registry import normalize_name_key
from stock_ontology.services.errors import ServiceError
from stock_ontology.services.notes import note_revision
from stock_ontology.services.registry import changed_fields, edit_aliases, edit_text, unique_labels
from stock_ontology.vocab import is_synthesized_edge

_PERSON_FIELDS = {"name", "aliases", "role", "organization"}
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


def _organization(db: OntologyDB, name: str) -> str | None:
    key = normalize_name_key(name)
    matches = [
        node.id for node in db.list_nodes(node_type="entity", limit=-1)
        if node.facets.get("entity_type") in {"company", "institution"}
        and key in {normalize_name_key(label) for label in [node.name, *node.aliases]}
    ] if key else []
    return matches[0] if len(matches) == 1 else None


def _review_edge(
    db: OntologyDB, before: dict[str, Any], changes: dict[str, Any], *, all_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    after = {key: before.get(key) for key in ("from_id", "to_id", "relation", "facets")}
    for key in ("from_id", "to_id", "relation"):
        if key in changes:
            after[key] = edit_text(changes[key], key)
    relation = db.registry.resolve_relation(after["relation"] or "")
    if relation is None:
        raise ServiceError("invalid", "Choose a relationship type from the applied registry.")
    updates = changes.get("facets", {})
    editable = db.registry.edge_facet_keys(relation.canonical) - {"basis"}
    if not isinstance(updates, dict) or updates.keys() - editable:
        raise ServiceError("invalid", "Choose editable relationship fields from the applied registry.")
    facets = dict(after["facets"] or {"basis": "extracted"})
    for field, value in updates.items():
        if value is None:
            facets.pop(field, None)
        else:
            facets[field] = value
    start = db.get_node(after["from_id"] or "")
    end = db.get_node(after["to_id"] or "")
    if start is None or end is None or start.id == end.id:
        raise ServiceError("invalid", "Choose two different existing endpoints.")
    canonical = db.registry.canonicalize_edge(
        after["relation"], from_id=start.id, from_type=start.node_type, from_entity_type=start.facets.get("entity_type"),
        to_id=end.id, to_type=end.node_type, to_entity_type=end.facets.get("entity_type"), facets=facets,
    )
    if not canonical.endpoints_ok:
        raise ServiceError("invalid", "The applied registry does not allow that relationship between these nodes.")
    after = {
        "from_id": canonical.from_id, "to_id": canonical.to_id, "relation": canonical.relation,
        "facets": db.registry.check_facets(None, canonical.facets, relation=canonical.relation),
    }
    if any(
        row["edge_id"] != before.get("edge_id") and
        (row["from_id"], row["to_id"], row["relation"]) == (after["from_id"], after["to_id"], after["relation"])
        for row in all_edges
    ):
        raise ServiceError("conflict", "This note already records that relationship.")
    return after


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
        raise ServiceError("conflict", "Review the latest processed version of this source note.")
    doc_id = note["doc_id"]
    all_edges = sorted(db.list_note_edges(doc_id), key=lambda item: item["edge_id"])
    edges: list[dict[str, Any]] = []
    person = None
    diff = []
    source_evidence = None
    if kind == "person":
        if not changes or changes.keys() - _PERSON_FIELDS:
            raise ServiceError("invalid", "Choose person details or identity fields.")
        node = db.get_node(record)
        if (
            node is None or node.node_type != "entity" or node.facets.get("entity_type") != "person"
            or doc_id not in db.note_entity_doc_ids(record)
        ):
            raise ServiceError("not_found", "That person is not in the selected note's extraction.")
        before = {"name": node.name, "aliases": node.aliases, **{key: node.facets.get(key) for key in ("role", "organization")}}
        after = before.copy()
        for field, value in changes.items():
            after[field] = edit_aliases(value) if field == "aliases" else edit_text(value, field)
        if keep_previous_name and after["name"] != before["name"]:
            after["aliases"] = [*after["aliases"], node.name]
        after["aliases"] = unique_labels(after["aliases"], excluding=after["name"])
        db.registry.check_metadata(after["name"], node.summary)
        if any(len(alias) > db.registry.metadata_max_length["name"] for alias in after["aliases"]):
            raise ServiceError("invalid", "An alternate name exceeds the name length limit.")
        proposed_labels = set(map(normalize_name_key, [after["name"], *after["aliases"]]))
        prior_labels = set(map(normalize_name_key, [node.name, *node.aliases]))
        if any(
            other.id != node.id and (proposed_labels - prior_labels) & set(map(normalize_name_key, [other.name, *other.aliases]))
            for other in db.list_nodes(node_type="entity", limit=-1)
        ):
            raise ServiceError("conflict", "A proposed name or alternate name identifies another entity.")
        facets = db.registry.check_facets("entity", {
            **node.facets, **{field: after[field] for field in ("role", "organization") if field in changes},
        })
        person = {"before": node.model_dump(mode="json"), "name": after["name"], "aliases": after["aliases"],
                  "facets": facets}
        diff = changed_fields(before, after)

        old_org = before["organization"]
        if any(change["field"] in {"role", "organization"} for change in diff):
            old_company = _organization(db, old_org) if isinstance(old_org, str) else None
            for row in all_edges:
                if row["relation"] != "WORKS_AT" or row["from_id"] != record or row["to_id"] != old_company:
                    continue
                edge_changes = {}
                if before["organization"] != after["organization"]:
                    new_company = _organization(db, after["organization"])
                    if new_company is None:
                        raise ServiceError("invalid", "Choose an unambiguous organization for the supporting employment relationship.")
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
            raise ServiceError("invalid", "Choose relationship fields to change.")
        before = next((row for row in all_edges if row["edge_id"] == edge_id), None)
        if kind == "relationship" and before is None:
            raise ServiceError("not_found", "That relationship is not in the selected note's extraction.")
        if kind == "relationship_add":
            if edge_id or record not in (changes.get("from_id"), changes.get("to_id")):
                raise ServiceError("invalid", "The new relationship must connect to the current record.")
            source_evidence = relationship_source_evidence(db, record).get(doc_id)
            if not source_evidence:
                raise ServiceError("conflict", "Choose a processed source note connected to the current record.")
            before = {}
        assert before is not None
        after = _review_edge(db, before, changes, all_edges=all_edges)
        edges.append({"before": before, "after": after})
        diff = changed_fields(before, after)
    else:
        raise ServiceError("invalid", "Choose a person or relationship correction.")

    if not diff:
        raise ServiceError("invalid", "Change at least one field before reviewing.")
    return {
        "file": file, "expected_hash": digest, "doc_id": doc_id, "ingested_at": note["ingested_at"],
        "registry_revision": db.registry.revision(), "person": person, "edges": edges, "diff": diff,
        **({"source_evidence": source_evidence} if source_evidence else {}),
        "request": {"kind": kind, "record": record, "edge_id": edge_id, "changes": changes,
                    "keep_previous_name": keep_previous_name},
    }
