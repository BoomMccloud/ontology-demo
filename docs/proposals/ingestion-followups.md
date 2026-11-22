---
proposal_id: "ingestion-followups"
state: BUILT
witness: independent
candidate: "12187d1 @ worktree/proposal-ingestion-followups"
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

Candidate: `dc5c34a` (branch `proposal/ingestion-followups`, worktree `.claude/worktrees/ingestion-followups`): production source unchanged from `5db2d3d` / `6d4b2d7`, plus the witness tests below. RED was observed on this tree.

**Protected witness**
- Primary claim, unchanged notes are not read. `tests/test_pipeline.py` / `test_pipeline_rerun_does_not_read_unchanged_notes`
  - Defect and boundary: `_scan_files` reads and hashes every note on every run. Crosses the filesystem → ingestion log (`ingestion_log` size/mtime) → run-skip boundary.
  - Assertion: after a first run over the 5 sample notes, a second run with untouched files opens no file under the data dir (via recorded `Path.read_text/read_bytes/open`, `builtins.open`, `io.open`) and makes zero `extract_document` calls, with `files_skipped == 5`. Proves that unchanged size and mtime skip reading. Limit: it doesn't catch reads through `os.open`/mmap, and it doesn't prove `--force` still reads everything.
- Primary claim, a moved note is not re-extracted. `tests/test_pipeline.py` / `test_pipeline_moved_note_keeps_doc_and_skips_extraction`
  - Defect and boundary: `doc_id` comes from the path, and deletions are handled before new paths, so a move becomes delete plus re-extract. Crosses filesystem → `ingestion_log` → stored node rows.
  - Assertion: moving `TSMC/2026-11-05_cowos_capacity_note.md` to `archive/...` and re-running gives zero `extract_document` calls. The old path leaves the log, the new path keeps the old `doc_id`, the doc's (node, edge) counts are unchanged, no nodes keep the old `source.file_path`, all of them carry the new one, and `source.folder == "archive"`. Proves a move keeps exactly one artifact set at the new path. Limit: it doesn't cover the ambiguous case (several same-hash candidates falling back to normal ingestion), and it doesn't check that `ingested_at`/consensus are left alone.
- Guardrail, a rolled-back note adds no consensus target. `tests/test_pipeline.py` / `test_pipeline_rolled_back_note_adds_no_consensus_target`
  - Defect and boundary: `_write_extraction` adds company IDs to the run's `affected_company_ids` inside the per-note transaction, and they survive a rollback. Crosses the per-note transaction → run-level consensus rebuild.
  - Assertion: note A ingests Zeta Optics cleanly. In run 2, note B mentions Zeta, then fails mid-write (malformed POISON event embedding). Run 2 reports exactly one error (`zeta_poison.md`), B is not logged, `synthesize_consensus` is never called and `consensus_updated_for == []`. Proves IDs from a rolled-back note never reach the targets. Limit: on the current code the spurious target shows up as an extra consensus rebuild, not as a second error (a missing company returns `False` silently), so the "exactly one error" part already passes today. The RED is the rebuild.
- Guardrail, the catalog lists old entities named in the note. `tests/test_pipeline.py` / `test_pipeline_catalog_lists_old_entities_named_in_note`
  - Defect and boundary: `_build_existing_catalog` takes only the 500 most recently updated entities and themes. Crosses DB → LLM prompt (`existing_catalog`).
  - Assertion: with 600 newer filler entities, the catalog passed to `extract_document` contains `[ent_legacy]` (name "Legacy Corp" in the text) and `[ent_omega]` (alias "OMGH" in the text). Proves note-mentioned entities are listed whatever their age. Limit: it doesn't check themes, the size of the recent-node budget, or ordering.
- Guardrail, repair counts self-loops and lists survivors. `tests/test_repair.py` / `test_repair_counts_self_loops_and_lists_merged_survivors`
  - Defect and boundary: `_merge_cluster` deletes the self-loops created by repointing without counting them, and `RepairReport` has no survivor IDs. Crosses stored rows → the repair report (CLI `--json` payload).
  - Assertion: two exact-duplicate companies joined by one edge merge into one survivor with zero edges left. The report has `self_loops_deleted == 1`, `merged_survivor_ids == [survivor]` and `total_changes == 2`. Proves every row change is reported, including self-loops, along with the survivor IDs. Limit: it doesn't test the CLI table/JSON output directly.
