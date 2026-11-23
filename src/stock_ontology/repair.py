"""Deterministic repair of stored ontology data: orphans, enum facets, relation names, pending edges,
exact duplicates.

Only fixes with a single right answer live here. Judgment calls (unknown relations,
near-duplicate entities) are queued as pending registry suggestions by `audit`.
All reads and writes go through `OntologyDB`; this module issues no SQL.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_ontology.db import OntologyDB, merge_edge_facets
from stock_ontology.models import Edge, Node
from stock_ontology.registry import FacetSchemaError, OntologyRegistry, normalize_name_key
from stock_ontology.vocab import VIEW_TYPE, canonicalize_edge_facets, canonicalize_node_facets, coerce_facet_value


@dataclass
class RepairReport:
    """Counts of rows changed by one repair run; all zero means the DB was already clean."""

    orphan_nodes_deleted: int = 0
    orphan_edges_deleted: int = 0
    # Nodes and edges whose enum facets were mapped to their vocabulary member, or whose optional
    # enum facet outside its vocabulary was dropped (the ingest rule).
    facets_canonicalized: int = 0
    edges_canonicalized: int = 0
    duplicate_edges_deleted: int = 0
    # Edges that had no `basis` and got one: `synthesized` if they touch a consensus view.
    edge_basis_backfilled: int = 0
    # Nodes and edges whose official facets were coerced to their registry kind (`"630"` -> 630).
    facets_migrated: int = 0
    # Money facets rewritten as amount plus currency, and those whose currency could not be determined.
    money_facets_migrated: int = 0
    money_facets_unresolved: int = 0
    nodes_merged: int = 0
    self_loops_deleted: int = 0
    # Pending edges whose relation the registry now maps, written to `edges` and removed from pending.
    pending_edges_promoted: int = 0
    # Registry merge suggestions a human approved and repair applied (`suggestions.merges`).
    approved_merges_applied: int = 0
    # Survivors of merges keep a stale embedding until `reembed_nodes` recomputes it.
    merged_survivor_ids: list[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return (
            self.orphan_nodes_deleted
            + self.orphan_edges_deleted
            + self.facets_canonicalized
            + self.edges_canonicalized
            + self.duplicate_edges_deleted
            + self.edge_basis_backfilled
            + self.facets_migrated
            + self.money_facets_migrated
            + self.nodes_merged
            + self.self_loops_deleted
            + self.pending_edges_promoted
        )



def repair_ontology(db: OntologyDB, registry: OntologyRegistry, data_dir: Path | str | None = None) -> RepairReport:
    """Apply deterministic repairs to `db` in one transaction and report what changed."""
    if db.read_only:
        raise ValueError("repair_ontology requires a writable OntologyDB.")  # noqa: TRY003
    report = RepairReport()
    # Every write is checked against the loaded registry: it may have just approved a relation
    # or endpoint that the DB's built-in default does not know.
    with db.transaction(), db.checking_against(registry):
        _delete_orphan_artifacts(db, report)
        _migrate_money_facets(db, registry, report, data_dir)
        # Before canonicalizing: an edge rewrite has to carry the required `basis`.
        _backfill_edge_basis(db, report)
        _canonicalize_facets(db, registry, report)
        _apply_approved_merges(db, registry, report)
        _merge_exact_duplicates(db, report)
        _canonicalize_relations(db, registry, report)
        _promote_pending_edges(db, registry, report)
        _delete_duplicate_edges(db, report)
        report.facets_migrated = db.migrate_facets(registry)
    return report


def validate_rollout(db: OntologyDB, registry: OntologyRegistry) -> None:
    """Check active graph rows against the proposed registry before recording adoption."""
    for node in db.list_all_nodes():
        try:
            registry.check_metadata(node.name, node.summary)
            registry.check_facets(node.node_type, node.facets)
        except FacetSchemaError as exc:
            raise FacetSchemaError(f"Node {node.id}: {exc}") from exc  # noqa: TRY003
    for edge in db.list_edges_with_endpoints():
        try:
            registry.check_endpoints(
                edge["relation"],
                from_type=edge["from_type"],
                from_entity_type=edge["from_entity_type"],
                to_type=edge["to_type"],
                to_entity_type=edge["to_entity_type"],
            )
            registry.check_facets(None, edge["facets"], relation=edge["relation"])
        except FacetSchemaError as exc:
            raise FacetSchemaError(f"Edge {edge['edge_id']}: {exc}") from exc  # noqa: TRY003


def _delete_orphan_artifacts(db: OntologyDB, report: RepairReport) -> None:
    """Remove doc-scoped nodes and edges whose document has no ingestion log entry."""
    logged = {entry["doc_id"] for entry in db.get_ingestion_log().values()}
    for doc_id in sorted(db.list_artifact_doc_ids() - logged):
        nodes, edges = db.count_document_artifacts(doc_id)
        db.delete_document_artifacts(doc_id)
        report.orphan_nodes_deleted += nodes
        report.orphan_edges_deleted += edges


_MONEY_NUMBER_RE = re.compile(r"\$?\s*(?P<number>[0-9][0-9,]*(?:\.[0-9]+)?[KMBT]?)(?P<plus>\+)?")
_NOTE_CURRENCIES = {"$": "USD", "US$": "USD", "NT$": "TWD", "HK$": "HKD"}


def _note_currency(rel_path: Any, number: str, data_dir: Path | str | None) -> str | None:
    """The one currency the source note writes next to `number`; None if absent or ambiguous."""
    if data_dir is None or not rel_path:
        return None
    root = Path(data_dir).resolve()
    path = (root / str(rel_path)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    plain = number.replace(",", "")
    forms = {plain}
    if plain.isdigit():
        forms.add(f"{int(plain):,}")
    alternatives = "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True))
    pattern = rf"(?<![A-Za-z])(US\$|NT\$|HK\$|\$)\s?(?:{alternatives})(?![0-9,]|\.[0-9]|[A-Za-z])"
    found = {_NOTE_CURRENCIES[m] for m in re.findall(pattern, path.read_text(encoding="utf-8"))}
    return found.pop() if len(found) == 1 else None


def _migrated_money(value: Any, rel_path: Any, data_dir: Path | str | None) -> Any | None:
    """`value` as money, reading a missing currency from the source note; None if unresolved."""
    try:
        return coerce_facet_value("money", value)
    except ValueError:
        match = _MONEY_NUMBER_RE.fullmatch(str(value).strip()) if not isinstance(value, bool) else None
        currency = _note_currency(rel_path, match["number"], data_dir) if match else None
        if currency is None:
            return None
        return coerce_facet_value("money", f"{currency} {match['number']}{match['plus'] or ''}")


def _migrate_money_facets(
    db: OntologyDB, registry: OntologyRegistry, report: RepairReport, data_dir: Path | str | None
) -> None:
    """Rewrite stored money as amount plus currency, reading a missing currency from the source note."""

    def migrate(facets: dict[str, Any], keys: list[str], rel_path: Any) -> dict[str, Any] | None:
        out = dict(facets)
        for key in keys:
            value = out.get(key)
            if value is None:
                continue
            money = _migrated_money(value, rel_path, data_dir)
            if money is None:
                report.money_facets_unresolved += 1
            elif money != value:
                out[key] = money
                report.money_facets_migrated += 1
        return out if out != facets else None

    for node in db.list_all_nodes():
        source = node.facets.get("source")
        rel_path = source.get("file_path") if isinstance(source, dict) else None
        migrated = migrate(node.facets, registry.facet_keys_of_kind(node.node_type, "money"), rel_path)
        if migrated is not None:
            node.facets = migrated
            db.upsert_node(node)
    doc_paths = {entry["doc_id"]: path for path, entry in db.get_ingestion_log().items()}
    for edge in db.list_edges_with_endpoints():
        keys = registry.facet_keys_of_kind(None, "money", relation=edge["relation"])
        migrated = migrate(edge["facets"], keys, doc_paths.get(edge["source_doc_id"])) if keys else None
        if migrated is not None:
            db.update_edge(
                edge["edge_id"],
                relation=edge["relation"],
                from_id=edge["from_id"],
                to_id=edge["to_id"],
                facets=migrated,
            )


def _canonicalize_facets(db: OntologyDB, registry: OntologyRegistry, report: RepairReport) -> None:
    """Map stored enum facets to their vocabulary member; drop an optional enum outside its vocabulary.

    An unknown required subtype is lowercased and kept, for `audit` to report.
    """
    for node in db.list_all_nodes():
        facets = registry.drop_uncoercible_optional(
            node.node_type, canonicalize_node_facets(node.node_type, node.facets), kinds=("enum",)
        )
        if facets != node.facets:
            node.facets = facets
            db.upsert_node(node)
            report.facets_canonicalized += 1
    for edge in db.list_edges_with_endpoints():
        facets = registry.drop_uncoercible_optional(
            None, canonicalize_edge_facets(edge["facets"]), kinds=("enum",), relation=edge["relation"]
        )
        if facets != edge["facets"]:
            db.update_edge(
                edge["edge_id"],
                relation=edge["relation"],
                from_id=edge["from_id"],
                to_id=edge["to_id"],
                facets=facets,
            )
            report.facets_canonicalized += 1


def _backfill_edge_basis(db: OntologyDB, report: RepairReport) -> None:
    """Give every edge without `basis` one: `synthesized` when either end is a consensus view."""
    consensus_ids = {
        n.id
        for n in db.list_all_nodes()
        if n.node_type == "view" and VIEW_TYPE.coerce(n.facets.get("view_type")) == "consensus"
    }
    for edge in db.list_edges_with_endpoints():
        if edge["facets"].get("basis") is not None:
            continue
        synthesized = edge["from_id"] in consensus_ids or edge["to_id"] in consensus_ids
        db.update_edge(
            edge["edge_id"],
            relation=edge["relation"],
            from_id=edge["from_id"],
            to_id=edge["to_id"],
            facets={**edge["facets"], "basis": "synthesized" if synthesized else "extracted"},
        )
        report.edge_basis_backfilled += 1


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


def _promote_pending_edges(db: OntologyDB, registry: OntologyRegistry, report: RepairReport) -> None:
    """Write each pending edge `registry` now allows to `edges`, then drop it from pending.

    The relation, direction and alias facets come from `canonicalize_edge`, as at ingest. A pending
    edge whose relation is still unmapped, or whose endpoints are still not allowed, stays pending.
    """
    promoted: list[str] = []
    for edge in db.list_pending_edges_with_endpoints():
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
        if not canon.matched or not canon.endpoints_ok:
            continue
        db.upsert_edge(
            Edge(
                id=f"edge_{uuid.uuid5(uuid.NAMESPACE_OID, edge['edge_id']).hex}",
                from_id=canon.from_id,
                to_id=canon.to_id,
                relation=canon.relation,
                facets=registry.drop_uncoercible_optional(None, canon.facets, relation=canon.relation),
                source_doc_id=edge["source_doc_id"],
                created_at=datetime.fromisoformat(edge["created_at"]),
            )
        )
        promoted.append(edge["edge_id"])
    report.pending_edges_promoted += db.delete_pending_edges(promoted)


def _merge_key(node: Node) -> tuple[str, str]:
    entity_type = str(node.facets.get("entity_type", ""))
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
                key = normalize_name_key(label)
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
    survivor_key = normalize_name_key(survivor.name)
    aliases = list(survivor.aliases)
    seen = {normalize_name_key(a) for a in aliases} | {survivor_key}
    facets = dict(survivor.facets)
    summary = survivor.summary

    for loser in losers:
        for label in [loser.name, *loser.aliases]:
            key = normalize_name_key(label)
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
