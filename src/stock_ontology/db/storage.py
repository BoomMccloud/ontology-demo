"""Storage layer: the `OntologyDB` connection, writes, and read queries.

Table definitions, row mapping, and facet merge rules live in
`stock_ontology.db.schema`. This module owns how rows are read and written.
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
import uuid
from collections import deque
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlite_vec

from stock_ontology.db.claims import ClaimStore
from stock_ontology.db.jobs import JobStore
from stock_ontology.db.schema import (
    init_schema,
    merge_edge_facets,
    node_meta,
    node_to_dict,
    now_iso,
    row_to_node,
    sql_casefold,
)
from stock_ontology.models import (
    VALID_SENTIMENTS,
    Edge,
    Node,
    NodeType,
    normalize_sentiment,
    resolve_item_sentiment,
)
from stock_ontology.registry import (
    CanonicalEdgeResult,
    FacetSchemaError,
    OntologyRegistry,
    create_minimal_registry,
    normalize_relation_name,
)
from stock_ontology.vocab import (
    is_synthesized_edge,
    matches_signal_filter,
    parse_category_filter,
    parse_filter_values,
    parse_sentiment_filter,
)


REGISTRY_VERSION_KEY = "registry_version"
"""`db_metadata` key holding the registry schema stamp (`OntologyRegistry.schema_stamp`) the stored
facets were migrated to."""
APPLIED_REGISTRY_KEY = "applied_registry"
APPLIED_REVISION_KEY = "applied_registry_revision"
# A second writer (the worker beside an operator command) waits this long for the write lock.
BUSY_TIMEOUT_MS = 10_000


class RegistryChangedError(FacetSchemaError):
    """The applied registry changed since this connection opened: reopen it and retry the work."""


def _edge_rank(relation: Any, edge_facets: dict[str, Any]) -> tuple[int, int]:
    """Rank duplicate edges to one neighbor: prefer a known sentiment, then ABOUT."""
    return (
        1 if normalize_sentiment(edge_facets.get("sentiment")) is not None else 0,
        1 if relation == "ABOUT" else 0,
    )


def _merge_exposure(
    base: dict[str, Any], new: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Merge edge facets and normalize the merged exposure sentiment in place."""
    merged = merge_edge_facets(base, new)
    exp = normalize_sentiment(merged.get("sentiment"))
    if exp is not None:
        merged["sentiment"] = exp
    return merged, exp


