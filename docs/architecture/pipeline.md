# Data processing pipeline

Turns research notes into graph rows. The worker runs it for every job that
changes the graph.

## Files

- `src/stock_ontology/pipeline.py`
- `src/stock_ontology/llm/prompts.py` holds the extraction and consensus
  prompts the pipeline sends through the LLM layer.

## Flow

The reader's Process action queues a `process` job, and the worker calls
`process_note` for that source. It reuses the batch extraction transaction and
records entity membership with the note's edges and content hash. Reader
corrections are jobs too: they validate and update that note's membership or
edges through ingestion, then refresh affected consensus.

Every transaction that changes evidence advances the affected companies'
`consensus_refresh` revisions in the same transaction (`_evidence_changed`),
so a rollback queues none, and calls `commit_check` with those revisions. The
worker sets `commit_check` to refuse a lost or expired job claim.

`IngestionPipeline.run(force=False, rebuild_consensus=False)` does this:

1. Scan `ONTOLOGY_DATA_DIR` recursively for `.md` and `.txt` files
   (`SUPPORTED_EXTENSIONS`, defined in `config.py`), skipping hidden paths.
2. Compare against `ingestion_log`. Files whose size and mtime match are
   skipped without being read. The rest are read and hashed. A moved file
   whose hash uniquely matches a vanished one is relinked to its new path
   (`relink_document`) instead of re-extracted. Removed or changed files have
   their prior rows deleted.
3. For each new or changed note, run three ordered extractions through
   `LLMClient.extract_stage`, each with a catalog of existing nodes. The catalog
   lists nodes named in the note first (`find_nodes_mentioned_in`), then
   recent ones.
   - `entities`: entities, themes, and `WORKS_AT`, `OWNS`, `BUY`, `COMPETE`
     and `EXPOSED_TO` edges. Only this run creates entities and themes.
   - `events`: events and their edges, linked to the resolved entities and themes.
   - `views`: views and their edges, linked to everything resolved so far.

   Each run's output schema only allows the node types it owns, and its new
   temp IDs are namespaced so runs cannot collide. A refused write repeats the
   run that owns the item and every later run, up to `MAX_EXTRACTION_ATTEMPTS`
   for the note. `IngestReport.extraction_retries` counts these by run, and
   `unresolved_edge_refs` counts edges whose endpoint matched no node. A client
   without `extract_stage` makes one `extract_document` call.
4. Resolve each extracted entity or theme to an existing node only by exact
   ID, name, or alias, or by the registry mapping it to the same official
   company (ticker, name, alias) or theme; otherwise create a new node.
   Embedding similarity never merges nodes. New and changed nodes are embedded
   in one batch per note.
5. Canonicalize edges through the registry and write nodes, edges, and
   embeddings inside one transaction per document.
6. Rebuild the `consensus` view for every company the note touched, through
   `LLMClient.synthesize_consensus`. Synthesis and its embedding run outside
   any write transaction. The result publishes only if the company's refresh
   revision is unchanged (otherwise `StaleConsensusError`), and the published
   revision is recorded with it. A failed refresh keeps the previous consensus
   and marks the refresh `failed`.

`watch(interval_seconds)` reruns `run` on a timer; the CLI's `watch` now runs
the worker loop instead. `reembed_all_nodes`
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

The worker (`worker.py`) for every job kind, including `reembed_nodes` after a
`repair --reembed`.

## Tests

`tests/test_pipeline.py`, with fake LLM clients.
