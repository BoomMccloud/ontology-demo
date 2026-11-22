---
proposal_id: "ingestion-followups"
state: FRAMED
witness: independent
candidate: "6d4b2d7 @ worktree/proposal-ingestion-followups"
---

# Proposal: Ingestion follow-ups

## Proposal

Status: approved by the human on 2026-11-22 ("do everything else", then "Yes,
start it" for the follow-ups listed after `ingestion-write-integrity` and
`minimal-entity-relationships` were accepted). The defaults below were stated
with that list and are taken as chosen.

### Outcome

Ingestion and repair stay correct and get cheaper: repaired data has fresh
embeddings, reports count everything they change, consensus targets reflect
only committed notes, lookups stay fast as the DB grows, and unchanged or
merely moved notes cost no file hashing or LLM calls.

### Motivation

These are the open items from the ingestion review and the
`ingestion-write-integrity` audit.

1. **Stale embedding after a merge.** `repair` unions aliases into the
   surviving node but cannot recompute its embedding, because it has no LLM.
2. **Uncounted self-loops.** Self-loop edges that `repair` deletes after
   repointing are not counted in `RepairReport`.
3. **Consensus targets from rolled-back notes.** `affected_company_ids` is
   filled inside the per-note transaction, so a note that rolls back can leave
   a company ID that no longer exists and a spurious consensus error.
4. **Name lookup is a full scan.** `find_by_name_or_alias` evaluates a Python
   function over every row and every alias.
5. **Moved or renamed notes re-run the LLM.** `doc_id` comes from the path, so
   a move is a delete plus a new note even when the content hash is unchanged.
6. **Every run reads and hashes every file**, which `watch` repeats every tick.
7. **Embedding calls are not batched** when extracted entities and themes are
   matched against existing nodes.
8. **The catalog sent to the LLM is capped silently** at 500 entities and 500
   themes, so past that the model cannot see existing nodes and creates
   duplicates.
9. **Code cleanup.** Event and view building inside `_write_extraction`, the
   event and view sentiment fallbacks (which differ in order and compute one
   value twice), and the consensus rebuild that reloads each node one by one.

### Chosen defaults

1. `repair` reports the IDs of merged survivors. A new `repair --reembed` flag
   recomputes their embeddings with the configured LLM. Plain `repair` still
   needs no LLM.
2. Self-loop deletions are counted in `RepairReport`.
3. Company IDs from a note are added to the consensus targets only after that
   note's transaction commits.
4. A `node_lookup` table of normalized names and aliases, with an index, is
   kept in sync on every node write and delete, and backfilled when a writable
   DB opens without it. Read-only opens of an older DB fall back to the
   current query.
5. A note that disappears from one path and appears at another with the same
   content hash keeps its `doc_id` and artifacts. Only its log path and its
   nodes' source path and folder are updated. Ambiguous matches (more than one
   candidate with the same hash) fall back to normal ingestion.
6. The ingestion log records file size and modification time. A file whose
   size and modification time are unchanged is skipped without reading.
   `--force` reads everything.
7. Probe embeddings for extracted entities and themes that have no exact
   name or alias match are computed in one batched call per note.
8. The catalog lists every entity and theme whose name or an alias appears in
   the note text, plus the most recently updated nodes up to a fixed budget,
   instead of an arbitrary first 500.
9. Event and view node building move into their own helpers, sentiment
   fallback goes through one shared helper with an explicit order, and the
   consensus rebuild fetches its nodes in one query.

### Constraints

- `audit`, the query agent, and the web UI stay read-only.
- Existing `ontology.db` files keep working: schema additions are additive and
  applied on writable open.
- Tests stay offline with fake LLM clients.
- Behavior covered by the accepted `ingestion-write-integrity` and
  `minimal-entity-relationships` witnesses does not change.

### Non-goals

- Live DB actions (running `repair`, `repair --reembed`, or re-ingest against
  the real `ontology.db`). Those stay with the human.
- Registry decisions on pending suggestions, contradiction review, or
  re-ingesting to fill missing sentiment.
- Ruff findings in files this proposal does not touch.

### Unresolved choices

- None.

## Frame

Candidate: `6d4b2d7 + uncommitted ledger @ worktree .claude/worktrees/ingestion-followups (branch proposal/ingestion-followups)`

### Verified reality
- `uv run pytest -q` in this worktree at `6d4b2d7` — 80 passed before the change; limit: offline fake-LLM suites only.
- `src/stock_ontology/pipeline.py:105` `_scan_files` — reads and hashes every supported file on every run; `run()` (`:543`) skips extraction only after reading, when `content_hash` matches the log.
- `pipeline.py:543` `run()` — deleted paths are cleaned up before new paths are processed, and `doc_id` is `sha256(rel_path)[:12]`, so a moved note is deleted and re-extracted (one `extract_document` call); limit: no rename handling exists.
- `src/stock_ontology/db.py:227` `ingestion_log` — columns `file_path`, `doc_id`, `content_hash`, `ingested_at` only; no size or mtime.
- `pipeline.py:128` `_build_existing_catalog` — `list_nodes(limit=500)` for entities and themes ordered by `updated_at DESC`; an entity named in the note but older than the 500 newest is omitted.
- `pipeline.py:150` `_resolve_canonical_node` — one `embed_texts([probe])` call per unmatched entity/theme, plus one per changed existing node; limit: per-node calls, no batching.
- `pipeline.py:247` `_process_document` / `_clear_prior_artifacts` / `_write_extraction` — company IDs are added to the caller's `affected_company_ids` inside the per-note transaction; `run()` rebuilds consensus for every ID in that set.
- `pipeline.py:476` `_rebuild_company_consensus` — calls `get_node` once per event, view, and theme ID from `get_entity_overview`.
- `db.py:599` `find_by_name_or_alias` — SQL with `so_casefold()` over `name` and `json_each(aliases_json)`; no index can serve it.
- `src/stock_ontology/repair.py:164` `_merge_cluster` — upserts the survivor without an embedding; `:191` deletes self-loops without counting them; `RepairReport` (`:17`) has no list of merged survivor IDs.
- `cli.py` `repair` — loads the registry and opens a writable DB; it never builds an LLM client.
- Accepted ledgers `docs/proposals/ingestion-write-integrity.md` and `docs/proposals/minimal-entity-relationships.md` — their witnesses in `tests/test_pipeline.py`, `tests/test_repair.py`, `tests/test_relationships.py` must stay green.

