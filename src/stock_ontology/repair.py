"""Deterministic repair of stored ontology data: orphans, relation names, exact duplicates.

Only fixes with a single right answer live here. Judgment calls (unknown relations,
near-duplicate entities) are queued as pending registry suggestions by `audit --sync`.
"""

from __future__ import annotations

import json
import sqlite3
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


def reembed_nodes(db: OntologyDB, llm: Any, node_ids: list[str]) -> int:
    """Recompute and store embeddings for `node_ids` (e.g. merge survivors); returns the count."""
    from stock_ontology.pipeline import node_embedding_text

    if db.read_only:
        raise ValueError("reembed_nodes requires a writable OntologyDB.")  # noqa: TRY003
    nodes = db.get_nodes(node_ids)
    if not nodes:
        return 0
    vectors = llm.embed_texts([node_embedding_text(node) for node in nodes])
    mapping = {node.id: vec for node, vec in zip(nodes, vectors, strict=True)}
    return db.replace_node_embeddings(mapping, prune_orphans=False)


def repair_ontology(db: OntologyDB, registry: OntologyRegistry) -> RepairReport:
    """Apply deterministic repairs to `db` in one transaction and report what changed."""
    if db.read_only:
        raise ValueError("repair_ontology requires a writable OntologyDB.")  # noqa: TRY003
    report = RepairReport()
    with db.transaction():
        _delete_orphan_artifacts(db, report)
        _merge_exact_duplicates(db, report)
        _canonicalize_relations(db, registry, report)
        _delete_duplicate_edges(db, report)
    return report


def _delete_orphan_artifacts(db: OntologyDB, report: RepairReport) -> None:
    """Remove doc-scoped nodes and edges whose document has no ingestion log entry."""
    logged = {entry["doc_id"] for entry in db.get_ingestion_log().values()}
    doc_ids = {
        str(r["source_doc_id"])
        for r in db.conn.execute(
            "SELECT source_doc_id FROM nodes WHERE source_doc_id IS NOT NULL "
            "UNION SELECT source_doc_id FROM edges WHERE source_doc_id IS NOT NULL"
        ).fetchall()
    }
    for doc_id in sorted(doc_ids - logged):
        nodes = db.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE source_doc_id = ?", (doc_id,)
        ).fetchone()[0]
        edges = db.conn.execute(
            """
            SELECT COUNT(*) FROM edges
            WHERE source_doc_id = ?
               OR from_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
               OR to_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
            """,
            (doc_id, doc_id, doc_id),
        ).fetchone()[0]
        db.delete_document_artifacts(doc_id)
        report.orphan_nodes_deleted += int(nodes)
        report.orphan_edges_deleted += int(edges)


def _canonicalize_relations(
    db: OntologyDB, registry: OntologyRegistry, report: RepairReport
) -> None:
    """Canonicalize relation names, alias facets, direction, and symmetry against `registry`."""
    rows = db.conn.execute(
        """
        SELECT
            e.id, e.from_id, e.to_id, e.relation, e.facets_json,
            nf.node_type AS from_type,
            json_extract(nf.facets_json, '$.entity_type') AS from_entity_type,
            nt.node_type AS to_type,
            json_extract(nt.facets_json, '$.entity_type') AS to_entity_type
        FROM edges e
        JOIN nodes nf ON nf.id = e.from_id
        JOIN nodes nt ON nt.id = e.to_id
        """
    ).fetchall()
    for row in rows:
        raw_facets = json.loads(row["facets_json"])
        canon = registry.canonicalize_edge(
            row["relation"],
            from_id=row["from_id"],
            from_type=row["from_type"],
            from_entity_type=row["from_entity_type"],
            to_id=row["to_id"],
            to_type=row["to_type"],
            to_entity_type=row["to_entity_type"],
            facets=raw_facets,
        )
        if (
            canon.relation == row["relation"]
            and canon.from_id == row["from_id"]
            and canon.to_id == row["to_id"]
            and canon.facets == raw_facets
        ):
            continue
        db.conn.execute(
            "UPDATE edges SET relation = ?, from_id = ?, to_id = ?, facets_json = ? WHERE id = ?",
            (canon.relation, canon.from_id, canon.to_id, json.dumps(canon.facets), row["id"]),
        )
        report.edges_canonicalized += 1


def _merge_key(node: Node) -> tuple[str, str]:
    entity_type = str(node.facets.get("entity_type", "")).strip().casefold()
    return node.node_type, entity_type if node.node_type == "entity" else ""


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
        db.conn.execute("UPDATE edges SET from_id = ? WHERE from_id = ?", (survivor.id, loser.id))
        db.conn.execute("UPDATE edges SET to_id = ? WHERE to_id = ?", (survivor.id, loser.id))
        db.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (loser.id,))
        db.conn.execute("DELETE FROM nodes WHERE id = ?", (loser.id,))
        report.nodes_merged += 1

    # Self-loops created by repointing carry no information.
    cur = db.conn.execute("DELETE FROM edges WHERE from_id = to_id AND from_id = ?", (survivor.id,))
    report.self_loops_deleted += max(cur.rowcount, 0)
    report.merged_survivor_ids.append(survivor.id)
    survivor.aliases = aliases
    survivor.facets = facets
    survivor.summary = summary
    db.upsert_node(survivor)


def _delete_duplicate_edges(db: OntologyDB, report: RepairReport) -> None:
    """Merge facets and keep one edge per (from, to, relation, source doc) after renames and merges."""
    rows = db.conn.execute(
        "SELECT id, from_id, to_id, relation, facets_json, source_doc_id FROM edges ORDER BY id ASC"
    ).fetchall()
    groups: dict[tuple[str, str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        key = (
            str(row["from_id"]),
            str(row["to_id"]),
            str(row["relation"]),
            str(row["source_doc_id"] or ""),
        )
        groups[key].append(row)

    for group in groups.values():
        if len(group) <= 1:
            continue
        survivor = group[0]
        merged = json.loads(survivor["facets_json"])
        for extra in group[1:]:
            merged = merge_edge_facets(merged, json.loads(extra["facets_json"]))
        merged_json = json.dumps(merged)
        if merged_json != survivor["facets_json"]:
            db.conn.execute(
                "UPDATE edges SET facets_json = ? WHERE id = ?",
                (merged_json, survivor["id"]),
            )
        extra_ids = [str(extra["id"]) for extra in group[1:]]
        placeholders = ", ".join("?" for _ in extra_ids)
        cur = db.conn.execute(
            f"DELETE FROM edges WHERE id IN ({placeholders})",
            extra_ids,
        )
        report.duplicate_edges_deleted += cur.rowcount
