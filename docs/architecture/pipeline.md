# Data processing pipeline

Turns research notes into graph rows. It's the main writer to `ontology.db`.

## Files

- `src/stock_ontology/pipeline.py`
- `src/stock_ontology/llm/prompts.py` holds the extraction and consensus
  prompts the pipeline sends through the LLM layer.

## Flow

`IngestionPipeline.run(force=False, rebuild_consensus=False)` does this:

1. Scan `ONTOLOGY_DATA_DIR` recursively for `.md` and `.txt` files
   (`SUPPORTED_EXTENSIONS`, defined in `config.py`), skipping hidden paths.
2. Compare against `ingestion_log`. Files whose size and mtime match are
   skipped without being read. The rest are read and hashed. A moved file
   whose hash uniquely matches a vanished one is relinked to its new path
   (`relink_document`) instead of re-extracted. Removed or changed files have
   their prior rows deleted.
3. For each new or changed note, call `LLMClient.extract_document` with a
   catalog of existing nodes, getting back an `ExtractionResult`. The catalog
   lists nodes named in the note first (`find_nodes_mentioned_in`), then
   recent ones.
4. Resolve each extracted node to an existing one by name, alias, or embedding
   distance under `CANONICAL_DISTANCE_THRESHOLD` (0.15), or create a new one.
5. Canonicalize edges through the registry and write nodes, edges, and
   embeddings inside one transaction per document.
6. Rebuild the `consensus` view for every company the note touched, through
   `LLMClient.synthesize_consensus`.

`watch(interval_seconds)` reruns `run` on a timer. `reembed_all_nodes`
rebuilds every embedding, for example after switching embedding models.
`reembed_nodes(db, llm, ids)` refreshes a few, which the CLI uses after
`repair` merges duplicates. It lives here, not in governance, because
governance may not import the LLM layer.

Folder names don't decide which company a note is about. The note's relative
path is stored as provenance in `facets.source`.

## Depends on

[ontology.md](ontology.md) (models and registry), [storage.md](storage.md),
and [llm.md](llm.md).

## Used by

The CLI (`ingest`, `watch`, `reembed`, and `repair` for `reembed_nodes`).

## Tests

`tests/test_pipeline.py`, with fake LLM clients.
