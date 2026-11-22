"""Deterministic repair of stored ontology data: orphans, relation names, exact duplicates.

Only fixes with a single right answer live here. Judgment calls (unknown relations,
near-duplicate entities) are queued as pending registry suggestions by `audit --sync`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from stock_ontology.db import OntologyDB
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

    @property
    def total_changes(self) -> int:
        return (
            self.orphan_nodes_deleted
            + self.orphan_edges_deleted
            + self.edges_canonicalized
            + self.duplicate_edges_deleted
            + self.nodes_merged
        )


def repair_ontology(db: OntologyDB, registry: OntologyRegistry) -> RepairReport:
    """Apply deterministic repairs to `db` in one transaction and report what changed."""
    if db.read_only:
        raise ValueError("repair_ontology requires a writable OntologyDB.")  # noqa: TRY003
    report = RepairReport()
    with db.transaction():
        _delete_orphan_artifacts(db, report)
        _canonicalize_relations(db, registry, report)
        _merge_exact_duplicates(db, report)
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
    """Rename registered alias relations and flip registered inverse relations."""
    rows = db.conn.execute("SELECT id, from_id, to_id, relation FROM edges").fetchall()
    for row in rows:
        match = registry.resolve_relation(row["relation"])
        if match is None:
            continue
        from_id, to_id = row["from_id"], row["to_id"]
        if match.flip_direction:
            from_id, to_id = to_id, from_id
        if match.canonical == row["relation"] and from_id == row["from_id"]:
            continue
        db.conn.execute(
            "UPDATE edges SET relation = ?, from_id = ?, to_id = ? WHERE id = ?",
            (match.canonical, from_id, to_id, row["id"]),
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
    db.conn.execute("DELETE FROM edges WHERE from_id = to_id AND from_id = ?", (survivor.id,))
    survivor.aliases = aliases
    survivor.facets = facets
    survivor.summary = summary
    db.upsert_node(survivor)


def _delete_duplicate_edges(db: OntologyDB, report: RepairReport) -> None:
    """Keep one edge per (from, to, relation, source doc) after renames and merges."""
    cur = db.conn.execute(
        """
        DELETE FROM edges
        WHERE id NOT IN (
            SELECT MIN(id) FROM edges
            GROUP BY from_id, to_id, relation, IFNULL(source_doc_id, '')
        )
        """
    )
    report.duplicate_edges_deleted += cur.rowcount
