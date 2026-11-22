"""Deterministic repair of stored ontology data: orphans, relation names, exact duplicates.

Only fixes with a single right answer live here. Judgment calls (unknown relations,
near-duplicate entities) are queued as pending registry suggestions by `audit`.
All reads and writes go through `OntologyDB`; this module issues no SQL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from stock_ontology.db import OntologyDB, merge_edge_facets
from stock_ontology.models import Node
from stock_ontology.registry import OntologyRegistry


@dataclass
class RepairReport:
    """Counts of rows changed by one repair run; all zero means the DB was already clean."""

    orphan_nodes_deleted: int = 0
    orphan_edges_deleted: int = 0
    edges_canonicalized: int = 0
    duplicate_edges_deleted: int = 0
    nodes_merged: int = 0
    self_loops_deleted: int = 0
    # Registry merge suggestions a human approved and repair applied (`suggestions.merges`).
    approved_merges_applied: int = 0
    # Survivors of merges keep a stale embedding until `reembed_nodes` recomputes it.
    merged_survivor_ids: list[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            self.orphan_nodes_deleted
            + self.orphan_edges_deleted
            + self.edges_canonicalized
            + self.duplicate_edges_deleted
            + self.nodes_merged
            + self.self_loops_deleted
        )



def repair_ontology(db: OntologyDB, registry: OntologyRegistry) -> RepairReport:
    """Apply deterministic repairs to `db` in one transaction and report what changed."""
    if db.read_only:
        raise ValueError("repair_ontology requires a writable OntologyDB.")  # noqa: TRY003
    report = RepairReport()
    with db.transaction():
        _delete_orphan_artifacts(db, report)
        _apply_approved_merges(db, registry, report)
        _merge_exact_duplicates(db, report)
        _canonicalize_relations(db, registry, report)
        _delete_duplicate_edges(db, report)
    return report


def _delete_orphan_artifacts(db: OntologyDB, report: RepairReport) -> None:
    """Remove doc-scoped nodes and edges whose document has no ingestion log entry."""
    logged = {entry["doc_id"] for entry in db.get_ingestion_log().values()}
    for doc_id in sorted(db.list_artifact_doc_ids() - logged):
        nodes, edges = db.count_document_artifacts(doc_id)
        db.delete_document_artifacts(doc_id)
        report.orphan_nodes_deleted += nodes
        report.orphan_edges_deleted += edges


def _canonicalize_relations(
    db: OntologyDB, registry: OntologyRegistry, report: RepairReport
) -> None:
    """Canonicalize relation names, alias facets, direction, and symmetry against `registry`."""
    for edge in db.list_edges_with_endpoints():
        canon = registry.canonicalize_edge(
            edge["relation"],
            from_id=edge["from_id"],
            from_type=edge["from_type"],
            from_entity_type=edge["from_entity_type"],
            to_id=edge["to_id"],
            to_type=edge["to_type"],
            to_entity_type=edge["to_entity_type"],
            facets=edge["facets"],
        )
        if (
            canon.relation == edge["relation"]
            and canon.from_id == edge["from_id"]
            and canon.to_id == edge["to_id"]
            and canon.facets == edge["facets"]
        ):
            continue
        db.update_edge(
            edge["edge_id"],
            relation=canon.relation,
            from_id=canon.from_id,
            to_id=canon.to_id,
            facets=canon.facets,
        )
        report.edges_canonicalized += 1


def _merge_key(node: Node) -> tuple[str, str]:
    entity_type = str(node.facets.get("entity_type", "")).strip().casefold()
    return node.node_type, entity_type if node.node_type == "entity" else ""


def _apply_approved_merges(db: OntologyDB, registry: OntologyRegistry, report: RepairReport) -> None:
    """Merge the node pairs of registry merge suggestions a human approved; skip all others."""
    for suggestion in registry.suggestions.merges:
        if suggestion.status != "approved":
            continue
        nodes = db.get_nodes([suggestion.node_a_id, suggestion.node_b_id])
        if len(nodes) != 2 or nodes[0].node_type != nodes[1].node_type:
            continue  # Already merged by an earlier run, deleted, or not a mergeable pair.
        _merge_cluster(db, nodes, report)
        report.approved_merges_applied += 1


def _merge_exact_duplicates(db: OntologyDB, report: RepairReport) -> None:
    """Merge entities/themes of the same type whose names or aliases match exactly."""
    groups: dict[tuple[str, str], list[Node]] = defaultdict(list)
    for node in db.list_all_nodes():
        if node.node_type in ("entity", "theme"):
            groups[_merge_key(node)].append(node)

    for nodes in groups.values():
        parent = {node.id: node.id for node in nodes}

        def find(node_id: str) -> str:
            while parent[node_id] != node_id:
                parent[node_id] = parent[parent[node_id]]
                node_id = parent[node_id]
            return node_id

        owner_by_key: dict[str, str] = {}
        for node in nodes:
            for label in [node.name, *node.aliases]:
                key = label.strip().casefold()
                if not key:
                    continue
                if key in owner_by_key:
                    parent[find(node.id)] = find(owner_by_key[key])
                else:
                    owner_by_key[key] = node.id

        clusters: dict[str, list[Node]] = defaultdict(list)
        for node in nodes:
            clusters[find(node.id)].append(node)
        for cluster in clusters.values():
            if len(cluster) > 1:
                _merge_cluster(db, cluster, report)


def _merge_cluster(db: OntologyDB, cluster: list[Node], report: RepairReport) -> None:
    cluster.sort(key=lambda n: (n.created_at, n.id))
    survivor, losers = cluster[0], cluster[1:]
    survivor_key = survivor.name.strip().casefold()
    aliases = list(survivor.aliases)
    seen = {a.strip().casefold() for a in aliases} | {survivor_key}
    facets = dict(survivor.facets)
    summary = survivor.summary

    for loser in losers:
        for label in [loser.name, *loser.aliases]:
            key = label.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                aliases.append(label.strip())
        for k, v in loser.facets.items():
            if k not in facets or facets[k] in (None, "", []):
                facets[k] = v
        if not summary and loser.summary:
            summary = loser.summary
        report.self_loops_deleted += db.merge_node_into(loser.id, survivor.id)
        report.nodes_merged += 1

    report.merged_survivor_ids.append(survivor.id)
    survivor.aliases = aliases
    survivor.facets = facets
    survivor.summary = summary
    db.upsert_node(survivor)


def _delete_duplicate_edges(db: OntologyDB, report: RepairReport) -> None:
    """Merge facets and keep one edge per (from, to, relation, source doc) after renames and merges."""
    edges = sorted(db.list_edges_with_endpoints(), key=lambda e: e["edge_id"])
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        key = (edge["from_id"], edge["to_id"], edge["relation"], str(edge["source_doc_id"] or ""))
        groups[key].append(edge)

    for group in groups.values():
        if len(group) <= 1:
            continue
        survivor = group[0]
        merged = survivor["facets"]
        for extra in group[1:]:
            merged = merge_edge_facets(merged, extra["facets"])
        if merged != survivor["facets"]:
            db.update_edge(
                survivor["edge_id"],
                relation=survivor["relation"],
                from_id=survivor["from_id"],
                to_id=survivor["to_id"],
                facets=merged,
            )
        report.duplicate_edges_deleted += db.delete_edges(
            [extra["edge_id"] for extra in group[1:]]
        )