- Guardrail, re-embedding refreshes the survivor's vector. `tests/test_repair.py` / `test_reembed_gives_merged_survivor_a_fresh_embedding`
  - Defect and boundary: the survivor is upserted without an embedding, so its vector stays stale, and no function exists to recompute it. Crosses LLM embeddings → `node_vectors`.
  - Assertion: after repair, `reembed_nodes(db, llm, merged_survivor_ids)` (looked up in `stock_ontology.repair` or `stock_ontology.pipeline`) embeds `node_embedding_text(survivor)`, a text that includes the loser's alias "Delta Power Systems". The stored vector equals the fake's vector for that text and differs from the stale one. Proves the survivor gets a freshly computed embedding. Limit: it doesn't run the CLI `repair --reembed` flag and doesn't prove plain `repair` builds no LLM client. Build covers both.
- Protected paths: `tests/test_pipeline.py`, `tests/test_repair.py`.
- Protected revision: `dc5c34a` (`git show dc5c34a:tests/test_pipeline.py`, `git show dc5c34a:tests/test_repair.py`). The witnesses are in the sections titled "Ingestion follow-ups: …" at the end of each file.

**Red evidence**
- `uv run pytest tests/test_pipeline.py -v -k "rerun_does_not_read or moved_note or rolled_back_note_adds or catalog_lists_old"` → 4 failed. "unchanged notes (same size and mtime) were read again on rerun" (all 5 notes read). "a moved note with identical content was re-extracted" (`['archive/2026-11-05_cowos_capacity_note.md']`). "a rolled-back note still added its company to the consensus targets" (`['Zeta Optics']`). "entity named in the note is missing from the catalog" (only filler entities listed). Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove2/red_pipeline.log`.
- `uv run pytest tests/test_repair.py -v -k "self_loops or fresh_embedding"` → 2 failed. "repair deleted a self-loop edge but did not count it" (`self_loops_deleted` absent). "no reembed_nodes(db, llm, node_ids) to recompute merged survivors' embeddings". Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove2/red_repair.log`.
- `uv run pytest -q` → 6 failed (only the witnesses above), 80 passed. Existing witnesses stay green. `ruff check` on both files is clean. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove2/full_suite.log`.
- None of the claims above has proof until these commands are observed RED. All six were observed RED on `dc5c34a`.

**Supporting test plan**
- `node_lookup` table, index, sync on upsert/delete, backfill, and read-only fallback → Build: `tests/test_db.py`. Catches a query plan that skips the index and lookups gone stale after alias edits or node deletes.
- `ingestion_log` `size`/`mtime_ns` migration on an old-schema DB → Build: `tests/test_db.py`. Catches a broken `ALTER TABLE` migration and an `upsert_ingestion_log` that drops the new columns.
- One batched probe `embed_texts` call per note for unmatched entities and themes → Build: `tests/test_pipeline.py` (embed-call count). Catches per-node embedding calls.
- `repair --reembed` builds the LLM only when the flag is set, and plain `repair` needs no LLM → Build: CLI test owner (`tests/test_repair.py` or the existing CLI test file). Catches LLM construction on plain `repair`.
- `_resolve_sentiment` precedence, the event/view helpers, and `OntologyDB.get_nodes(ids)` for the consensus rebuild → Build: the existing `test_pipeline_normalizes_event_view_consensus_and_edge_sentiment` stays green, plus a `tests/test_db.py` unit test for `get_nodes`. Catches changed sentiment outputs and missing or reordered nodes.

## Build

Candidate: `12187d1 @ worktree/proposal-ingestion-followups` (branch `proposal/ingestion-followups`; rebuilt for R1 on top of `c6375e6`). Later commits on the branch touch only this ledger.

### Files changed

- `src/stock_ontology/db.py` — `node_lookup(key, node_id, node_type)` table with `idx_node_lookup_key_type`, cascading on node delete, refreshed in `upsert_node`, rebuilt on writable open when the table is new or any node lacks a lookup row (`rebuild_node_lookup`; R1); `find_by_name_or_alias` reads it and falls back to the old query when the table is absent (read-only older DB). `ingestion_log` gains nullable `size`/`mtime_ns` via `_migrate_schema`; `get_ingestion_log` returns them; `upsert_ingestion_log` accepts them; new `update_ingestion_stat`, `relink_document`, `get_nodes`, and `find_nodes_mentioned_in` (whole-word match of indexed names/aliases in note text).
- `src/stock_ontology/pipeline.py` — `_scan_files` stats only; `run()` reads a note only when size or mtime differs (or `force`), relinks a vanished path to a new path with a uniquely matching content hash (`files_moved`), records stat for touched-but-unchanged notes, takes `doc_id` from the log entry when present and salts new path-derived IDs that would collide (`_new_doc_id`); `_process_document` collects company IDs in a local set merged into consensus targets only after the note's transaction commits; `_build_existing_catalog(text)` lists note-mentioned entities/themes first, then `CATALOG_RECENT_BUDGET` (500) most recent per type; `_batch_probe_vectors` embeds all unmatched probes in one call and `_resolve_canonical_node` takes `probe_vec`; `_find_exact` shared; `_build_event_node`/`_build_view_node` and `_resolve_sentiment` replace the inline builders with the same precedence; `_rebuild_company_consensus` uses `get_nodes`.
- `src/stock_ontology/repair.py` — `RepairReport.self_loops_deleted` (counted in `total_changes`) and `merged_survivor_ids`; new `reembed_nodes(db, llm, node_ids)`.
- `src/stock_ontology/cli.py` — `repair --reembed` builds the LLM client only when set and re-embeds merged survivors; JSON/table output includes `reembedded`.
- `tests/test_db.py` — supporting tests: lookup index use, alias edits and delete cascade; backfill on an old DB and read-only fallback; `ingestion_log` migration and stat storage; `get_nodes` order; `_resolve_sentiment` precedence; one batched probe call per note; moves to the root folder, doc-ID reuse at an old path, ambiguous same-hash copies, and `--force`; `repair --reembed` builds the LLM only with the flag; existing-but-incomplete `node_lookup` is rebuilt on writable open (R1).
- `README.md` — `repair --reembed` usage; two Ingestion Constraints entries (insert nodes and change names/aliases only through `upsert_node`, raw deletes and other-column updates allowed; take `doc_id` from the log, not the path), each with **Why** and **Guarded by**.

### Unit evidence

- `uv run pytest -q tests/test_db.py` — GREEN: 19 passed; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/unit_db.log`. These supporting tests were written after the implementation, so no RED was observed for them.
- R1: `uv run pytest -q tests/test_db.py -k exists_but_misses` — RED before the fix (1 failed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/r1_red.log`. GREEN after (1 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/r1_green.log`.

### Green evidence

- Decisive witness: `uv run pytest -q tests/test_pipeline.py -k "rerun_does_not_read or moved_note or rolled_back_note_adds or catalog_lists_old"` — pass (4 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/witness_pipeline_r1.log`.
- Decisive witness: `uv run pytest -q tests/test_repair.py -k "self_loops or fresh_embedding"` — pass (2 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/witness_repair_r1.log`.
- Gate: `uv run pytest -q` — pass (95 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/full_suite_r1.log`.
- Gate: `uv run ruff check src/stock_ontology/db.py src/stock_ontology/pipeline.py src/stock_ontology/repair.py src/stock_ontology/cli.py tests/test_db.py` — pass; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build2/ruff_r1.log`.
- Protected witnesses: `git diff --quiet dc5c34a -- tests/test_pipeline.py tests/test_repair.py` — no changes.

### Intervention record

- None. The repository has no intervention ledger, and the measurable outcome (fewer reads and LLM calls) is covered by the witnesses.

### Deviations

- Test home: Proof's supporting test plan named `tests/test_pipeline.py` for the probe-batching embed-call count. It is in `tests/test_db.py` (`test_probe_embeddings_are_batched_per_note`) because Proof protects the whole of `tests/test_pipeline.py`; no behavior or scope change.

## Audit

## Revisions

### R1 — 2026-11-22 — Supporting obligation: backfill `node_lookup` when missing or empty
- Verdict: REVISE — primary claim and all four guardrails PROVED (RED reproduced on `dc5c34a`), scope HELD, gates PASS on `c6375e6`; duty VIOLATED because `node_lookup` was backfilled only when the table was missing, not when it existed but was empty, so an interrupted first open left lookups empty and ingestion would create duplicates (probe `scratchpad/audit2/probe_lookup.log`). Also: the probe-batching test home moved without a recorded deviation. Independence: fresh-context.
- Changed: `src/stock_ontology/db.py` — writable open rebuilds `node_lookup` when the table is new or any node lacks a lookup row (also covers nodes written by older code, the audit's first residual risk). `tests/test_db.py` — `test_node_lookup_backfills_when_table_exists_but_misses_nodes`, RED before and GREEN after. `README.md` — the `upsert_node` rule now matches the code (raw deletes and other-column updates such as `relink_document`'s `facets_json` changes are allowed). Build records the test-home deviation. Candidate is now `12187d1`.
- Re-audit: pending; candidate `12187d1`