class OntologyDB:
    """Single-file SQLite + sqlite-vec graph and vector store."""

    def __init__(
        self,
        db_path: str | Path,
        embedding_dim: int = 768,
        read_only: bool = False,
        registry: OntologyRegistry | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self.embedding_dim = embedding_dim
        self.read_only = read_only
        self.registry: OntologyRegistry = (
            registry if registry is not None else create_minimal_registry()
        )
        self._active_revision: str | None = None
        self._registry_selected = False
        self._tx_depth = 0

        if self.read_only and self.db_path != ":memory:" and not Path(self.db_path).exists():
            raise FileNotFoundError(  # noqa: TRY003
                f"Ontology database does not exist at {self.db_path}. Run `ingest` first."
            )

        if not self.read_only and self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.create_function("so_casefold", 1, sql_casefold, deterministic=True)

        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
        if self.read_only:
            # Strict DB-enforced one-way data flow for the query agent.
            self.conn.execute("PRAGMA query_only = ON;")
        else:
            if self.db_path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL;")
            self._init_schema()
        if self.read_only:
            self.registry = self.applied_registry() or self.registry
        else:
            try:
                self._select_registry(registry)
            except (ValueError, sqlite3.Error):
                self.close()
                raise
        self._registry_selected = True

    def __enter__(self) -> OntologyDB:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self.conn.close()

    @property
    def jobs(self) -> JobStore:
        """Job and consensus-refresh rows on this connection (written only by the worker)."""
        return JobStore(self.conn, self.transaction)

    @property
    def claims(self) -> ClaimStore:
        """Claim graph rows on this connection (written only by the worker's claim jobs)."""
        return ClaimStore(self.conn, self.transaction)

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[None]:
        """Group writes or read-only queries in the outermost transaction."""
        if self._tx_depth == 0 and self.read_only and not self.conn.in_transaction:
            self.conn.execute("BEGIN")
        if self._tx_depth == 0 and not self.read_only and (immediate or self._registry_selected):
            if not self.conn.in_transaction:
                self.conn.execute("BEGIN IMMEDIATE")
            if self.get_metadata(APPLIED_REVISION_KEY) != self._active_revision:
                self.conn.rollback()
                raise RegistryChangedError("The applied registry changed. Reopen the database and retry.")  # noqa: TRY003
        self._tx_depth += 1
        try:
            yield
        except BaseException:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self.conn.rollback()
            raise
        self._tx_depth -= 1
        if self._tx_depth == 0:
            self.conn.commit()

    def _init_schema(self) -> None:
        lookup_existed = self._has_node_lookup()
        init_schema(self.conn, self.embedding_dim)
        self._migrate_schema(backfill_lookup=not lookup_existed)
    def use_registry(self, registry: OntologyRegistry) -> None:
        """Select the applied registry, with a fallback for fresh and legacy stores."""
        self._select_registry(registry)

    def _select_registry(self, fallback: OntologyRegistry | None) -> None:
        applied = self.applied_registry()
        if applied is not None:
            self.registry = applied
            self._active_revision = applied.revision()
            return
        if fallback is None:
            return
        self.registry = fallback
        if self.read_only:
            return
        with self.transaction(immediate=True):
            stamp = self.get_metadata(REGISTRY_VERSION_KEY)
            if stamp == fallback.schema_stamp():
                return
            if stamp is not None or self.conn.execute("SELECT 1 FROM nodes LIMIT 1").fetchone():
                raise FacetSchemaError("This database needs an explicit registry adoption. Run registry-apply.")  # noqa: TRY003
            self.set_metadata(REGISTRY_VERSION_KEY, fallback.schema_stamp())

    def applied_registry(self) -> OntologyRegistry | None:
        payload = self.get_metadata(APPLIED_REGISTRY_KEY)
        return OntologyRegistry.model_validate_json(payload) if payload else None

    def record_registry_adoption(self, registry: OntologyRegistry, from_revision: str | None, plan: str) -> None:
        """Store the full applied version alongside the legacy facet schema stamp."""
        revision = registry.revision()
        confirmed_at = now_iso()
        with self.transaction():
            self.set_metadata(APPLIED_REGISTRY_KEY, json.dumps(registry.official_definitions(), ensure_ascii=False))
            self.set_metadata(APPLIED_REVISION_KEY, revision)
            self.set_metadata(REGISTRY_VERSION_KEY, registry.schema_stamp())
            self.set_metadata(f"registry_rollout:{revision}:{confirmed_at}", json.dumps({
                "from_revision": from_revision,
                "to_revision": revision,
                "plan": plan,
                "confirmed_at": confirmed_at,
            }))

    def copy_to(self, path: Path) -> None:
        """Copy a consistent database snapshot for a disposable migration preview."""
        with closing(sqlite3.connect(path)) as destination:
            self.conn.backup(destination)

    def registry_rollout_rows(self) -> list[str]:
        """Serialize logical migration inputs and effects in deterministic row order."""
        result: list[str] = []
        for table, key in (("nodes", "id"), ("edges", "id"), ("pending_edges", "id"), ("ingestion_log", "file_path")):
            for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY {key}"):
                result.append(json.dumps({"table": table, **dict(row)}, ensure_ascii=False, sort_keys=True))
        return result

    def migrate_facets(self, registry: OntologyRegistry | None = None) -> int:
        """Coerce every stored official facet to its registry kind where lossless.

        Uses `registry` (default: this DB's) without changing what writes are checked against.
        Values that cannot be coerced stay as stored. Returns how many nodes and edges changed.
        """
        reg = registry if registry is not None else self.registry
        changed = 0
        with self.transaction():
            for r in self.conn.execute("SELECT id, node_type, facets_json FROM nodes").fetchall():
                facets = json.loads(r["facets_json"] or "{}")
                migrated = reg.migrate_facets(str(r["node_type"]), facets)
                if migrated != facets:
                    self.conn.execute(
                        "UPDATE nodes SET facets_json = ? WHERE id = ?", (json.dumps(migrated), r["id"])
                    )
                    changed += 1
            for r in self.conn.execute("SELECT id, relation, facets_json FROM edges").fetchall():
                facets = json.loads(r["facets_json"] or "{}")
                migrated = reg.migrate_facets(None, facets, relation=str(r["relation"]))
                if migrated != facets:
                    self.conn.execute(
                        "UPDATE edges SET facets_json = ? WHERE id = ?", (json.dumps(migrated), r["id"])
                    )
                    changed += 1
        return changed

    def _migrate_schema(self, *, backfill_lookup: bool) -> None:
        """Backfill derived data for databases created by older versions.

        Column additions are schema changes and live in `schema.init_schema`.
        """
        with self.transaction():
            # Rebuild when the table is new, or when any node has no lookup row (an interrupted
            # first backfill, or nodes written by code that predates `node_lookup`).
            missing = self.conn.execute(
                "SELECT 1 FROM nodes n WHERE NOT EXISTS "
                "(SELECT 1 FROM node_lookup l WHERE l.node_id = n.id) LIMIT 1"
            ).fetchone()
            if backfill_lookup or missing is not None:
                self.rebuild_node_lookup()

    def _has_node_lookup(self) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'node_lookup'"
            ).fetchone()
            is not None
        )

    def _write_node_lookup(self, node_id: str, node_type: str, name: str, aliases: list[str]) -> None:
        self.conn.execute("DELETE FROM node_lookup WHERE node_id = ?", (node_id,))
        keys = {k for k in (sql_casefold(label) for label in [name, *aliases]) if k}
        self.conn.executemany(
            "INSERT OR IGNORE INTO node_lookup (key, node_id, node_type) VALUES (?, ?, ?)",
            [(key, node_id, node_type) for key in sorted(keys)],
        )

    def rebuild_node_lookup(self) -> int:
        """Recompute the normalized name/alias lookup for every node; returns rows written."""
        with self.transaction():
            self.conn.execute("DELETE FROM node_lookup")
            rows = self.conn.execute("SELECT id, node_type, name, aliases_json FROM nodes").fetchall()
            for r in rows:
                self._write_node_lookup(
                    str(r["id"]), str(r["node_type"]), str(r["name"]), json.loads(r["aliases_json"] or "[]")
                )
            return int(self.conn.execute("SELECT COUNT(*) FROM node_lookup").fetchone()[0])

    # ------------------------------------------------------------------
    # Write Operations (Pipeline only; blocked by SQLite when read_only)
    # ------------------------------------------------------------------

    def upsert_node(self, node: Node, embedding: list[float] | None = None) -> None:
        """Insert or update a node and optionally its embedding vector."""
        if embedding is not None and len(embedding) != self.embedding_dim:
            raise ValueError(  # noqa: TRY003
                f"Embedding dimension mismatch: expected {self.embedding_dim}, got {len(embedding)}"
            )
        self.registry.check_metadata(node.name, node.summary)
        facets = self.registry.check_facets(node.node_type, node.facets)
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO nodes (
                    id, node_type, name, summary, aliases_json, facets_json,
                    source_doc_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    summary = excluded.summary,
                    aliases_json = excluded.aliases_json,
                    facets_json = excluded.facets_json,
                    source_doc_id = excluded.source_doc_id,
                    updated_at = excluded.updated_at
                """,
                (
                    node.id,
                    node.node_type,
                    node.name,
                    node.summary,
                    json.dumps(node.aliases),
                    json.dumps(facets),
                    node.source_doc_id,
                    node.created_at.isoformat(),
                    node.updated_at.isoformat(),
                ),
            )
            self._write_node_lookup(node.id, node.node_type, node.name, node.aliases)
            if embedding is not None:
                vec_blob = sqlite_vec.serialize_float32(embedding)
                self.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (node.id,))
                self.conn.execute(
                    "INSERT INTO node_vectors(node_id, embedding) VALUES (?, ?)",
                    (node.id, vec_blob),
                )

    def upsert_edge(self, edge: Edge) -> str:
        """Insert an edge or update facets if an identical (from, to, relation, doc) exists.

        A relation the registry does not map, or endpoints it does not allow, are refused.
        """
        self.registry.check_relation(edge.relation)
        self._check_edge_endpoints(edge.relation, edge.from_id, edge.to_id)
        norm_rel = normalize_relation_name(edge.relation)
        with self.transaction():
            existing = self.conn.execute(
                """
                SELECT id, facets_json FROM edges
                WHERE from_id = ? AND to_id = ? AND relation = ? AND source_doc_id IS ?
                """,
                (edge.from_id, edge.to_id, norm_rel, edge.source_doc_id),
            ).fetchone()
            if existing is not None:
                existing_facets = json.loads(existing["facets_json"])
                merged_facets = self.registry.check_facets(
                    None, merge_edge_facets(existing_facets, edge.facets), relation=norm_rel
                )
                self.conn.execute(
                    "UPDATE edges SET facets_json = ? WHERE id = ?",
                    (json.dumps(merged_facets), existing["id"]),
                )
                return str(existing["id"])

            facets = self.registry.check_facets(None, edge.facets, relation=norm_rel)
            self.conn.execute(
                """
                INSERT INTO edges (id, from_id, to_id, relation, facets_json, source_doc_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.id,
                    edge.from_id,
                    edge.to_id,
                    norm_rel,
                    json.dumps(facets),
                    edge.source_doc_id,
                    edge.created_at.isoformat(),
                ),
            )
            return edge.id

    @contextmanager
    def checking_against(self, registry: OntologyRegistry) -> Iterator[None]:
        """Check writes in this block against `registry`, without migrating stored rows."""
        previous = self.registry
        self.registry = registry
        try:
            yield
        finally:
            self.registry = previous

    def _check_edge_endpoints(self, relation: str, from_id: str, to_id: str) -> None:
        """Refuse endpoints the relation does not allow. A missing node is left to the foreign key."""
        rows = self.conn.execute(
            "SELECT id, node_type, json_extract(facets_json, '$.entity_type') AS entity_type "
            "FROM nodes WHERE id IN (?, ?)",
            (from_id, to_id),
        ).fetchall()
        by_id = {str(r["id"]): r for r in rows}
        if from_id in by_id and to_id in by_id:
            start, end = by_id[from_id], by_id[to_id]
            self.registry.check_endpoints(
                relation,
                from_type=str(start["node_type"]),
                from_entity_type=start["entity_type"],
                to_type=str(end["node_type"]),
                to_entity_type=end["entity_type"],
            )

    def insert_pending_edge(self, edge: Edge) -> str:
        """Hold an edge whose relation the registry does not map, with its raw relation, out of `edges`."""
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO pending_edges (id, from_id, to_id, relation, facets_json, source_doc_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.id,
                    edge.from_id,
                    edge.to_id,
                    edge.relation,
                    json.dumps(edge.facets),
                    edge.source_doc_id,
                    edge.created_at.isoformat(),
                ),
            )
        return edge.id

    def delete_pending_edges(self, edge_ids: list[str]) -> int:
        """Delete pending edges by id and return how many rows were removed."""
        if not edge_ids:
            return 0
        placeholders = ", ".join("?" for _ in edge_ids)
        with self.transaction():
            cur = self.conn.execute(f"DELETE FROM pending_edges WHERE id IN ({placeholders})", edge_ids)  # noqa: S608
        return cur.rowcount

    def get_doc_affected_company_ids(self, doc_id: str) -> set[str]:
        """Return company entity IDs touched by nodes or edges from `doc_id`."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT n.id
            FROM nodes n
            WHERE n.node_type = 'entity'
              AND json_extract(n.facets_json, '$.entity_type') = 'company'
              AND (
                  n.id IN (SELECT from_id FROM edges WHERE source_doc_id = ?)
                  OR n.id IN (SELECT to_id FROM edges WHERE source_doc_id = ?)
                  OR n.id IN (
                      SELECT e.from_id FROM edges e
                      JOIN nodes dn ON dn.id = e.to_id
                      WHERE dn.source_doc_id = ?
                  )
                  OR n.id IN (
                      SELECT e.to_id FROM edges e
                      JOIN nodes dn ON dn.id = e.from_id
                      WHERE dn.source_doc_id = ?
                  )
              )
            """,
            (doc_id, doc_id, doc_id, doc_id),
        ).fetchall()
        return {str(r["id"]) for r in rows}

    def delete_document_artifacts(self, doc_id: str) -> None:
        """Remove doc-scoped nodes, edges, pending edges, and vectors while keeping canonical entities/themes."""
        with self.transaction():
            self.conn.execute("DELETE FROM note_entities WHERE doc_id = ?", (doc_id,))
            doc_node_rows = self.conn.execute(
                "SELECT id FROM nodes WHERE source_doc_id = ?", (doc_id,)
            ).fetchall()
            doc_node_ids = [str(r["id"]) for r in doc_node_rows]
            for node_id in doc_node_ids:
                self.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (node_id,))

            for table in ("edges", "pending_edges"):
                self.conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE source_doc_id = ?
                       OR from_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
                       OR to_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
                    """,  # noqa: S608
                    (doc_id, doc_id, doc_id),
                )
            self.conn.execute("DELETE FROM nodes WHERE source_doc_id = ?", (doc_id,))

    def list_artifact_doc_ids(self) -> set[str]:
        """Return every `source_doc_id` referenced by a node, an edge, or a pending edge."""
        rows = self.conn.execute(
            "SELECT source_doc_id FROM nodes WHERE source_doc_id IS NOT NULL "
            "UNION SELECT source_doc_id FROM edges WHERE source_doc_id IS NOT NULL "
            "UNION SELECT source_doc_id FROM pending_edges WHERE source_doc_id IS NOT NULL"
        ).fetchall()
        return {str(r["source_doc_id"]) for r in rows}

    def count_document_artifacts(self, doc_id: str) -> tuple[int, int]:
        """Return (nodes, edges) that `delete_document_artifacts(doc_id)` would remove."""
        nodes = self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE source_doc_id = ?", (doc_id,)
        ).fetchone()[0]
        edges = self.conn.execute(
            """
            SELECT COUNT(*) FROM edges
            WHERE source_doc_id = ?
               OR from_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
               OR to_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
            """,
            (doc_id, doc_id, doc_id),
        ).fetchone()[0]
        return int(nodes), int(edges)

    def update_edge(
        self,
        edge_id: str,
        *,
        relation: str,
        from_id: str,
        to_id: str,
        facets: dict[str, Any],
    ) -> None:
        """Overwrite an edge's relation, endpoints, and facets in place; an unmapped relation is refused."""
        self.registry.check_relation(relation)
        self._check_edge_endpoints(relation, from_id, to_id)
        facets = self.registry.check_facets(None, facets, relation=relation)
        with self.transaction():
            self.conn.execute(
                "UPDATE edges SET relation = ?, from_id = ?, to_id = ?, facets_json = ? WHERE id = ?",
                (normalize_relation_name(relation), from_id, to_id, json.dumps(facets), edge_id),
            )

    def merge_node_into(self, loser_id: str, survivor_id: str) -> int:
        """Repoint the loser's edges and claims to the survivor, then delete the loser and its vector.

        Self-loops on the survivor created by the repoint are dropped; returns how many. Copying the loser's
        names and facets onto the survivor is the caller's job (`upsert_node`).
        """
        with self.transaction():
            self.claims.repoint_node(loser_id, survivor_id)
            self.conn.execute(
                "INSERT OR IGNORE INTO note_entities (doc_id, entity_id) "
                "SELECT doc_id, ? FROM note_entities WHERE entity_id = ?",
                (survivor_id, loser_id),
            )
            self.conn.execute(
                "UPDATE edges SET from_id = ? WHERE from_id = ?", (survivor_id, loser_id)
            )
            self.conn.execute("UPDATE edges SET to_id = ? WHERE to_id = ?", (survivor_id, loser_id))
            self.conn.execute("UPDATE pending_edges SET from_id = ? WHERE from_id = ?", (survivor_id, loser_id))
            self.conn.execute("UPDATE pending_edges SET to_id = ? WHERE to_id = ?", (survivor_id, loser_id))
            self.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (loser_id,))
            self.conn.execute("DELETE FROM nodes WHERE id = ?", (loser_id,))
            cur = self.conn.execute(
                "DELETE FROM edges WHERE from_id = to_id AND from_id = ?", (survivor_id,)
            )
            self.conn.execute("DELETE FROM pending_edges WHERE from_id = to_id AND from_id = ?", (survivor_id,))
        return max(cur.rowcount, 0)

    def delete_edges(self, edge_ids: list[str]) -> int:
        """Delete edges by id and return how many rows were removed."""
        if not edge_ids:
            return 0
        placeholders = ", ".join("?" for _ in edge_ids)
        with self.transaction():
            cur = self.conn.execute(f"DELETE FROM edges WHERE id IN ({placeholders})", edge_ids)
        return cur.rowcount

    def upsert_consensus_view(
        self,
        company_id: str,
        view_node: Node,
        embedding: list[float],
        supporting_ids: list[str],
        contradicting_ids: list[str],
    ) -> Node:
        """Store a new active consensus view for `company_id`, superseding any prior one."""
        prior = self.get_entity_consensus(company_id)
        now = datetime.now(UTC)
        view_node.node_type = "view"
        view_node.source_doc_id = None
        view_node.facets["view_type"] = "consensus"
        view_node.facets["status"] = "active"
        view_node.updated_at = now

        supersedes_prior = prior is not None and prior.id != view_node.id
        if supersedes_prior:
            prior.facets["status"] = "superseded"
            prior.updated_at = now
            self.upsert_node(prior)

        self.upsert_node(view_node, embedding=embedding)

        def link(from_id: str, to_id: str, relation: str, facets: dict[str, Any]) -> None:
            self.upsert_edge(
                Edge(
                    id=f"edge_{uuid.uuid4().hex[:12]}",
                    from_id=from_id,
                    to_id=to_id,
                    relation=relation,
                    facets={**facets, "basis": "synthesized"},
                    created_at=now,
                )
            )

        link(view_node.id, company_id, "ABOUT", {"consensus_link": True})
        if supersedes_prior:
            link(view_node.id, prior.id, "SUPERSEDES", {})
        for relation, ids in (("SUPPORTS", supporting_ids), ("CONTRADICTS", contradicting_ids)):
            for sid in ids:
                if sid != view_node.id and self.get_node(sid) is not None:
                    link(sid, view_node.id, relation, {"consensus_evidence": True})

        return view_node

    def get_ingestion_log(self) -> dict[str, dict[str, Any]]:
        """Return ingestion log keyed by relative file_path.

        `size` and `mtime_ns` are None for rows written before they were recorded
        (or when the DB is an older read-only file without those columns).
        """
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(ingestion_log)")}
        has_stat = {"size", "mtime_ns"} <= cols
        select = "file_path, doc_id, content_hash, ingested_at" + (", size, mtime_ns" if has_stat else "")
        rows = self.conn.execute(f"SELECT {select} FROM ingestion_log").fetchall()  # noqa: S608
        return {
            str(r["file_path"]): {
                "file_path": str(r["file_path"]),
                "doc_id": str(r["doc_id"]),
                "content_hash": str(r["content_hash"]),
                "ingested_at": str(r["ingested_at"]),
                "size": r["size"] if has_stat else None,
                "mtime_ns": r["mtime_ns"] if has_stat else None,
            }
            for r in rows
        }

    def get_note_state(self, file_path: str) -> dict[str, Any] | None:
        """Look up one extraction, including on older read-only databases."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(ingestion_log)")}
        recorded = "entities_recorded" if "entities_recorded" in columns else "0 AS entities_recorded"
        row = self.conn.execute(
            f"SELECT doc_id, content_hash, ingested_at, {recorded} FROM ingestion_log WHERE file_path = ?",  # noqa: S608
            (file_path,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_note_entities(self, doc_id: str) -> list[Node]:
        """List canonical entities attributed to one recorded extraction."""
        rows = self.conn.execute(
            "SELECT n.* FROM note_entities ne JOIN nodes n ON n.id = ne.entity_id "
            "WHERE ne.doc_id = ? ORDER BY n.name COLLATE NOCASE, n.id",
            (doc_id,),
        )
        return [row_to_node(row) for row in rows]

    def note_entity_doc_ids(self, entity_id: str) -> set[str]:
        """Return recorded extraction documents that contain the canonical entity."""
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'note_entities'"
        ).fetchone()
        if exists is None:
            return set()
        return {str(row["doc_id"]) for row in self.conn.execute(
            "SELECT doc_id FROM note_entities WHERE entity_id = ?", (entity_id,)
        )}

    def add_note_entities(self, doc_id: str, entity_ids: tuple[str, ...]) -> None:
        with self.transaction():
            self.conn.executemany(
                "INSERT OR IGNORE INTO note_entities (doc_id, entity_id) VALUES (?, ?)",
                [(doc_id, entity_id) for entity_id in entity_ids],
            )

    def remove_note_entity(self, doc_id: str, entity_id: str) -> bool:
        with self.transaction():
            result = self.conn.execute(
                "DELETE FROM note_entities WHERE doc_id = ? AND entity_id = ?", (doc_id, entity_id)
            )
            return result.rowcount != 0

    def relink_note_entity(self, doc_id: str, entity_id: str, replacement_id: str) -> None:
        with self.transaction():
            self.add_note_entities(doc_id, (replacement_id,))
            self.remove_note_entity(doc_id, entity_id)

    def upsert_ingestion_log(
        self,
        file_path: str,
        doc_id: str,
        content_hash: str,
        ingested_at: str | None = None,
        *,
        size: int | None = None,
        mtime_ns: int | None = None,
        entity_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Record or update ingestion state for a source file."""
        ts = ingested_at or now_iso()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO ingestion_log (file_path, doc_id, content_hash, ingested_at, size, mtime_ns, entities_recorded)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    content_hash = excluded.content_hash,
                    ingested_at = excluded.ingested_at,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    entities_recorded = excluded.entities_recorded
                """,
                (file_path, doc_id, content_hash, ts, size, mtime_ns, entity_ids is not None),
            )
            self.conn.execute("DELETE FROM note_entities WHERE doc_id = ?", (doc_id,))
            if entity_ids:
                self.add_note_entities(doc_id, entity_ids)

    def update_ingestion_stat(self, file_path: str, size: int, mtime_ns: int) -> None:
        """Record a file's size and modification time without touching its content state."""
        with self.transaction():
            self.conn.execute(
                "UPDATE ingestion_log SET size = ?, mtime_ns = ? WHERE file_path = ?",
                (size, mtime_ns, file_path),
            )

    def relink_document(
        self, doc_id: str, old_path: str, new_path: str, *, size: int, mtime_ns: int
    ) -> None:
        """Point an ingested document at a new file path without re-extracting it."""
        folder = Path(new_path).parent.as_posix()
        with self.transaction():
            self.conn.execute(
                "UPDATE ingestion_log SET file_path = ?, size = ?, mtime_ns = ? WHERE file_path = ?",
                (new_path, size, mtime_ns, old_path),
            )
            self.conn.execute(
                """
                UPDATE nodes SET facets_json = json_set(facets_json, '$.source.file_path', ?)
                WHERE source_doc_id = ? AND json_type(facets_json, '$.source') = 'object'
                """,
                (new_path, doc_id),
            )
            if folder == ".":
                self.conn.execute(
                    """
                    UPDATE nodes SET facets_json = json_remove(facets_json, '$.source.folder')
                    WHERE source_doc_id = ? AND json_type(facets_json, '$.source') = 'object'
                    """,
                    (doc_id,),
                )
            else:
                self.conn.execute(
                    """
                    UPDATE nodes SET facets_json = json_set(facets_json, '$.source.folder', ?)
                    WHERE source_doc_id = ? AND json_type(facets_json, '$.source') = 'object'
                    """,
                    (folder, doc_id),
                )

    def delete_ingestion_log(self, file_path: str) -> None:
        """Remove an ingestion log record for a deleted file."""
        with self.transaction():
            self.conn.execute("DELETE FROM ingestion_log WHERE file_path = ?", (file_path,))

    def set_metadata(self, key: str, value: str) -> None:
        """Insert or update a metadata key-value pair in `db_metadata`."""
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO db_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_metadata(self, key: str) -> str | None:
        """Fetch a metadata value by key, returning None if absent or uninitialized."""
        try:
            row = self.conn.execute(
                "SELECT value FROM db_metadata WHERE key = ?",
                (key,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return str(row["value"]) if row is not None else None

    def get_all_metadata(self) -> dict[str, str]:
        """Return all stored metadata key-value pairs, or `{}` if table is absent."""
        try:
            rows = self.conn.execute("SELECT key, value FROM db_metadata").fetchall()
        except sqlite3.OperationalError:
            return {}
        return {str(r["key"]): str(r["value"]) for r in rows}

    def replace_node_embeddings(
        self, embeddings: dict[str, list[float]], *, prune_orphans: bool = True
    ) -> int:
        """Atomically replace node embeddings and optionally prune orphaned vector rows."""
        for node_id, vec in embeddings.items():
            if len(vec) != self.embedding_dim:
                raise ValueError(  # noqa: TRY003
                    f"Embedding dimension mismatch for {node_id}: expected {self.embedding_dim}, got {len(vec)}"
                )

        serialized = {
            node_id: sqlite_vec.serialize_float32(vec)
            for node_id, vec in embeddings.items()
        }
        with self.transaction():
            for node_id, vec_blob in serialized.items():
                self.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (node_id,))
                self.conn.execute(
                    "INSERT INTO node_vectors(node_id, embedding) VALUES (?, ?)",
                    (node_id, vec_blob),
                )
            if prune_orphans:
                node_ids = {
                    str(r["id"])
                    for r in self.conn.execute("SELECT id FROM nodes").fetchall()
                }
                vec_ids = [
                    str(r["node_id"])
                    for r in self.conn.execute("SELECT node_id FROM node_vectors").fetchall()
                ]
                for orphan_id in vec_ids:
                    if orphan_id not in node_ids:
                        self.conn.execute(
                            "DELETE FROM node_vectors WHERE node_id = ?", (orphan_id,)
                        )
        return len(embeddings)

    # ------------------------------------------------------------------
    # Read & Graph Traversal Operations
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Node | None:
        """Fetch a single node by ID."""
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return row_to_node(row) if row is not None else None

    def get_nodes(self, node_ids: list[str]) -> list[Node]:
        """Fetch nodes by ID in one query, preserving input order and skipping missing IDs."""
        unique = list(dict.fromkeys(node_ids))
        if not unique:
            return []
        placeholders = ",".join("?" for _ in unique)
        rows = self.conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({placeholders})", unique  # noqa: S608
        ).fetchall()
        by_id = {str(r["id"]): row_to_node(r) for r in rows}
        return [by_id[i] for i in unique if i in by_id]

    def find_nodes_mentioned_in(self, text: str, node_types: tuple[str, ...]) -> list[Node]:
        """Return nodes whose normalized name or alias occurs in `text` as a whole word."""
        haystack = text.casefold()
        if not haystack.strip() or not self._has_node_lookup():
            return []
        placeholders = ",".join("?" for _ in node_types)
        rows = self.conn.execute(
            f"""
            SELECT DISTINCT l.node_id, l.key FROM node_lookup l
            WHERE l.node_type IN ({placeholders}) AND length(l.key) >= 2 AND instr(?, l.key) > 0
            """,  # noqa: S608
            (*node_types, haystack),
        ).fetchall()
        matched: list[str] = []
        for r in rows:
            pattern = r"(?<!\w)" + re.escape(str(r["key"])) + r"(?!\w)"
            if re.search(pattern, haystack):
                matched.append(str(r["node_id"]))
        return self.get_nodes(sorted(set(matched)))

    def find_by_name_or_alias(
        self, name: str, node_type: NodeType | None = None
    ) -> Node | None:
        """Case-insensitive exact match on `name` or any item in `aliases`."""
        target = name.strip().casefold()
        if not target:
            return None
        if self._has_node_lookup():
            sql = """
                SELECT n.* FROM node_lookup l JOIN nodes n ON n.id = l.node_id
                WHERE l.key = :target
            """
            params_l: dict[str, Any] = {"target": target}
            if node_type is not None:
                sql += " AND l.node_type = :node_type"
                params_l["node_type"] = node_type
            sql += " ORDER BY n.updated_at DESC LIMIT 1"
            row = self.conn.execute(sql, params_l).fetchone()
            return row_to_node(row) if row is not None else None
        # Older read-only databases without `node_lookup`: scan names and aliases.
        sql = """
            SELECT * FROM nodes n
            WHERE (
                so_casefold(n.name) = :target
                OR EXISTS (
                    SELECT 1 FROM json_each(n.aliases_json) a
                    WHERE so_casefold(a.value) = :target
                )
            )
        """
        params: dict[str, Any] = {"target": target}
        if node_type is not None:
            sql += " AND n.node_type = :node_type"
            params["node_type"] = node_type
        sql += " ORDER BY n.updated_at DESC LIMIT 1"
        row = self.conn.execute(sql, params).fetchone()
        return row_to_node(row) if row is not None else None

    def list_nodes(self, node_type: NodeType | None = None, limit: int = 100) -> list[Node]:
        """List nodes, optionally filtered by `node_type`."""
        if node_type is not None:
            rows = self.conn.execute(
                "SELECT * FROM nodes WHERE node_type = ? ORDER BY updated_at DESC LIMIT ?",
                (node_type, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM nodes ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row_to_node(r) for r in rows]

    def list_all_nodes(self) -> list[Node]:
        """Return every node in the database ordered by ID."""
        rows = self.conn.execute("SELECT * FROM nodes ORDER BY id ASC").fetchall()
        return [row_to_node(r) for r in rows]

    def vector_search(
        self,
        query_embedding: list[float],
        node_type: NodeType | None = None,
        limit: int = 8,
    ) -> list[tuple[Node, float]]:
        """Cosine similarity search via sqlite-vec, returning `(Node, distance)` pairs."""
        if len(query_embedding) != self.embedding_dim:
            raise ValueError(  # noqa: TRY003
                f"Query embedding dim mismatch: expected {self.embedding_dim}, got {len(query_embedding)}"
            )
        vec_blob = sqlite_vec.serialize_float32(query_embedding)
        fetch_k = limit * 5 if node_type is not None else limit
        rows = self.conn.execute(
            """
            SELECT node_id, distance
            FROM node_vectors
            WHERE embedding MATCH ? AND k = ?
            """,
            (vec_blob, fetch_k),
        ).fetchall()

        distances = {str(row["node_id"]): float(row["distance"]) for row in rows}
        results: list[tuple[Node, float]] = []
        for node in self.get_nodes(list(distances)):
            if node_type is not None and node.node_type != node_type:
                continue
            results.append((node, distances[node.id]))
            if len(results) >= limit:
                break
        return results

    def keyword_search(
        self,
        query: str,
        node_type: NodeType | None = None,
        limit: int = 8,
    ) -> list[Node]:
        """Case-insensitive substring search across name, aliases, summary, and facets."""
        cleaned = query.strip()
        if not cleaned:
            return []
        pattern = f"%{cleaned}%"
        params: list[Any] = [pattern] * 4
        sql = """
            SELECT * FROM nodes
            WHERE (
                name LIKE ?
                OR aliases_json LIKE ?
                OR summary LIKE ?
                OR facets_json LIKE ?
            )
        """
        if node_type is not None:
            sql += " AND node_type = ?"
            params.append(node_type)
        sql += """
            ORDER BY
                CASE WHEN lower(name) LIKE lower(?) THEN 0 ELSE 1 END,
                updated_at DESC
            LIMIT ?
        """
        params += [pattern, limit]
        rows = self.conn.execute(sql, params).fetchall()
        return [row_to_node(r) for r in rows]

    def get_incident_edges(self, node_id: str) -> list[dict[str, Any]]:
        """Return all outgoing and incoming edges for `node_id` with neighbor metadata."""
        rows = self.conn.execute(
            """
            SELECT
                e.id AS edge_id,
                e.from_id,
                e.to_id,
                e.relation,
                e.facets_json AS edge_facets_json,
                e.source_doc_id AS edge_source_doc_id,
                n.id AS neighbor_id,
                n.node_type AS neighbor_type,
                n.name AS neighbor_name,
                n.summary AS neighbor_summary,
                n.aliases_json AS neighbor_aliases_json,
                n.facets_json AS neighbor_facets_json,
                n.source_doc_id AS neighbor_source_doc_id,
                CASE WHEN e.from_id = ? THEN 'outgoing' ELSE 'incoming' END AS direction
            FROM edges e
            JOIN nodes n ON n.id = CASE WHEN e.from_id = ? THEN e.to_id ELSE e.from_id END
            WHERE e.from_id = ? OR e.to_id = ?
            ORDER BY e.created_at DESC
            """,
            (node_id, node_id, node_id, node_id),
        ).fetchall()

        items: list[dict[str, Any]] = []
        for r in rows:
            items.append(
                {
                    "edge_id": r["edge_id"],
                    "direction": r["direction"],
                    "relation": r["relation"],
                    "facets": json.loads(r["edge_facets_json"]),
                    "source_doc_id": r["edge_source_doc_id"],
                    "neighbor": {
                        "id": r["neighbor_id"],
                        "node_type": r["neighbor_type"],
                        "name": r["neighbor_name"],
                        "summary": r["neighbor_summary"],
                        "aliases": json.loads(r["neighbor_aliases_json"]),
                        "facets": json.loads(r["neighbor_facets_json"]),
                        "source_doc_id": r["neighbor_source_doc_id"],
                    },
                }
            )
        return items

    def list_edges_with_endpoints(self) -> list[dict[str, Any]]:
        """Return all edges joined with endpoint node types, names, and entity subtypes."""
        return self._list_with_endpoints("edges")

    def list_pending_edges_with_endpoints(self) -> list[dict[str, Any]]:
        """Return pending (unmapped-relation) edges in the `list_edges_with_endpoints` shape.

        A read-only DB created before `pending_edges` existed has none.
        """
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pending_edges'"
        ).fetchone()
        return self._list_with_endpoints("pending_edges") if exists is not None else []

    def list_note_edges(self, doc_id: str, *, pending: bool = False) -> list[dict[str, Any]]:
        """List relationships extracted from one document, with endpoint names."""
        return self._list_with_endpoints("pending_edges" if pending else "edges", doc_id)

    def _list_with_endpoints(self, table: str, doc_id: str | None = None) -> list[dict[str, Any]]:
        restriction = "WHERE e.source_doc_id = ?" if doc_id is not None else ""
        rows = self.conn.execute(
            f"""
            SELECT
                e.id AS edge_id,
                e.from_id,
                e.to_id,
                e.relation,
                e.facets_json AS edge_facets_json,
                e.source_doc_id,
                e.created_at,
                n1.node_type AS from_type,
                n1.name AS from_name,
                n1.facets_json AS from_facets_json,
                n2.node_type AS to_type,
                n2.name AS to_name,
                n2.facets_json AS to_facets_json
            FROM {table} e
            JOIN nodes n1 ON n1.id = e.from_id
            JOIN nodes n2 ON n2.id = e.to_id
            {restriction}
            ORDER BY e.created_at DESC
            """,  # noqa: S608
            (doc_id,) if doc_id is not None else (),
        ).fetchall()

        edges: list[dict[str, Any]] = []
        for r in rows:
            from_facets = json.loads(r["from_facets_json"])
            to_facets = json.loads(r["to_facets_json"])
            from_et = str(from_facets.get("entity_type") or "") or None
            to_et = str(to_facets.get("entity_type") or "") or None
            edges.append(
                {
                    "edge_id": str(r["edge_id"]),
                    "from_id": str(r["from_id"]),
                    "to_id": str(r["to_id"]),
                    "relation": str(r["relation"]),
                    "facets": json.loads(r["edge_facets_json"]),
                    "source_doc_id": r["source_doc_id"],
                    "created_at": str(r["created_at"]),
                    "from_type": str(r["from_type"]),
                    "from_name": str(r["from_name"]),
                    "from_entity_type": from_et,
                    "to_type": str(r["to_type"]),
                    "to_name": str(r["to_name"]),
                    "to_entity_type": to_et,
                }
            )
        return edges

    def get_node_embeddings(
        self, node_ids: list[str] | None = None
    ) -> dict[str, list[float]]:
        """Return stored float32 embedding vectors keyed by `node_id`."""
        if node_ids is not None:
            cleaned = [str(nid) for nid in node_ids if str(nid)]
            if not cleaned:
                return {}
            placeholders = ", ".join("?" for _ in cleaned)
            rows = self.conn.execute(
                f"SELECT node_id, embedding FROM node_vectors WHERE node_id IN ({placeholders})",
                cleaned,
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT node_id, embedding FROM node_vectors"
            ).fetchall()

        out: dict[str, list[float]] = {}
        for r in rows:
            blob = r["embedding"]
            if not blob:
                continue
            out[str(r["node_id"])] = list(struct.unpack(f"<{len(blob) // 4}f", blob))
        return out

    def get_entity_consensus(self, entity_id: str) -> Node | None:
        """Return the active consensus view node linked to `entity_id`, if any."""
        rows = self.conn.execute(
            """
            SELECT n.*
            FROM nodes n
            JOIN edges e ON e.from_id = n.id
            WHERE e.to_id = ?
              AND e.relation = 'ABOUT'
              AND n.node_type = 'view'
              AND json_extract(n.facets_json, '$.view_type') = 'consensus'
              AND COALESCE(json_extract(n.facets_json, '$.status'), 'active') = 'active'
            ORDER BY n.updated_at DESC
            LIMIT 1
            """,
            (entity_id,),
        ).fetchall()
        return row_to_node(rows[0]) if rows else None

    def _canonicalize_incident_edge(
        self, focus_node: Node | dict[str, Any], item: dict[str, Any]
    ) -> tuple[CanonicalEdgeResult, str]:
        """Project a raw incident edge onto its canonical relation and focus-relative direction."""
        fid, ftype, fet = node_meta(focus_node)
        nid, ntype, net = node_meta(item["neighbor"])
        if item["direction"] == "outgoing":
            raw_from = (fid, ftype, fet)
            raw_to = (nid, ntype, net)
        else:
            raw_from = (nid, ntype, net)
            raw_to = (fid, ftype, fet)

        res = self.registry.canonicalize_edge(
            item["relation"],
            from_id=raw_from[0],
            from_type=raw_from[1],
            from_entity_type=raw_from[2],
            to_id=raw_to[0],
            to_type=raw_to[1],
            to_entity_type=raw_to[2],
            facets=item["facets"],
        )
        if res.symmetric:
            direction = "mutual"
        elif res.from_id == fid:
            direction = "outgoing"
        else:
            direction = "incoming"
        return res, direction

    def get_entity_overview(self, entity_id: str) -> dict[str, Any]:
        """Return full ontology context for an entity: consensus, events, views, themes, peers."""
        entity = self.get_node(entity_id)
        if entity is None:
            raise KeyError(f"Node not found: {entity_id}")  # noqa: TRY003

        consensus = self.get_entity_consensus(entity_id)
        incident = self.get_incident_edges(entity_id)

        events_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        views_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        prior_by_id: dict[str, dict[str, Any]] = {}
        direct_themes_map: dict[str, dict[str, Any]] = {}
        related_map: dict[str, dict[str, Any]] = {}
        seen_theme_ids: set[str] = set()

        for item in incident:
            neighbor = item["neighbor"]
            nid = str(neighbor["id"])
            ntype = neighbor["node_type"]
            edge_info = {
                "relation": item["relation"],
                "direction": item["direction"],
                "edge_facets": item["facets"],
            }
            if ntype == "view" and neighbor["facets"].get("view_type") == "consensus":
                status = neighbor["facets"].get("status", "active")
                if (consensus is None or nid != consensus.id) and status == "superseded":
                    prior_by_id.setdefault(nid, {**neighbor, **edge_info})
            elif ntype in ("event", "view"):
                bucket = events_by_id if ntype == "event" else views_by_id
                rank = _edge_rank(item["relation"], item["facets"])
                if nid not in bucket or rank > bucket[nid][0]:
                    eff_sent, sent_src = resolve_item_sentiment(neighbor["facets"], item["facets"])
                    bucket[nid] = (
                        rank,
                        {
                            **neighbor,
                            **edge_info,
                            "effective_sentiment": eff_sent,
                            "sentiment_source": sent_src,
                        },
                    )
            elif ntype == "theme":
                res, direction = self._canonicalize_incident_edge(entity, item)
                seen_theme_ids.add(nid)
                link_entry = {
                    "relation": res.relation,
                    "direction": direction,
                    "facets": dict(res.facets),
                    "matched": res.matched,
                }
                rank = (1 if res.matched else 0, 1 if direction == "outgoing" else 0)
                existing_theme = direct_themes_map.get(nid)
                if existing_theme is None:
                    merged_facets, exp_sent = _merge_exposure({}, res.facets)
                    direct_themes_map[nid] = {
                        **neighbor,
                        "relation": res.relation,
                        "direction": direction,
                        "edge_facets": merged_facets,
                        "exposure_sentiment": exp_sent,
                        "via": "direct",
                        "links": [link_entry],
                        "_best_rank": rank,
                    }
                else:
                    merged_facets, exp_sent = _merge_exposure(
                        existing_theme["edge_facets"], res.facets
                    )
                    existing_theme["edge_facets"] = merged_facets
                    existing_theme["exposure_sentiment"] = exp_sent
                    if rank > existing_theme["_best_rank"]:
                        existing_theme["_best_rank"] = rank
                        existing_theme["relation"] = res.relation
                        existing_theme["direction"] = direction
                    dup_lk = next(
                        (
                            lk
                            for lk in existing_theme["links"]
                            if lk["relation"] == res.relation and lk["direction"] == direction
                        ),
                        None,
                    )
                    if dup_lk is None:
                        existing_theme["links"].append(link_entry)
                    else:
                        dup_lk["facets"] = merge_edge_facets(dup_lk["facets"], res.facets)
            elif ntype == "entity":
                res, direction = self._canonicalize_incident_edge(entity, item)
                rel_entry = {
                    "relation": res.relation,
                    "direction": direction,
                    "symmetric": res.symmetric,
                    "matched": res.matched,
                    "facets": dict(res.facets),
                }
                existing_peer = related_map.get(nid)
                if existing_peer is None:
                    related_map[nid] = {
                        **neighbor,
                        "relation": res.relation,
                        "direction": direction,
                        "symmetric": res.symmetric,
                        "edge_facets": dict(res.facets),
                        "relationships": [rel_entry],
                    }
                else:
                    dup_rel = next(
                        (
                            r
                            for r in existing_peer["relationships"]
                            if r["relation"] == res.relation and r["direction"] == direction
                        ),
                        None,
                    )
                    if dup_rel is None:
                        existing_peer["relationships"].append(rel_entry)
                    else:
                        dup_rel["facets"] = merge_edge_facets(dup_rel["facets"], res.facets)
                    existing_peer["relationships"].sort(
                        key=lambda r: (0 if r["matched"] else 1, r["relation"], r["direction"])
                    )
                    headline = existing_peer["relationships"][0]
                    existing_peer["relation"] = headline["relation"]
                    existing_peer["direction"] = headline["direction"]
                    existing_peer["symmetric"] = headline["symmetric"]
                    existing_peer["edge_facets"] = headline["facets"]

        events = [pair[1] for pair in events_by_id.values()]
        views = [pair[1] for pair in views_by_id.values()]
        prior_consensuses = list(prior_by_id.values())
        themes: list[dict[str, Any]] = []
        for thm_entry in direct_themes_map.values():
            thm_entry.pop("_best_rank", None)
            themes.append(thm_entry)
        related_entities = list(related_map.values())

        # Also surface themes connected 1-hop through this entity's events or views.
        for linked_item in events + views:
            for sub in self.get_incident_edges(linked_item["id"]):
                sub_nb = sub["neighbor"]
                if sub_nb["node_type"] == "theme" and sub_nb["id"] not in seen_theme_ids:
                    seen_theme_ids.add(sub_nb["id"])
                    sub_res, sub_dir = self._canonicalize_incident_edge(linked_item, sub)
                    sub_facets = dict(sub_res.facets)
                    exp_sent = normalize_sentiment(sub_facets.get("sentiment"))
                    themes.append(
                        {
                            **sub_nb,
                            "relation": sub_res.relation,
                            "direction": sub_dir,
                            "edge_facets": sub_facets,
                            "exposure_sentiment": exp_sent,
                            "via": f"{linked_item['node_type']}: {linked_item['name']}",
                        }
                    )

        signal_stats = self.query_entity_signals(
            entity_id,
            include_consensus=False,
            include_authored=False,
        )
        sentiment_summary = {
            "total_signals": signal_stats["total_matched"],
            "counts_by_sentiment": signal_stats["counts_by_sentiment"],
            "counts_by_node_type": signal_stats["counts_by_node_type"],
            "counts_by_subtype": signal_stats["counts_by_subtype"],
            "unclassified_in_scope": signal_stats["unclassified_in_scope"],
        }

        return {
            "entity": node_to_dict(entity),
            "consensus": node_to_dict(consensus) if consensus is not None else None,
            "prior_consensuses": prior_consensuses,
            "events": events,
            "views": views,
            "themes": themes,
            "related_entities": related_entities,
            "sentiment_summary": sentiment_summary,
        }

    def _collect_entity_signal_items(
        self,
        entity_id: str,
        *,
        include_consensus: bool = False,
        include_authored: bool = False,
    ) -> list[dict[str, Any]]:
        """Collect deduplicated event/view signal items connected to `entity_id`."""
        by_node_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}

        for item in self.get_incident_edges(entity_id):
            neighbor = item["neighbor"]
            ntype = neighbor["node_type"]
            if ntype not in ("event", "view"):
                continue

            rel = str(item["relation"])
            if not include_authored and rel == "AUTHORED_BY":
                continue

            facets = neighbor["facets"]
            if ntype == "view" and facets.get("view_type") == "consensus":
                status = facets.get("status") or "active"
                if not include_consensus or status != "active":
                    continue

            edge_facets = item["facets"]
            rank = _edge_rank(rel, edge_facets)

            nid = str(neighbor["id"])
            if nid in by_node_id and rank <= by_node_id[nid][0]:
                continue

            eff_sent, sent_src = resolve_item_sentiment(facets, edge_facets)
            subtype = facets.get("event_type") if ntype == "event" else facets.get("view_type")
            date_val = facets.get("event_date") or facets.get("as_of")
            enriched = {
                **neighbor,
                "relation": item["relation"],
                "direction": item["direction"],
                "edge_facets": edge_facets,
                "effective_sentiment": eff_sent,
                "sentiment_source": sent_src,
                "node_sentiment": normalize_sentiment(facets.get("sentiment")),
                "date": date_val,
                "subtype": subtype,
            }
            by_node_id[nid] = (rank, enriched)

        return [pair[1] for pair in by_node_id.values()]

    def query_entity_signals(
        self,
        entity_id: str,
        *,
        sentiments: list[str] | None = None,
        node_types: list[str] | None = None,
        categories: list[str] | None = None,
        statuses: list[str] | None = None,
        include_consensus: bool = False,
        include_authored: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Filter and deterministically count event/view signals attached to `entity_id`."""
        entity = self.get_node(entity_id)
        if entity is None:
            raise KeyError(f"Node not found: {entity_id}")  # noqa: TRY003

        norm_sentiments = parse_filter_values(sentiments, parse_sentiment_filter)

        norm_node_types: set[str] | None = None
        if node_types:
            parsed_types = {str(nt).strip().lower() for nt in node_types if str(nt).strip()}
            norm_node_types = parsed_types or None

        norm_categories = parse_filter_values(categories, parse_category_filter)

        norm_statuses: set[str] | None = None
        if statuses:
            parsed_statuses = {str(st).strip().lower() for st in statuses if str(st).strip()}
            norm_statuses = parsed_statuses or None

        d_from = date_from.strip() if date_from and date_from.strip() else None
        d_to = date_to.strip() if date_to and date_to.strip() else None
        include_cons = bool(include_consensus) or bool(norm_categories and "consensus" in norm_categories)

        raw_items = self._collect_entity_signal_items(
            entity_id,
            include_consensus=include_cons,
            include_authored=include_authored,
        )

        scope_items: list[dict[str, Any]] = []
        for item in raw_items:
            if norm_node_types is not None and item["node_type"] not in norm_node_types:
                continue
            item_status = str(item["facets"].get("status") or "")
            if norm_statuses is not None and item_status not in norm_statuses:
                continue
            if not matches_signal_filter(
                item["node_type"], item["facets"], None, categories=norm_categories
            ):
                continue
            if d_from is not None or d_to is not None:
                item_date = str(item.get("date") or "").strip()
                if not item_date:
                    continue
                if d_from is not None and item_date < d_from:
                    continue
                if d_to is not None and item_date > d_to:
                    continue
            scope_items.append(item)

        unclassified_in_scope = sum(
            1 for item in scope_items if item["effective_sentiment"] is None
        )

        matched = [
            item
            for item in scope_items
            if matches_signal_filter(
                item["node_type"],
                item["facets"],
                item["effective_sentiment"],
                sentiments=norm_sentiments,
            )
        ]

        matched.sort(key=lambda item: item["name"].casefold())
        matched.sort(key=lambda item: str(item.get("date") or ""), reverse=True)

        counts_by_sentiment: dict[str, int] = {
            **{s: 0 for s in VALID_SENTIMENTS},
            "unclassified": 0,
        }
        counts_by_node_type: dict[str, int] = {"event": 0, "view": 0}
        counts_by_subtype: dict[str, int] = {}
        rumored_event_count = 0

        for item in matched:
            eff = item["effective_sentiment"] or "unclassified"
            counts_by_sentiment[eff] = counts_by_sentiment.get(eff, 0) + 1
            ntype = item["node_type"]
            counts_by_node_type[ntype] = counts_by_node_type.get(ntype, 0) + 1
            subtype_key = str(item.get("subtype") or ntype)
            counts_by_subtype[subtype_key] = counts_by_subtype.get(subtype_key, 0) + 1
            if (
                ntype == "event"
                and item["facets"].get("status") == "rumored"
            ):
                rumored_event_count += 1

        return {
            "entity": node_to_dict(entity),
            "filters": {
                "sentiments": sorted(norm_sentiments) if norm_sentiments is not None else None,
                "node_types": sorted(norm_node_types) if norm_node_types is not None else None,
                "categories": sorted(norm_categories) if norm_categories is not None else None,
                "statuses": sorted(norm_statuses) if norm_statuses is not None else None,
                "include_consensus": include_cons,
                "include_authored": include_authored,
                "date_from": d_from,
                "date_to": d_to,
            },
            "total_matched": len(matched),
            "counts_by_sentiment": counts_by_sentiment,
            "counts_by_node_type": counts_by_node_type,
            "counts_by_subtype": counts_by_subtype,
            "rumored_event_count": rumored_event_count,
            "unclassified_in_scope": unclassified_in_scope,
            "items": matched,
        }

    def traverse_bfs(
        self,
        start_node_id: str,
        relations: list[str] | None = None,
        max_hops: int = 2,
        limit: int = 40,
    ) -> dict[str, Any]:
        """Breadth-first traversal from `start_node_id` up to `max_hops`."""
        start = self.get_node(start_node_id)
        if start is None:
            raise KeyError(f"Node not found: {start_node_id}")  # noqa: TRY003

        rel_filter = {normalize_relation_name(r) for r in relations} if relations else None
        visited_hops: dict[str, int] = {start.id: 0}
        nodes_by_id: dict[str, dict[str, Any]] = {start.id: {**node_to_dict(start), "hop": 0}}
        nodes_out: list[dict[str, Any]] = [nodes_by_id[start.id]]
        edges_out: list[dict[str, Any]] = []
        edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

        queue: deque[tuple[str, int]] = deque([(start.id, 0)])
        while queue and len(nodes_out) < limit:
            curr_id, hop = queue.popleft()
            if hop >= max_hops:
                continue
            curr_node = nodes_by_id.get(curr_id) or self.get_node(curr_id)
            if curr_node is None:
                continue
            for item in self.get_incident_edges(curr_id):
                res, _ = self._canonicalize_incident_edge(curr_node, item)
                rel = res.relation
                if rel_filter is not None and rel not in rel_filter:
                    continue
                nb = item["neighbor"]
                edge_key = (res.from_id, res.to_id, rel)
                if edge_key not in edges_by_key:
                    edge_entry = {
                        "edge_id": item["edge_id"],
                        "from_id": res.from_id,
                        "to_id": res.to_id,
                        "relation": rel,
                        "facets": dict(res.facets),
                    }
                    edges_by_key[edge_key] = edge_entry
                    edges_out.append(edge_entry)
                else:
                    edges_by_key[edge_key]["facets"] = merge_edge_facets(
                        edges_by_key[edge_key]["facets"], res.facets
                    )
                if nb["id"] not in visited_hops and len(nodes_out) < limit:
                    visited_hops[nb["id"]] = hop + 1
                    node_entry = {**nb, "hop": hop + 1}
                    nodes_by_id[nb["id"]] = node_entry
                    nodes_out.append(node_entry)
                    queue.append((nb["id"], hop + 1))

        return {
            "start_node": node_to_dict(start),
            "nodes": nodes_out,
            "edges": edges_out,
        }

    def find_theme_companies(self, theme_id: str) -> dict[str, Any]:
        """Find the companies a theme affects, directly or through an event or view about it."""
        theme = self.get_node(theme_id)
        if theme is None or theme.node_type != "theme":
            raise KeyError(f"Theme not found: {theme_id}")  # noqa: TRY003

        company_map: dict[str, dict[str, Any]] = {}
        direct_links_by_company: dict[str, dict[str, dict[str, Any]]] = {}
        indirect_seen_by_company: dict[str, set[tuple[str, str, str]]] = {}

        def _ensure_company_entry(company_dict: dict[str, Any]) -> dict[str, Any]:
            cid = company_dict["id"]
            if cid not in company_map:
                consensus = self.get_entity_consensus(cid)
                company_map[cid] = {
                    "company": company_dict,
                    "consensus_stance": consensus.facets.get("stance") if consensus else None,
                    "consensus_summary": consensus.summary if consensus else None,
                    "links": [],
                }
                direct_links_by_company[cid] = {}
                indirect_seen_by_company[cid] = set()
            return company_map[cid]

        def _is_company(node_dict: dict[str, Any]) -> bool:
            return (
                node_dict["node_type"] == "entity"
                and node_dict["facets"].get("entity_type") == "company"
            )

        for item in self.get_incident_edges(theme.id):
            # A synthesized edge is consensus inference, not evidence the theme affects a company.
            if is_synthesized_edge(item.get("facets")):
                continue
            nb = item["neighbor"]
            item_res, _ = self._canonicalize_incident_edge(theme, item)
            if _is_company(nb):
                entry = _ensure_company_entry(nb)
                cid = nb["id"]
                by_rel = direct_links_by_company[cid]
                existing_lk = by_rel.get(item_res.relation)
                if existing_lk is None:
                    merged_facets, exp_sent = _merge_exposure({}, item_res.facets)
                    link_obj = {
                        "via": "direct",
                        "relation": item_res.relation,
                        "direction": "outgoing" if item_res.from_id == cid else "incoming",
                        "facets": merged_facets,
                        "exposure_sentiment": exp_sent,
                    }
                    by_rel[item_res.relation] = link_obj
                    entry["links"].append(link_obj)
                else:
                    merged_facets, exp_sent = _merge_exposure(existing_lk["facets"], item_res.facets)
                    existing_lk["facets"] = merged_facets
                    existing_lk["exposure_sentiment"] = exp_sent
            elif nb["node_type"] in ("event", "view"):
                for sub in self.get_incident_edges(nb["id"]):
                    sub_nb = sub["neighbor"]
                    if _is_company(sub_nb) and not is_synthesized_edge(sub.get("facets")):
                        entry = _ensure_company_entry(sub_nb)
                        sub_res, _ = self._canonicalize_incident_edge(nb, sub)
                        ind_key = (nb["id"], sub_res.relation, item_res.relation)
                        if ind_key in indirect_seen_by_company[sub_nb["id"]]:
                            continue
                        indirect_seen_by_company[sub_nb["id"]].add(ind_key)
                        entry["links"].append(
                            {
                                "via": f"{nb['node_type']}: {nb['name']}",
                                "via_node_id": nb["id"],
                                "theme_relation": item_res.relation,
                                "entity_relation": sub_res.relation,
                                "source": nb["facets"].get("source"),
                                "facets": nb["facets"],
                            }
                        )

        return {
            "theme": node_to_dict(theme),
            "companies": list(company_map.values()),
        }

    def get_known_facet_keys(self) -> dict[str, list[str]]:
        """Collect existing facet keys per node type so extraction reuses established keys."""
        keys_by_type: dict[str, set[str]] = {
            "entity": set(),
            "event": set(),
            "view": set(),
            "theme": set(),
        }
        rows = self.conn.execute("SELECT node_type, facets_json FROM nodes").fetchall()
        for row in rows:
            ntype = str(row["node_type"])
            facets = json.loads(row["facets_json"])
            for k in facets:
                if k != "source":
                    keys_by_type.setdefault(ntype, set()).add(k)
        return {k: sorted(v) for k, v in keys_by_type.items()}

    def get_stats(self) -> dict[str, Any]:
        """Return summary counts of nodes, edges, consensus views, and ingested files."""
        node_counts = {"entity": 0, "event": 0, "view": 0, "theme": 0}
        for row in self.conn.execute(
            "SELECT node_type, COUNT(*) AS c FROM nodes GROUP BY node_type"
        ).fetchall():
            node_counts[str(row["node_type"])] = int(row["c"])

        edge_count = int(self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
        consensus_count = int(
            self.conn.execute(
                """
                SELECT COUNT(*) FROM nodes
                WHERE node_type = 'view'
                  AND json_extract(facets_json, '$.view_type') = 'consensus'
                  AND COALESCE(json_extract(facets_json, '$.status'), 'active') = 'active'
                """
            ).fetchone()[0]
        )
        file_count = int(self.conn.execute("SELECT COUNT(*) FROM ingestion_log").fetchone()[0])
        return {
            "nodes": node_counts,
            "total_nodes": sum(node_counts.values()),
            "total_edges": edge_count,
            "active_consensus_views": consensus_count,
            "ingested_files": file_count,
        }

    def get_doc_node_counts(self) -> dict[str, dict[str, int]]:
        """Return `{doc_id: {'event': e, 'view': v, 'total': total}}` for ingested documents."""
        rows = self.conn.execute(
            """
            SELECT source_doc_id, node_type, COUNT(*) AS c
            FROM nodes
            WHERE source_doc_id IS NOT NULL
            GROUP BY source_doc_id, node_type
            """
        ).fetchall()
        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            doc_id = str(row["source_doc_id"])
            ntype = str(row["node_type"])
            cnt = int(row["c"])
            entry = counts.setdefault(doc_id, {"event": 0, "view": 0, "total": 0})
            entry[ntype] = entry.get(ntype, 0) + cnt
            entry["total"] += cnt
        return counts

    def get_entity_document_links(
        self, entity_type: str | None = None
    ) -> dict[str, list[dict[str, str | None]]]:
        """Return document provenance links for entities via incident edges and neighboring nodes."""
        where_type = ""
        params: list[Any] = []
        if entity_type is not None:
            where_type = "AND json_extract(ent.facets_json, '$.entity_type') = ?"
            params.append(entity_type.strip().lower())

        sql = f"""
            SELECT
                ent.id AS entity_id,
                e.relation AS relation,
                COALESCE(e.source_doc_id, nb.source_doc_id) AS doc_id,
                json_extract(nb.facets_json, '$.source.file_path') AS neighbor_file_path
            FROM nodes ent
            JOIN edges e ON (e.from_id = ent.id OR e.to_id = ent.id)
            JOIN nodes nb ON nb.id = CASE WHEN e.from_id = ent.id THEN e.to_id ELSE e.from_id END
            WHERE ent.node_type = 'entity'
              {where_type}
              AND (
                  e.source_doc_id IS NOT NULL
                  OR nb.source_doc_id IS NOT NULL
                  OR json_extract(nb.facets_json, '$.source.file_path') IS NOT NULL
              )
        """
        rows = self.conn.execute(sql, params).fetchall()
        links: dict[str, list[dict[str, str | None]]] = {}
        for row in rows:
            eid = str(row["entity_id"])
            links.setdefault(eid, []).append(
                {
                    "relation": str(row["relation"]),
                    "doc_id": str(row["doc_id"]) if row["doc_id"] is not None else None,
                    "file_path": (
                        str(row["neighbor_file_path"])
                        if row["neighbor_file_path"] is not None
                        else None
                    ),
                }
            )
        return links

    def get_edge_schema_summary(self) -> list[dict[str, Any]]:
        """Return aggregated edge schema triples `(from_type, relation, to_type, count)`."""
        rows = self.conn.execute(
            """
            SELECT nf.node_type AS from_type, e.relation AS relation, nt.node_type AS to_type, COUNT(*) AS count
            FROM edges e
            JOIN nodes nf ON nf.id = e.from_id
            JOIN nodes nt ON nt.id = e.to_id
            GROUP BY nf.node_type, e.relation, nt.node_type
            ORDER BY count DESC, e.relation ASC
            """
        ).fetchall()
        return [
            {
                "from_type": str(r["from_type"]),
                "relation": str(r["relation"]),
                "to_type": str(r["to_type"]),
                "count": int(r["count"]),
            }
            for r in rows
        ]

    def get_node_edge_counts(self) -> dict[str, int]:
        """Return total incident edge count per node ID."""
        rows = self.conn.execute(
            """
            SELECT node_id, COUNT(*) AS c
            FROM (
                SELECT from_id AS node_id FROM edges
                UNION ALL
                SELECT to_id AS node_id FROM edges
            )
            GROUP BY node_id
            """
        ).fetchall()
        return {str(r["node_id"]): int(r["c"]) for r in rows}

    def get_entity_connected_nodes(self, entity_id: str) -> dict[str, dict[str, Any] | None]:
        """Return `{node_id: best_edge_facets_or_none}` for `entity_id` and its 1-hop neighbors."""
        connected: dict[str, dict[str, Any] | None] = {entity_id: None}
        best_ranks: dict[str, tuple[int, int]] = {}
        for item in self.get_incident_edges(entity_id):
            nb_id = str(item["neighbor"]["id"])
            if nb_id == entity_id:
                continue
            edge_facets = item["facets"]
            rank = _edge_rank(item["relation"], edge_facets)
            if nb_id not in best_ranks or rank > best_ranks[nb_id]:
                best_ranks[nb_id] = rank
                connected[nb_id] = edge_facets
        return connected

    def get_relation_node_ids(self, relation: str, *, entity_id: str | None = None) -> set[str]:
        """Return IDs of nodes with at least one incident edge of `relation`.

        With `entity_id`, only the entity's neighbors joined to it by such an edge, so a
        neighbor keeps every relation it has with the entity, not just its best edge.
        """
        if entity_id is None:
            rows = self.conn.execute(
                "SELECT from_id AS node_id FROM edges WHERE relation = ? "
                "UNION SELECT to_id AS node_id FROM edges WHERE relation = ?",
                (relation, relation),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT CASE WHEN from_id = ? THEN to_id ELSE from_id END AS node_id FROM edges "
                "WHERE relation = ? AND (from_id = ? OR to_id = ?)",
                (entity_id, relation, entity_id, entity_id),
            ).fetchall()
        ids = {str(r["node_id"]) for r in rows}
        if entity_id is not None:
            ids.discard(entity_id)
        return ids
