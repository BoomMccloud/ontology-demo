# Storage

Persistence for the ontology in one SQLite file (`ontology.db`) with the
`sqlite-vec` extension for embeddings. It's a package with two layers.

## Files

- `src/stock_ontology/db/__init__.py` re-exports the public names. Import from
  `stock_ontology.db`, never from the submodules.
- `src/stock_ontology/db/schema.py` is the schema layer.
- `src/stock_ontology/db/storage.py` is the storage layer.

## Schema layer (`db/schema.py`)

Pure definitions. Nothing here opens a connection.

- `init_schema(conn, embedding_dim)` creates the tables and indexes:
  `nodes`, `edges`, `node_vectors` (a `vec0` virtual table, cosine distance),
  `ingestion_log`, `db_metadata`, and `node_lookup` (casefolded names and
  aliases, for exact-match resolution). It then adds columns that shipped
  later, listed in `_ADDED_COLUMNS` (`ingestion_log.size` and `mtime_ns`). It
  is idempotent, so old databases upgrade on open.
- `row_to_node`, `row_to_edge`, `node_to_dict` map between SQLite rows and the
  `Node` / `Edge` models.
- `merge_edge_facets` and `reconcile_sentiment` define how two facet dicts
  combine when edges are deduplicated. Opposing sentiments become `mixed`.
- Relation groupings used by queries: `THEME_EXPOSURE_RELATIONS`.
  `SIGNAL_CATEGORY_ALIASES` is re-exported from `vocab.py`.

Change this layer when the shape of the data changes: a new column, a new
table, a new facet merge rule. A column added to an existing table goes in
`_ADDED_COLUMNS` so older databases get it too.

## Storage layer (`db/storage.py`)

`OntologyDB` owns the connection and every read and write.

- Opening: `OntologyDB(path, embedding_dim=768, read_only=False, registry=None)`.
  With `read_only=True` it sets `PRAGMA query_only = ON`, so SQLite itself
  rejects writes. Writable connections use WAL, call `init_schema`, and backfill
  `node_lookup` if any node lacks rows there.
- Transactions: `transaction()` nests; only the outermost scope commits.
- Writes: `upsert_node`, `upsert_edge` (relation through
  `normalize_relation_name`), `upsert_consensus_view`,
  `delete_document_artifacts`, `relink_document`, `replace_node_embeddings`,
  `rebuild_node_lookup`, the `ingestion_log` methods, and `set_metadata`.
- Repair writes: `update_edge` (also normalizes the relation), `merge_node_into` (returns the self-loops it
  dropped), `delete_edges`, plus the
  `list_artifact_doc_ids` and `count_document_artifacts` lookups.
- Lookups: `get_node`, `get_nodes`, `find_by_name_or_alias`,
  `find_nodes_mentioned_in`, `list_nodes`, `list_all_nodes`,
  `get_incident_edges`, `list_edges_with_endpoints`, `get_entity_consensus`.
- Search: `vector_search` (sqlite-vec) and `keyword_search`.
- Graph queries: `get_entity_overview`, `query_entity_signals`, `traverse_bfs`,
  `find_theme_companies`. These canonicalize edges through the registry, which
  is why `OntologyDB` takes one.
- Stats for the UI: `get_stats`, `get_doc_node_counts`,
  `get_entity_document_links`, `get_edge_schema_summary`,
  `get_node_edge_counts`, `get_entity_connected_nodes`, `list_recent_edges`.

Stored enum facets and relation names are canonical, so queries compare them
directly. `query_entity_signals` parses its filter input and matches items with
the shared `vocab` filter functions.

Change this layer when you need a new query or a faster one.

## Depends on

[ontology.md](ontology.md) for the models and for `OntologyRegistry` and
`CanonicalEdgeResult`.

## Used by

The pipeline, agent, web app, governance, and CLI. Only the pipeline and
`repair` open it writable.

No other module may touch SQLite directly. `tests/test_architecture.py`
enforces that.

## Tests

`tests/test_db.py`, plus `tests/test_relationships.py` for the graph queries.
