"""Schema layer: SQLite table definitions, row mapping, and facet merge rules.

Nothing here opens a connection or runs a query on its own. `init_schema` takes
a connection from the storage layer, and the rest are pure functions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from stock_ontology.models import Edge, Node, Sentiment, normalize_sentiment
from stock_ontology.vocab import SIGNAL_CATEGORY_ALIASES  # noqa: F401  (re-exported by stock_ontology.db)


SECOND_ORDER_ENTITY_RELATIONS = {
    "BUY",
    "COMPETE",
    "OWNS",
}

THEME_EXPOSURE_RELATIONS = {
    "EXPOSED_TO",
}


def init_schema(conn: sqlite3.Connection, embedding_dim: int) -> None:
    """Create tables and indexes if they do not exist, then add any missing columns. Idempotent."""
    with conn:
        conn.executescript(
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
                embedding float[{embedding_dim}] distance_metric=cosine
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

            CREATE TABLE IF NOT EXISTS node_lookup (
                key TEXT NOT NULL,
                node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                node_type TEXT NOT NULL,
                PRIMARY KEY (key, node_id)
            );
            CREATE INDEX IF NOT EXISTS idx_node_lookup_key_type ON node_lookup(key, node_type);
            CREATE INDEX IF NOT EXISTS idx_node_lookup_node ON node_lookup(node_id);
            """
        )
        _add_missing_columns(conn)


# Columns added after a table first shipped: (table, column, SQL type).
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("ingestion_log", "size", "INTEGER"),
    ("ingestion_log", "mtime_ns", "INTEGER"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring tables from older databases up to date with additive ALTERs."""
    with conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


def row_to_node(row: sqlite3.Row) -> Node:
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


def row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        id=row["id"],
        from_id=row["from_id"],
        to_id=row["to_id"],
        relation=row["relation"],
        facets=json.loads(row["facets_json"]),
        source_doc_id=row["source_doc_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def node_to_dict(node: Node) -> dict[str, Any]:
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


def node_meta(node: Node | dict[str, Any]) -> tuple[str, str, str | None]:
    """Return (id, node_type, entity_type) for a node or node dict."""
    if isinstance(node, Node):
        et = node.facets.get("entity_type")
        return node.id, node.node_type, str(et) if et else None
    et = node["facets"].get("entity_type")
    return str(node["id"]), str(node["node_type"]), str(et) if et else None


def sql_casefold(value: Any) -> str | None:
    """SQL helper matching Python `str.strip().casefold()` for name/alias lookups."""
    return value.strip().casefold() if isinstance(value, str) else None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def reconcile_sentiment(existing: Any, incoming: Any) -> Sentiment | None:
    """Combine two optional sentiment polarities without losing opposing signals."""
    s1 = normalize_sentiment(existing)
    s2 = normalize_sentiment(incoming)
    if s1 is None:
        return s2
    if s2 is None:
        return s1
    if s1 == s2:
        return s1
    if s1 == "neutral":
        return s2
    if s2 == "neutral":
        return s1
    return "mixed"


def merge_edge_facets(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge two edge facet dicts, preserving non-empty keys and reconciling sentiment."""
    merged: dict[str, Any] = dict(existing or {})
    for k, v in (incoming or {}).items():
        if k == "sentiment":
            combined = reconcile_sentiment(merged.get("sentiment"), v)
            if combined is not None:
                merged["sentiment"] = combined
            continue
        if k not in merged or merged[k] in (None, "", []):
            merged[k] = v
    return merged
