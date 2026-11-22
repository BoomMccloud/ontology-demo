"""SQLite + sqlite-vec storage layer for the 4-node stock ontology."""

from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlite_vec

from stock_ontology.models import (
    VALID_SENTIMENTS,
    Edge,
    Node,
    NodeType,
    normalize_sentiment,
    resolve_item_sentiment,
)

SECOND_ORDER_ENTITY_RELATIONS = {
    "SUPPLIES_TO",
    "CUSTOMER_OF",
    "COMPETES_WITH",
    "PARTNERS_WITH",
    "SUBSIDIARY_OF",
    "OWNS",
}

THEME_EXPOSURE_RELATIONS = {
    "BENEFITS_FROM",
    "HURT_BY",
    "EXPOSED_TO",
    "RELATES_TO",
}

SIGNAL_CATEGORY_ALIASES: dict[str, str] = {
    "rumor": "rumor",
    "rumors": "rumor",
    "news": "news",
    "fact": "fact",
    "facts": "fact",
    "earnings": "earnings",
    "catalyst": "catalyst",
    "catalysts": "catalyst",
    "meeting": "meeting",
    "meetings": "meeting",
    "analyst_report": "analyst_report",
    "analyst_reports": "analyst_report",
    "pm_view": "pm_view",
    "pm_views": "pm_view",
    "channel_check": "channel_check",
    "channel_checks": "channel_check",
    "consensus": "consensus",
}