### Final primary claim
- Re-running ingestion over notes that are unchanged, or only moved to a new path with identical content, makes zero `extract_document` calls and does not read files whose size and modification time are unchanged, and each moved note keeps exactly one artifact set whose `facets.source.file_path` is its new path.

### Routing
- Witness: independent
- Why: the change alters stored `ontology.db` schema (`node_lookup` table, `ingestion_log` columns) and rewrites stored rows on rename and repair.
- Human-owned irreversible action: running `repair`, `repair --reembed`, or ingestion against the real `ontology.db`, and merging `proposal/ingestion-followups` into `main`.

### Decisive witness
- Layer: offline pytest integration tests over temporary DBs and data dirs with fake LLM clients.
- Permanent owner: `tests/test_pipeline.py` (ingestion claims) and `tests/test_repair.py` (repair claims).
- Witness: after an initial run, a second run with all files untouched calls neither `extract_document` nor `Path.read_text` for them; moving one note to a new folder and re-running calls `extract_document` zero times, keeps the same artifact count, and reports the new `file_path` on its nodes.

### Guardrail claims
- `repair` reports every row it changes, including deleted self-loops, and lists merged survivor IDs; `repair --reembed` (or the function it calls) gives each survivor a freshly computed embedding.
- A note whose transaction rolls back contributes no company to the consensus targets, so a run whose only failure is that note reports exactly one error.
- An existing entity whose name or alias appears in a note is listed in the extraction catalog even when more than 500 newer entities exist.

### Supporting obligations
- Add `node_lookup(key, node_id, node_type)` with an index on `(key, node_type)` and `ON DELETE CASCADE` to `nodes`; refresh rows in `upsert_node`; backfill on writable open when missing or empty; `find_by_name_or_alias` uses it, falling back to the current query when the table is absent (read-only open of an older DB). Unit test in `tests/test_db.py`: query plan uses the index; lookups survive alias edits and node deletes.
- Add nullable `size` and `mtime_ns` columns to `ingestion_log` via `ALTER TABLE` on writable open; `upsert_ingestion_log` accepts them; `_scan_files` stats first and reads only when size or mtime differs or `force` is set. Unit test in `tests/test_db.py` for the migration on an old-schema DB.
- Rename detection in `run()` before deletion: pair a vanished logged path with a new path whose content hash matches, when the match is unique; update the log path and each artifact's `source.file_path` and `source.folder` in one transaction.
- Batch probe embeddings for unmatched extracted entities and themes into one `embed_texts` call per note; unit test counts embed calls.
- Catalog: names and aliases found in the note text (casefold substring) first, then most recent nodes up to a fixed budget.
- Collect a note's company IDs in a local set and merge it into the run's targets only after the transaction commits.
- `RepairReport` gains `self_loops_deleted` and `merged_survivor_ids`; add `reembed_nodes(db, llm, node_ids)` reusing `node_embedding_text`; `cli repair --reembed` builds the LLM client only when the flag is set.
- Move event and view node building into helpers; one `_resolve_sentiment(explicit, facet, fallback)` helper with the precedence explicit → facet → stance-derived → `neutral`, keeping current outputs for existing witnesses; `_rebuild_company_consensus` fetches nodes in one query via a new `OntologyDB.get_nodes(ids)`.
- Update `README.md` with `repair --reembed` and any durable constraint the change establishes.

### Allowed scope
- Reuse: `OntologyDB.transaction()`, `delete_document_artifacts`, `node_embedding_text`, `reembed_all_nodes` patterns, `repair_ontology`, existing fake LLMs in `tests/test_pipeline.py`.
- Cheaper alternative: skip `node_lookup` and the mtime columns, keeping only rename detection by hash. Rejected because the primary claim requires skipping reads of unchanged files, which needs stored size and mtime; `node_lookup` is a supporting obligation the human listed, not a claim, so it is kept but witnessed only by unit tests.
- Include: `src/stock_ontology/db.py`, `src/stock_ontology/pipeline.py`, `src/stock_ontology/repair.py`, `src/stock_ontology/cli.py`, `tests/test_db.py`, `tests/test_pipeline.py`, `tests/test_repair.py`, `README.md`.
- Exclude/protect: `ontology.db`, `ontology_registry.json`, `data/`; `audit.py`, `registry.py`, web, i18n, and locale files; `tests/test_relationships.py`; behavior asserted by existing tests.

### Invariants changed
- None.

### Decisions required
- None.

## Proof

## Build

## Audit

## Revisions