def _sql_casefold(value: Any) -> str | None:
    """SQL helper matching Python `str.strip().casefold()` for name/alias lookups."""
    return value.strip().casefold() if isinstance(value, str) else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _node_to_dict(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "name": node.name,
        "summary": node.summary,
        "aliases": node.aliases,
        "facets": node.facets,
        "source_doc_id": node.source_doc_id,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


class OntologyDB:
    """Single-file SQLite + sqlite-vec graph and vector store."""

    def __init__(
        self,
        db_path: str | Path,
        embedding_dim: int = 768,
        read_only: bool = False,
    ) -> None:
        self.db_path = str(db_path)
        self.embedding_dim = embedding_dim
        self.read_only = read_only
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
        self.conn.create_function("so_casefold", 1, _sql_casefold, deterministic=True)

        self.conn.execute("PRAGMA foreign_keys = ON;")
        if self.read_only:
            # Strict DB-enforced one-way data flow for the query agent.
            self.conn.execute("PRAGMA query_only = ON;")
        else:
            if self.db_path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL;")
            self._init_schema()

    def __enter__(self) -> OntologyDB:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group writes into one atomic unit; only the outermost scope commits or rolls back."""
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
        with self.conn:
            self.conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL CHECK(node_type IN ('entity', 'event', 'view', 'theme')),
                    name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    facets_json TEXT NOT NULL DEFAULT '{{}}',
                    source_doc_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    from_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    to_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    relation TEXT NOT NULL,
                    facets_json TEXT NOT NULL DEFAULT '{{}}',
                    source_doc_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS node_vectors USING vec0(
                    node_id TEXT PRIMARY KEY,
                    embedding float[{self.embedding_dim}] distance_metric=cosine
                );

                CREATE TABLE IF NOT EXISTS ingestion_log (
                    file_path TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS db_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
                CREATE INDEX IF NOT EXISTS idx_nodes_doc ON nodes(source_doc_id);
                CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
                CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
                CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
                CREATE INDEX IF NOT EXISTS idx_edges_doc ON edges(source_doc_id);
                """
            )

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        return Node(
            id=row["id"],
            node_type=row["node_type"],
            name=row["name"],
            summary=row["summary"],
            aliases=json.loads(row["aliases_json"]),
            facets=json.loads(row["facets_json"]),
            source_doc_id=row["source_doc_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        return Edge(
            id=row["id"],
            from_id=row["from_id"],
            to_id=row["to_id"],
            relation=row["relation"],
            facets=json.loads(row["facets_json"]),
            source_doc_id=row["source_doc_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ------------------------------------------------------------------
    # Write Operations (Pipeline only; blocked by SQLite when read_only)
    # ------------------------------------------------------------------

    def upsert_node(self, node: Node, embedding: list[float] | None = None) -> None:
        """Insert or update a node and optionally its embedding vector."""
        if embedding is not None and len(embedding) != self.embedding_dim:
            raise ValueError(  # noqa: TRY003
                f"Embedding dimension mismatch: expected {self.embedding_dim}, got {len(embedding)}"
            )
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
                    json.dumps(node.facets),
                    node.source_doc_id,
                    node.created_at.isoformat(),
                    node.updated_at.isoformat(),
                ),
            )
            if embedding is not None:
                vec_blob = sqlite_vec.serialize_float32(embedding)
                self.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (node.id,))
                self.conn.execute(
                    "INSERT INTO node_vectors(node_id, embedding) VALUES (?, ?)",
                    (node.id, vec_blob),
                )

    def upsert_edge(self, edge: Edge) -> str:
        """Insert an edge or update facets if an identical (from, to, relation, doc) exists."""
        norm_rel = edge.relation.strip().upper().replace(" ", "_")
        with self.transaction():
            existing = self.conn.execute(
                """
                SELECT id FROM edges
                WHERE from_id = ? AND to_id = ? AND relation = ? AND source_doc_id IS ?
                """,
                (edge.from_id, edge.to_id, norm_rel, edge.source_doc_id),
            ).fetchone()
            if existing is not None:
                self.conn.execute(
                    "UPDATE edges SET facets_json = ? WHERE id = ?",
                    (json.dumps(edge.facets), existing["id"]),
                )
                return str(existing["id"])

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
                    json.dumps(edge.facets),
                    edge.source_doc_id,
                    edge.created_at.isoformat(),
                ),
            )
            return edge.id

    def get_doc_affected_company_ids(self, doc_id: str) -> set[str]:
        """Return company entity IDs touched by nodes or edges from `doc_id`."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT n.id
            FROM nodes n
            WHERE n.node_type = 'entity'
              AND lower(COALESCE(json_extract(n.facets_json, '$.entity_type'), '')) = 'company'
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
        """Remove doc-scoped nodes, edges, and vectors while keeping canonical entities/themes."""
        with self.transaction():
            doc_node_rows = self.conn.execute(
                "SELECT id FROM nodes WHERE source_doc_id = ?", (doc_id,)
            ).fetchall()
            doc_node_ids = [str(r["id"]) for r in doc_node_rows]
            for node_id in doc_node_ids:
                self.conn.execute("DELETE FROM node_vectors WHERE node_id = ?", (node_id,))

            self.conn.execute(
                """
                DELETE FROM edges
                WHERE source_doc_id = ?
                   OR from_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
                   OR to_id IN (SELECT id FROM nodes WHERE source_doc_id = ?)
                """,
                (doc_id, doc_id, doc_id),
            )
            self.conn.execute("DELETE FROM nodes WHERE source_doc_id = ?", (doc_id,))

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

        if prior is not None and prior.id != view_node.id:
            prior.facets["status"] = "superseded"
            prior.updated_at = now
            self.upsert_node(prior)

        self.upsert_node(view_node, embedding=embedding)

        self.upsert_edge(
            Edge(
                id=f"edge_{uuid.uuid4().hex[:12]}",
                from_id=view_node.id,
                to_id=company_id,
                relation="ABOUT",
                facets={"consensus_link": True},
                source_doc_id=None,
                created_at=now,
            )
        )

        if prior is not None and prior.id != view_node.id:
            self.upsert_edge(
                Edge(
                    id=f"edge_{uuid.uuid4().hex[:12]}",
                    from_id=view_node.id,
                    to_id=prior.id,
                    relation="SUPERSEDES",
                    facets={},
                    source_doc_id=None,
                    created_at=now,
                )
            )

        for sid in supporting_ids:
            if sid != view_node.id and self.get_node(sid) is not None:
                self.upsert_edge(
                    Edge(
                        id=f"edge_{uuid.uuid4().hex[:12]}",
                        from_id=sid,
                        to_id=view_node.id,
                        relation="SUPPORTS",
                        facets={"consensus_evidence": True},
                        source_doc_id=None,
                        created_at=now,
                    )
                )

        for cid in contradicting_ids:
            if cid != view_node.id and self.get_node(cid) is not None:
                self.upsert_edge(
                    Edge(
                        id=f"edge_{uuid.uuid4().hex[:12]}",
                        from_id=cid,
                        to_id=view_node.id,
                        relation="CONTRADICTS",
                        facets={"consensus_evidence": True},
                        source_doc_id=None,
                        created_at=now,
                    )
                )

        return view_node

    def get_ingestion_log(self) -> dict[str, dict[str, str]]:
        """Return ingestion log keyed by relative file_path."""
        rows = self.conn.execute(
            "SELECT file_path, doc_id, content_hash, ingested_at FROM ingestion_log"
        ).fetchall()
        return {
            str(r["file_path"]): {
                "file_path": str(r["file_path"]),
                "doc_id": str(r["doc_id"]),
                "content_hash": str(r["content_hash"]),
                "ingested_at": str(r["ingested_at"]),
            }
            for r in rows
        }

    def upsert_ingestion_log(
        self, file_path: str, doc_id: str, content_hash: str, ingested_at: str | None = None
    ) -> None:
        """Record or update ingestion state for a source file."""
        ts = ingested_at or _now_iso()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO ingestion_log (file_path, doc_id, content_hash, ingested_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    content_hash = excluded.content_hash,
                    ingested_at = excluded.ingested_at
                """,
                (file_path, doc_id, content_hash, ts),
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
        return self._row_to_node(row) if row is not None else None

    def find_by_name_or_alias(
        self, name: str, node_type: NodeType | None = None
    ) -> Node | None:
        """Case-insensitive exact match on `name` or any item in `aliases`."""
        target = name.strip().casefold()
        if not target:
            return None
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
        return self._row_to_node(row) if row is not None else None

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
        return [self._row_to_node(r) for r in rows]

    def list_all_nodes(self) -> list[Node]:
        """Return every node in the database ordered by ID."""
        rows = self.conn.execute("SELECT * FROM nodes ORDER BY id ASC").fetchall()
        return [self._row_to_node(r) for r in rows]

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

        results: list[tuple[Node, float]] = []
        for row in rows:
            node = self.get_node(str(row["node_id"]))
            if node is None:
                continue
            if node_type is not None and node.node_type != node_type:
                continue
            results.append((node, float(row["distance"])))
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
        params: list[Any] = [pattern, pattern, pattern, pattern, pattern]
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
            params_query = [pattern, pattern, pattern, pattern, node_type, pattern, limit]
            sql += """
                ORDER BY
                    CASE WHEN lower(name) LIKE lower(?) THEN 0 ELSE 1 END,
                    updated_at DESC
                LIMIT ?
            """
        else:
            params_query = [pattern, pattern, pattern, pattern, pattern, limit]
            sql += """
                ORDER BY
                    CASE WHEN lower(name) LIKE lower(?) THEN 0 ELSE 1 END,
                    updated_at DESC
                LIMIT ?
            """
        _ = params  # unused placeholder avoided
        rows = self.conn.execute(sql, params_query).fetchall()
        return [self._row_to_node(r) for r in rows]

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
        rows = self.conn.execute(
            """
            SELECT
                e.id AS edge_id,
                e.from_id,
                e.to_id,
                e.relation,
                e.facets_json AS edge_facets_json,
                e.source_doc_id,
                n1.node_type AS from_type,
                n1.name AS from_name,
                n1.facets_json AS from_facets_json,
                n2.node_type AS to_type,
                n2.name AS to_name,
                n2.facets_json AS to_facets_json
            FROM edges e
            JOIN nodes n1 ON n1.id = e.from_id
            JOIN nodes n2 ON n2.id = e.to_id
            ORDER BY e.created_at DESC
            """
        ).fetchall()

        edges: list[dict[str, Any]] = []
        for r in rows:
            from_facets = json.loads(r["from_facets_json"])
            to_facets = json.loads(r["to_facets_json"])
            from_et = str(from_facets.get("entity_type") or "").strip().lower() or None
            to_et = str(to_facets.get("entity_type") or "").strip().lower() or None
            edges.append(
                {
                    "edge_id": str(r["edge_id"]),
                    "from_id": str(r["from_id"]),
                    "to_id": str(r["to_id"]),
                    "relation": str(r["relation"]),
                    "facets": json.loads(r["edge_facets_json"]),
                    "source_doc_id": r["source_doc_id"],
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
        return self._row_to_node(rows[0]) if rows else None

    def get_entity_overview(self, entity_id: str) -> dict[str, Any]:
        """Return full ontology context for an entity: consensus, events, views, themes, peers."""
        entity = self.get_node(entity_id)
        if entity is None:
            raise KeyError(f"Node not found: {entity_id}")  # noqa: TRY003

        consensus = self.get_entity_consensus(entity_id)
        incident = self.get_incident_edges(entity_id)

        events: list[dict[str, Any]] = []
        views: list[dict[str, Any]] = []
        prior_consensuses: list[dict[str, Any]] = []
        themes: list[dict[str, Any]] = []
        related_entities: list[dict[str, Any]] = []
        seen_theme_ids: set[str] = set()

        for item in incident:
            neighbor = item["neighbor"]
            ntype = neighbor["node_type"]
            edge_info = {
                "relation": item["relation"],
                "direction": item["direction"],
                "edge_facets": item["facets"],
            }
            if ntype == "event":
                eff_sent, sent_src = resolve_item_sentiment(neighbor["facets"], item["facets"])
                events.append(
                    {
                        **neighbor,
                        **edge_info,
                        "effective_sentiment": eff_sent,
                        "sentiment_source": sent_src,
                    }
                )
            elif ntype == "view":
                vtype = neighbor["facets"].get("view_type")
                status = neighbor["facets"].get("status", "active")
                if vtype == "consensus":
                    if consensus is None or neighbor["id"] != consensus.id:
                        if status == "superseded":
                            prior_consensuses.append({**neighbor, **edge_info})
                else:
                    eff_sent, sent_src = resolve_item_sentiment(neighbor["facets"], item["facets"])
                    views.append(
                        {
                            **neighbor,
                            **edge_info,
                            "effective_sentiment": eff_sent,
                            "sentiment_source": sent_src,
                        }
                    )
            elif ntype == "theme":
                seen_theme_ids.add(neighbor["id"])
                themes.append({**neighbor, **edge_info, "via": "direct"})
            elif ntype == "entity":
                related_entities.append({**neighbor, **edge_info})

        # Also surface themes connected 1-hop through this entity's events or views.
        for linked_item in events + views:
            for sub in self.get_incident_edges(linked_item["id"]):
                sub_nb = sub["neighbor"]
                if sub_nb["node_type"] == "theme" and sub_nb["id"] not in seen_theme_ids:
                    seen_theme_ids.add(sub_nb["id"])
                    themes.append(
                        {
                            **sub_nb,
                            "relation": sub["relation"],
                            "direction": sub["direction"],
                            "edge_facets": sub["facets"],
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
            "entity": _node_to_dict(entity),
            "consensus": _node_to_dict(consensus) if consensus is not None else None,
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

            rel = str(item["relation"]).strip().upper()
            if not include_authored and rel == "AUTHORED_BY":
                continue

            facets = neighbor["facets"]
            if ntype == "view" and str(facets.get("view_type") or "").strip().lower() == "consensus":
                status = str(facets.get("status") or "active").strip().lower()
                if not include_consensus or status != "active":
                    continue

            edge_facets = item["facets"]
            rank = (
                1 if normalize_sentiment(edge_facets.get("sentiment")) is not None else 0,
                1 if rel == "ABOUT" else 0,
            )

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

        norm_sentiments: set[str] | None = None
        if sentiments:
            parsed_sents = set()
            for raw in sentiments:
                cleaned = str(raw).strip().lower()
                if not cleaned:
                    continue
                if cleaned in ("unknown", "unclassified", "none"):
                    parsed_sents.add("unclassified")
                else:
                    parsed_sents.add(cleaned)
            norm_sentiments = parsed_sents or None

        norm_node_types: set[str] | None = None
        if node_types:
            parsed_types = {str(nt).strip().lower() for nt in node_types if str(nt).strip()}
            norm_node_types = parsed_types or None

        norm_categories: set[str] | None = None
        if categories:
            parsed_cats = set()
            for raw in categories:
                cleaned = str(raw).strip().lower().replace(" ", "_")
                if not cleaned:
                    continue
                parsed_cats.add(SIGNAL_CATEGORY_ALIASES.get(cleaned, cleaned))
            norm_categories = parsed_cats or None

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

        def _matches_category(item: dict[str, Any], cat: str) -> bool:
            ntype = item["node_type"]
            subtype = str(item.get("subtype") or "").strip().lower()
            status = str(item["facets"].get("status") or "").strip().lower()
            if cat == "rumor":
                return (ntype == "view" and subtype == "rumor") or (
                    ntype == "event" and (status == "rumored" or subtype == "rumor")
                )
            return subtype == cat

        scope_items: list[dict[str, Any]] = []
        for item in raw_items:
            if norm_node_types is not None and item["node_type"] not in norm_node_types:
                continue
            item_status = str(item["facets"].get("status") or "").strip().lower()
            if norm_statuses is not None and item_status not in norm_statuses:
                continue
            if norm_categories is not None and not any(
                _matches_category(item, cat) for cat in norm_categories
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

        if norm_sentiments is not None:
            matched = [
                item
                for item in scope_items
                if (item["effective_sentiment"] or "unclassified") in norm_sentiments
            ]
        else:
            matched = list(scope_items)

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
            subtype_key = str(item.get("subtype") or ntype).strip().lower()
            counts_by_subtype[subtype_key] = counts_by_subtype.get(subtype_key, 0) + 1
            if (
                ntype == "event"
                and str(item["facets"].get("status") or "").strip().lower() == "rumored"
            ):
                rumored_event_count += 1

        return {
            "entity": _node_to_dict(entity),
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

        rel_filter = {r.strip().upper() for r in relations} if relations else None
        visited_hops: dict[str, int] = {start.id: 0}
        nodes_out: list[dict[str, Any]] = [{**_node_to_dict(start), "hop": 0}]
        edges_out: list[dict[str, Any]] = []
        seen_edge_ids: set[str] = set()

        queue: deque[tuple[str, int]] = deque([(start.id, 0)])
        while queue and len(nodes_out) < limit:
            curr_id, hop = queue.popleft()
            if hop >= max_hops:
                continue
            for item in self.get_incident_edges(curr_id):
                rel = item["relation"].upper()
                if rel_filter is not None and rel not in rel_filter:
                    continue
                nb = item["neighbor"]
                if item["edge_id"] not in seen_edge_ids:
                    seen_edge_ids.add(item["edge_id"])
                    from_id = curr_id if item["direction"] == "outgoing" else nb["id"]
                    to_id = nb["id"] if item["direction"] == "outgoing" else curr_id
                    edges_out.append(
                        {
                            "edge_id": item["edge_id"],
                            "from_id": from_id,
                            "to_id": to_id,
                            "relation": rel,
                            "facets": item["facets"],
                        }
                    )
                if nb["id"] not in visited_hops and len(nodes_out) < limit:
                    visited_hops[nb["id"]] = hop + 1
                    nodes_out.append({**nb, "hop": hop + 1})
                    queue.append((nb["id"], hop + 1))

        return {
            "start_node": _node_to_dict(start),
            "nodes": nodes_out,
            "edges": edges_out,
        }

    def find_theme_companies(
        self, theme_id: str, include_second_order: bool = True
    ) -> dict[str, Any]:
        """Find 1st-order (direct & event/view-mediated) and 2nd-order theme-exposed companies."""
        theme = self.get_node(theme_id)
        if theme is None or theme.node_type != "theme":
            raise KeyError(f"Theme not found: {theme_id}")  # noqa: TRY003

        first_order_map: dict[str, dict[str, Any]] = {}

        def _ensure_company_entry(company_dict: dict[str, Any]) -> dict[str, Any]:
            cid = company_dict["id"]
            if cid not in first_order_map:
                consensus = self.get_entity_consensus(cid)
                first_order_map[cid] = {
                    "company": company_dict,
                    "consensus_stance": consensus.facets.get("stance") if consensus else None,
                    "consensus_summary": consensus.summary if consensus else None,
                    "links": [],
                }
            return first_order_map[cid]

        def _is_company(node_dict: dict[str, Any]) -> bool:
            return (
                node_dict["node_type"] == "entity"
                and str(node_dict["facets"].get("entity_type", "")).lower() == "company"
            )

        for item in self.get_incident_edges(theme.id):
            nb = item["neighbor"]
            if _is_company(nb):
                entry = _ensure_company_entry(nb)
                entry["links"].append(
                    {
                        "via": "direct",
                        "relation": item["relation"],
                        "direction": item["direction"],
                        "facets": item["facets"],
                    }
                )
            elif nb["node_type"] in ("event", "view"):
                for sub in self.get_incident_edges(nb["id"]):
                    sub_nb = sub["neighbor"]
                    if _is_company(sub_nb):
                        entry = _ensure_company_entry(sub_nb)
                        entry["links"].append(
                            {
                                "via": f"{nb['node_type']}: {nb['name']}",
                                "via_node_id": nb["id"],
                                "theme_relation": item["relation"],
                                "entity_relation": sub["relation"],
                                "source": nb["facets"].get("source"),
                                "facets": nb["facets"],
                            }
                        )

        second_order_map: dict[str, dict[str, Any]] = {}
        if include_second_order:
            for cid, entry in first_order_map.items():
                first_name = entry["company"]["name"]
                for rel_item in self.get_incident_edges(cid):
                    nb = rel_item["neighbor"]
                    if (
                        _is_company(nb)
                        and nb["id"] not in first_order_map
                        and rel_item["relation"].upper() in SECOND_ORDER_ENTITY_RELATIONS
                    ):
                        sid = nb["id"]
                        if sid not in second_order_map:
                            consensus = self.get_entity_consensus(sid)
                            second_order_map[sid] = {
                                "company": nb,
                                "consensus_stance": (
                                    consensus.facets.get("stance") if consensus else None
                                ),
                                "paths": [],
                            }
                        second_order_map[sid]["paths"].append(
                            {
                                "connected_to": first_name,
                                "connected_to_id": cid,
                                "relation": rel_item["relation"],
                                "direction": rel_item["direction"],
                                "facets": rel_item["facets"],
                            }
                        )

        return {
            "theme": _node_to_dict(theme),
            "first_order": list(first_order_map.values()),
            "second_order": list(second_order_map.values()),
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
            where_type = "AND lower(COALESCE(json_extract(ent.facets_json, '$.entity_type'), '')) = ?"
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
            rel = str(item["relation"]).strip().upper()
            edge_facets = item["facets"]
            rank = (
                1 if normalize_sentiment(edge_facets.get("sentiment")) is not None else 0,
                1 if rel == "ABOUT" else 0,
            )
            if nb_id not in best_ranks or rank > best_ranks[nb_id]:
                best_ranks[nb_id] = rank
                connected[nb_id] = edge_facets
        return connected

    def list_recent_edges(self, limit: int = 80) -> list[dict[str, Any]]:
        """Return recent edges joined with endpoint node names and types."""
        rows = self.conn.execute(
            """
            SELECT
                e.id AS edge_id,
                e.relation AS relation,
                e.facets_json AS facets_json,
                e.source_doc_id AS source_doc_id,
                nf.id AS from_id,
                nf.name AS from_name,
                nf.node_type AS from_type,
                nt.id AS to_id,
                nt.name AS to_name,
                nt.node_type AS to_type
            FROM edges e
            JOIN nodes nf ON nf.id = e.from_id
            JOIN nodes nt ON nt.id = e.to_id
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "edge_id": str(r["edge_id"]),
                "relation": str(r["relation"]),
                "facets": json.loads(r["facets_json"]),
                "source_doc_id": r["source_doc_id"],
                "from_id": str(r["from_id"]),
                "from_name": str(r["from_name"]),
                "from_type": str(r["from_type"]),
                "to_id": str(r["to_id"]),
                "to_name": str(r["to_name"]),
                "to_type": str(r["to_type"]),
            }
            for r in rows
        ]
