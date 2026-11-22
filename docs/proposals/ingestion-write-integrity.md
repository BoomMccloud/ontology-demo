---
proposal_id: "ingestion-write-integrity"
state: ACCEPTED
witness: independent
candidate: "tree:808c88c2facb @ /Users/jasonbxu/Documents/GitHub/stock_ontology"
---

# Proposal: Ingestion write integrity

## Proposal

Status: approved as drafted by the human on 2026-11-22. The recommended
option is chosen for unresolved choices 1 to 3. Choice 4 had no
recommendation; Frame decides whether it blocks.

### Outcome

Ingestion leaves `ontology.db` consistent after every run, including runs that
fail partway, and stays consistent as the database grows. Each guarantee is
enforced where data is written, pinned by a regression test, and backed by a
periodic repair job that cleans up data written before the fix and any drift
the write path cannot catch.

### Motivation

Four defects in `src/stock_ontology/pipeline.py` and `src/stock_ontology/db.py`
can corrupt or fragment the graph.

1. **Partial writes duplicate data.** Each `upsert_node` and `upsert_edge`
   commits on its own. Old artifacts are only deleted when the note already has
   an ingestion log entry. If a new note fails partway (for example an
   embedding call fails), its events and edges stay in the DB without a log
   entry, and the next run writes a second copy with new random IDs.
2. **Relations drift because the registry is not applied at ingest.** The
   pipeline only uppercases relation names. The registry's alias and inverse
   rules, and its resolver in `registry.py`, are used only by `audit`, after
   the fact. The current DB has 39 relation names, including `PARTNER_WITH`,
   `PARTNER_OF`, and `PARTNERS_WITH`, `HAS_EMPLOYEE` beside its registered
   inverse `WORKS_AT`, and `RELATED_TO` beside `RELATES_TO`.
3. **Name lookup fails silently at scale.** `find_by_name_or_alias` loads up
   to 5,000 nodes into Python per call. The edge-reference fallback searches
   all node types ordered by recency, so events and views push older canonical
   entities out of the window. Past 5,000 nodes it misses existing entities and
   creates duplicates. The DB has 264 nodes today, so this is latent.
4. **One bad file aborts the run.** `_scan_files` reads files outside any error
   handling, so one non-UTF-8 note crashes the whole run instead of landing in
   `report.errors`. `watch` has no error handling, so the same failure ends the
   loop.

### Approach

Three layers, in this order.

1. **Write path.**
   - Wrap each document's writes in one transaction that always clears the
     note's prior artifacts first. `doc_id` is derived from the path, so this
     is safe for new and modified notes alike. Individual DB writes stop
     committing on their own when called inside it.
   - Resolve every relation through the registry before writing: rename
     aliases, flip direction for inverse aliases. Give the extraction prompt the
     registry's relation list.
   - Replace the Python scan in `find_by_name_or_alias` with a SQL lookup on
     name and aliases. Restrict the edge-reference fallback to entities and
     themes.
   - Isolate per-file read errors into `report.errors`. `watch` catches errors
     per tick and keeps running.
2. **Regression tests**, one per defect:
   - A new note whose embedding fails midway leaves no rows. A rerun produces
     exactly one copy.
   - An extracted `HAS_EMPLOYEE` edge is stored as a flipped `WORKS_AT` edge.
   - An old company still resolves after more than 5,000 newer events.
   - A non-UTF-8 file is reported in `report.errors` and the other notes still
     ingest.
3. **Periodic repair.**
   - A new `stock-ontology repair` command applies only deterministic fixes:
     delete artifacts whose `source_doc_id` has no ingestion log entry, rewrite
     alias and inverse relations to canonical form, and merge entities that are
     exact name or alias duplicates. It reuses the detection already in
     `audit.py`. `audit` itself stays read-only.
   - Judgment calls (unknown relations, near-duplicate entities found by vector
     distance) go to `ontology_registry.json` as `pending` suggestions for a
     human to approve. Once approved, the next `repair` applies them.

Static checks are a small supporting piece: add ruff with the `BLE`, `TRY`,
and `PLW1514` rule sets, and type `upsert_edge` to accept only a
registry-resolved relation so a raw LLM string fails type checking.

### Constraints

- `audit` and the query agent stay strictly read-only. `repair` is the only new
  writer, and it opens the DB the same way ingestion does.
- No change to the 4-node schema or the registry file format beyond what
  `suggestions` already supports.
- Tests stay offline and use the existing fake LLM fixtures.
- `repair` must be idempotent: a second run on the same DB changes nothing.

### Non-goals

- Items 5 to 11 from the ingestion review (rename detection, mtime-based
  scanning, embedding batching, catalog size cap, `_process_document` split,
  sentiment helper, consensus reload). The transaction work may make part of
  the `_process_document` split natural, but it is not a goal here.
- An LLM agent that writes to the DB.
- Scheduling infrastructure beyond documenting how to run `repair` on a timer.

### Unresolved choices

1. **Unknown relations at ingest.** Store the edge as-is and queue a pending
   suggestion, or drop the edge until the relation is approved. Recommended:
   store and queue, so no extracted signal is lost.
2. **How `repair` runs.** A standalone command run by cron or launchd, or also
   every N ticks of `watch`. Recommended: standalone first.
3. **Exact-duplicate entity merges.** Apply automatically in `repair`, or queue
   for approval like fuzzy matches. Recommended: automatic for exact name or
   alias matches, since the pipeline would have merged them at write time.
4. **Static checks scope.** Add both ruff and a type checker (pyright), or only
   ruff for now. Neither is configured today.

## Frame

Candidate: `tree:8544199b47ab @ /Users/jasonbxu/Documents/GitHub/stock_ontology (no git; sha256 over sorted src/ and tests/ *.py plus src/**/*.json)`

### Verified reality
- `uv run pytest -q` on this candidate — 60 passed, 8 failed; the 8 failures are exactly the Proof witnesses in `tests/test_pipeline.py` and `tests/test_repair.py`; every other suite, including `tests/test_web.py`, is green; limit: the witnesses were authored before this Frame rerun.
- Since the first Frame, other sessions added `reembed_all_nodes` (`src/stock_ontology/pipeline.py`), `OntologyDB.replace_node_embeddings` and `list_all_nodes` (`src/stock_ontology/db.py:481`, `:556`), and a `reembed` CLI command (`src/stock_ontology/cli.py:129`); proves a second DB writer path exists; limit: it does not touch per-document ingestion.
- `src/stock_ontology/db.py` — 8 `with self.conn:` blocks (lines 127, 214, 253, 314, 432, 447, 452, 495), so each `upsert_node`, `upsert_edge`, `delete_document_artifacts`, and `replace_node_embeddings` commits on its own; limit: nesting `with self.conn:` cannot form an outer transaction.
- `src/stock_ontology/pipeline.py:249` `_process_document` — deletes prior artifacts only when `replace_old_doc_id` is set; `doc_id` is derived from `rel_path` in `run()`; Proof RED confirms a new note that fails midway leaves a row.
- `src/stock_ontology/pipeline.py:375` — relation is only uppercased; `OntologyRegistry.resolve_relation` (`src/stock_ontology/registry.py:223`) returns `canonical` and `flip_direction`; `IngestionPipeline.__init__` (`pipeline.py:87`) takes no registry.
- `ontology_registry.json` — registered aliases/inverses are `CORROBORATES`, `HAS_EMPLOYEE`, `PARTNER_OF`, `PARTNER_WITH`, `RELATED_TO`; limit: most observed drift names are unregistered.
- Read-only query of `ontology.db` — 264 nodes, 458 edges, 39 relation names; limit: snapshot only.
- `src/stock_ontology/db.py:527` `find_by_name_or_alias` — Python scan of `list_nodes(limit=5000)`; `pipeline.py:208` calls it with no `node_type`.
- `src/stock_ontology/pipeline.py:108` — `read_text` outside per-file error handling; `pipeline.py:520` `watch` has no error handling.
- `src/stock_ontology/audit.py` `run_ontology_audit` and `cli.py:728` `audit --sync` — classify edges against the registry and queue unmapped relations via `OntologyRegistry.sync_suggestions`; limit: no orphan-artifact or exact-duplicate detection.
- `tests/test_registry_audit.py` and `tests/test_web.py` seed `HAS_EMPLOYEE`/`PARTNER_WITH` through `db.upsert_edge`; proves `upsert_edge` must keep accepting raw relation strings.
- `pyproject.toml` — no ruff or type checker configured.

### Final primary claim
- After any ingestion run, including one where a new or modified note fails partway, `ontology.db` holds exactly one set of artifacts per ingested note and none for notes without an ingestion log entry, and every edge whose relation is a registered alias or inverse is stored under its canonical name and direction.

### Routing
- Witness: independent
- Why: the change rewrites and deletes rows in the stored `ontology.db` and crosses the pipeline, DB, registry, and CLI components.
- Human-owned irreversible action: running `stock-ontology repair` (or a re-ingest) against the real `ontology.db`. No stage runs either against it; all evidence uses temporary databases.

### Decisive witness
- Layer: offline pytest integration tests over a temporary SQLite DB with fake LLM clients.
- Permanent owner: `tests/test_pipeline.py` (ingestion claims) and `tests/test_repair.py` (repair claims).
- Witness: a mid-note failure on a new note leaves zero rows for that note and no log entry, and a healthy rerun yields exactly one copy; an extracted `HAS_EMPLOYEE` edge is stored as `WORKS_AT` with endpoints flipped; `repair` on a seeded DB removes an orphaned doc artifact and canonicalizes alias and inverse edges.

### Guardrail claims
- An existing entity still resolves by name or alias when more than 5,000 newer nodes exist, so no duplicate entity is created.
- A non-UTF-8 note is reported in `report.errors` while every other note ingests, and `watch` continues to the next tick after a run raises.
- `repair` is idempotent, and `audit`, the query agent, and the web UI still open the DB read-only.

### Supporting obligations
- Add `OntologyDB.transaction()` (depth-counted) so `upsert_node`, `upsert_edge`, `delete_document_artifacts`, and `replace_node_embeddings` commit only at the outermost scope; unit test rollback in `tests/test_db.py`.
- `_process_document` always calls `delete_document_artifacts(doc_id)` inside that transaction before writing; canonical entity/theme upserts in the same scope roll back too.
- `IngestionPipeline` takes an optional `OntologyRegistry` (default `create_minimal_registry()`); `cli.ingest` and `cli.watch` pass `load_registry(settings.registry_path)`.
- Relation resolution happens in the pipeline, not in `db.upsert_edge`. Unknown relations are stored as uppercased raw names; queuing reuses `audit --sync`, so ingestion does not write the registry file.
- Add the registry relation names to the extraction prompt in `src/stock_ontology/llm/prompts.py`.
- Replace `find_by_name_or_alias` with a SQL query over `name` and `json_each(aliases_json)`; `_resolve_node_ref` fallback searches entity and theme types only.
- Per-file read errors append to `report.errors`; `watch` catches per tick.
- Add `stock-ontology repair` (CLI) backed by `repair_ontology(db, registry)` in a new `src/stock_ontology/repair.py`: delete orphaned doc artifacts, canonicalize alias/inverse edges, merge exact name/alias duplicates within the same `node_type` and `entity_type` (repoint edges, union aliases, delete the loser and its vector).
- Add ruff to the dev group with `BLE`, `TRY`, `PLW1514`; fix or `noqa` findings in touched files only.
- Update `README.md` usage with the `repair` command and how to run it periodically.

### Allowed scope
- Reuse: `OntologyRegistry.resolve_relation` and `create_minimal_registry`; `audit --sync` for pending relation suggestions; `delete_document_artifacts`; `FakePipelineLLM` and the Proof witnesses.
- Cheaper alternative: only call `delete_document_artifacts(doc_id)` unconditionally before writing, with no transaction. Rejected because a mid-note failure would still leave partial rows and canonical entity changes until the next run.
- Include: `src/stock_ontology/db.py`, `src/stock_ontology/pipeline.py`, `src/stock_ontology/llm/prompts.py`, `src/stock_ontology/cli.py`, new `src/stock_ontology/repair.py`, `tests/test_db.py`, new tests in `tests/test_pipeline.py` or `tests/test_repair.py` outside the protected witnesses, `pyproject.toml`, `uv.lock`, `README.md`.
- Exclude/protect: `ontology.db`, `ontology_registry.json`, `data/`; `audit.py` stays read-only; `reembed_all_nodes` behavior unchanged; no pyright or type-level relation enforcement (choice 4 resolved to ruff only, the cheapest option, since it is developer tooling, not a routed user surface); items 5 to 11 of the review; web and i18n files.

### Invariants changed
- None.

### Decisions required
- None.

## Proof

Candidate: `tree:8544199b47ab @ /Users/jasonbxu/Documents/GitHub/stock_ontology` (same hash command, run from repo root on the current tree; differs from `b9dc25bb53ee` only by the named edits to `tests/test_web.py`, `tests/test_i18n.py`, `src/stock_ontology/i18n.py`; `src/stock_ontology/repair.py` still absent; no files edited in this rerun).

**Protected witness**
- Primary claim, part 1 (mid-note failure leaves no rows; rerun yields one copy) — `tests/test_pipeline.py` / `test_pipeline_mid_note_failure_leaves_no_rows_and_rerun_yields_one_copy`
  - Defect and boundary: `_process_document` commits each `upsert_node`/`upsert_edge` separately and only deletes prior artifacts when `replace_old_doc_id` is set, so a new note failing after its first doc-scoped write leaves rows that the rerun duplicates; pipeline → DB transaction → ingestion log.
  - Assertion: after a run where the second event's embedding is malformed, no log entry, 0 nodes carrying that file's `source.file_path`, 0 edges, and no "Zeta Optics" entity; after a healthy rerun, exactly (2 nodes, 2 edges) under the logged `doc_id`, 2 nodes by file path, 1 Zeta entity; proves one artifact set per logged note and none for an unlogged note, including canonical entities; limit: failure injected during doc-node writes only, not during edge writes or consensus.
- Primary claim, part 2 (registered alias/inverse relations stored canonically) — `tests/test_pipeline.py` / `test_pipeline_stores_registered_alias_and_inverse_relations_canonically`
  - Defect and boundary: `pipeline.py` only uppercases the relation and holds no registry; extraction → registry → DB.
  - Assertion: an extracted `HAS_EMPLOYEE` company → person is stored as `(person, WORKS_AT, company)`, an extracted `partner with` is stored as `(company, PARTNERS_WITH, company)`, and no `HAS_EMPLOYEE`/`PARTNER_WITH` edges remain; uses the default pipeline registry (`create_minimal_registry`); limit: does not prove `cli ingest`/`watch` pass `load_registry(settings.registry_path)`. (Frame's witness text says "from person to company"; I used company → person, the direction where the inverse is semantically correct; the observable is the flipped endpoints either way.)
- Primary claim, repair half — `tests/test_repair.py` / `test_repair_removes_orphan_artifacts_and_canonicalizes_edges`
  - Defect and boundary: no repair exists for already-corrupted stored rows; registry + DB rewrite.
  - Assertion: after `repair_ontology(db, create_minimal_registry())`, the orphan doc's node, vector, and edges are gone, the logged doc's event and canonical entities remain, `PARTNER_WITH` becomes `PARTNERS_WITH` in the same direction, and `HAS_EMPLOYEE` becomes a flipped `WORKS_AT`; limit: does not exercise the `stock-ontology repair` CLI wiring.
- Repair duplicate merge (supporting obligation, witnessed because it deletes stored rows) — `tests/test_repair.py` / `test_repair_merges_exact_duplicates_within_same_type_only`
  - Assertion: two companies with an exact casefold name match merge into one survivor, the loser's node and vector are deleted, aliases are unioned, both edges are repointed to the survivor, and a same-named `person` entity survives; limit: does not pin which ID survives or cover alias-only matches.
- Guardrail, past 5,000 newer nodes — `tests/test_pipeline.py` / `test_pipeline_resolves_old_entity_past_5000_newer_nodes`
  - Defect and boundary: `find_by_name_or_alias` scans the newest 5,000 nodes in Python; pipeline resolution → DB query.
  - Assertion: with 5,001 newer events plus 5,001 newer person entities, re-extracting "LGC" yields only the company `ent_legacy`, and the by-name edge ref "Legacy Corp" points to `ent_legacy`; limit: also seeds newer *entities*, because typed lookup ignores events, so events alone cannot cause a duplicate; events alone only break the untyped edge-ref path.
- Guardrail, non-UTF-8 note — `tests/test_pipeline.py` / `test_pipeline_reports_non_utf8_note_and_ingests_the_rest`
  - Assertion: `run()` returns without raising, `report.errors` is exactly `_general/bad_encoding.md`, `files_processed == 5`, 5 log entries; limit: decode errors only, not other OS read errors.
- Guardrail, watch continues — `tests/test_pipeline.py` / `test_pipeline_watch_continues_after_a_run_raises`
  - Assertion: when the first `run` raises `RuntimeError`, `watch` calls `run` a second time (a `BaseException` sentinel stops the loop); limit: `run` is a monkeypatched double, so it proves only the per-tick catch.
- Guardrail, repair idempotence — `tests/test_repair.py` / `test_repair_is_idempotent`
  - Assertion: the node/edge/vector snapshot after a second repair equals the snapshot after the first; limit: compares DB state, not a "zero changes" return value, because Frame does not define the report shape.
- Protected paths: `tests/test_pipeline.py` (the five tests above after the `# Ingestion write integrity` banner, plus the imports `datetime`, `pytest`, `stock_ontology.pipeline as pipeline_module`) and `tests/test_repair.py`.
- Protected revision: sha256 `e261aac4be5dd35db59611ad9f83b54fb5aaf45f34002ee0e2004cdfeee40a2a` for `tests/test_pipeline.py`; sha256 `9fa23f160b9e2dbc2b8f9624c103bc41d64677471ab37146997fb9f81bfe5fb1` for `tests/test_repair.py`; both re-verified on this tree.

**Red evidence**
- `uv run pytest -q tests/test_pipeline.py -k "mid_note or registered_alias or 5000 or non_utf8 or watch_continues"` → 5 failed, all assertion failures: partial row left (`_count_nodes_for_file == 0` failed with 1); edges stored as `HAS_EMPLOYEE`/`PARTNER_WITH` with no `WORKS_AT`; duplicate company `ent_lgc_*` created; `pytest.fail` because `run()` aborted on `UnicodeDecodeError`; `pytest.fail` because `watch()` stopped after the tick-1 `RuntimeError`; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove/red_test_pipeline_rerun.log`.
- `uv run pytest -q tests/test_repair.py` → 3 failed with `Failed: stock_ontology.repair.repair_ontology is missing: repair behavior not implemented` (import deferred until after seeding succeeds; each seed checked first); limit: this RED shows missing behavior, not a wrong result, since Frame names no other repair API to fail against; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove/red_test_repair_rerun.log`.
- `uv run pytest -q` → 8 failed, 60 passed; only the 8 new witnesses fail and `tests/test_web.py` is green; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove/full_suite_rerun.log`.
- Each claim above has no proof until its command is observed RED.

**Supporting test plan**
- `OntologyDB.transaction()` commits only at the outermost scope and rolls back every write when the body raises → Build: `tests/test_db.py`; catches inner `with self.conn:` commits leaking through.
- The extraction prompt lists the registry relation names → Build: `tests/test_pipeline.py` (new test outside the protected witnesses) or a prompt unit test; catches a prompt that never mentions the canonical names.
- `stock-ontology repair` CLI wiring (writable DB, `load_registry(settings.registry_path)`) → Build: `tests/test_registry_audit.py` CLI style with `CliRunner`, or a new test in `tests/test_repair.py` added without touching the protected tests; catches an unwired CLI or one that opens the DB read-only.
- `cli ingest`/`watch` pass the loaded registry → Build: a CLI test; catches the default minimal registry being used in place of `ontology_registry.json`.
- `audit`, the query agent, and the web UI still open the DB read-only → already green in `tests/test_db.py::test_read_only_enforces_pragma_query_only`, `tests/test_agent.py`, `tests/test_web.py`; Build keeps them green; no RED possible because this is not missing behavior.

## Build

Candidate: `tree:808c88c2facb @ /Users/jasonbxu/Documents/GitHub/stock_ontology` (same hash command; no git). The builder produced `tree:d4343ca612eb` for R1; the tree then moved to `808c88c2facb` only because other Claude sessions in this working tree edited `src/stock_ontology/web/catalog.py` (15:06:43, `_safe_note_path` hardening) and `tests/test_web.py` (15:07:26). The builder did not edit either file; both are outside this proposal and are not part of Files changed.

### Files changed

- `src/stock_ontology/db.py` — `OntologyDB.transaction()` (depth-counted; only the outermost scope commits or rolls back) replaces the 7 per-method `with self.conn:` write blocks, satisfying the primary claim; `find_by_name_or_alias` is now one SQL query over `name` and `json_each(aliases_json)` using a registered `so_casefold` function, satisfying the 5,000-node guardrail.
- `src/stock_ontology/pipeline.py` — `IngestionPipeline` takes an optional `registry` (default `create_minimal_registry()`); each note's writes run in one transaction that first clears prior artifacts for `doc_id` and any old doc id (`_clear_prior_artifacts`), with the write body moved into `_write_extraction`; edges go through `_canonical_relation` (registry rename, inverse flip); `_resolve_node_ref` falls back to entity then theme only; the extraction catalog lists registry relation names; `_scan_files` returns unreadable files, which `run()` reports in `report.errors` and excludes from deletion; deletions and consensus rebuilds run in transactions; `watch` logs and continues after a failing tick.
- `src/stock_ontology/repair.py` — new `repair_ontology(db, registry) -> RepairReport` in one transaction: delete orphan doc artifacts, canonicalize alias/inverse edges, merge exact name/alias duplicates within the same `node_type` and `entity_type` (survivor is oldest `created_at`), drop self-loops and duplicate edges.
- `src/stock_ontology/cli.py` — `ingest` and `watch` pass `_load_ingest_registry(settings)` (falls back to the built-in registry with a warning when the file is missing); new `repair` command (`--db`, `--registry`, `--json`).
- `src/stock_ontology/llm/prompts.py` — catalog header tells the model the canonical relations are listed at the end.
- `tests/test_db.py` — supporting tests: nested-transaction rollback and single commit; casefold name/alias lookup by type; extraction catalog lists registry relations; `repair` CLI reports changes then zero; `ingest` CLI uses the registry file for relations.
- `pyproject.toml`, `uv.lock` — ruff dev dependency; `[tool.ruff.lint]` selects `BLE`, `TRY`, `PLW1514` with no global ignores. The 13 `TRY003` findings in touched files carry per-line `# noqa: TRY003` (8 in `db.py`, 4 in `pipeline.py`, 1 in `repair.py`), as Frame allows.
- `README.md` — `repair` usage and periodic-run note; three Ingestion Constraints entries, each with **Why** naming this proposal and **Guarded by** an existing witness: per-note transaction (mid-note witness), registry relation resolution in the pipeline before `upsert_edge` (alias/inverse witness), and SQL name/alias lookup with the entity/theme-only fallback (5,000-node witness).

### Unit evidence

- `uv run pytest -q tests/test_db.py` — GREEN: 11 passed; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build/unit_db.log`. No RED was observed for these supporting tests: they were written after the implementation, so they are regression tests only.

### Green evidence

- Decisive witness: `uv run pytest -q tests/test_pipeline.py -k "mid_note or registered_alias or 5000 or non_utf8 or watch_continues"` — pass (5 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build/witness_pipeline_r1.log`.
- Decisive witness: `uv run pytest -q tests/test_repair.py` — pass (3 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build/witness_repair_r1.log`.
- Gate: `uv run pytest -q` — pass (73 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build/full_suite_r1.log`.
- Gate: `uv run ruff check src/stock_ontology/db.py src/stock_ontology/pipeline.py src/stock_ontology/repair.py src/stock_ontology/cli.py src/stock_ontology/llm/prompts.py` — pass with no global ignores; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build/ruff_r1.log`. `uv run ruff check src` still reports 6 findings in untouched files (`llm/providers/gemini.py`, `models.py`, `web/catalog.py`), out of scope.
- Protected witnesses: `tests/test_pipeline.py` sha256 `e261aac4…40a2a` and `tests/test_repair.py` sha256 `9fa23f16…5fb1`, both unchanged from Proof. During Build, supporting tests were briefly appended to both files and then moved to `tests/test_db.py`, restoring both files byte-for-byte (pre-edit copies at `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build/protected/`).

### Intervention record

- None. The repository has no intervention ledger, and this change has no user-facing outcome to measure beyond the tests.

### Deviations

- None.

## Audit

Candidate: `tree:808c88c2facb @ /Users/jasonbxu/Documents/GitHub/stock_ontology`. I recomputed the stated hash command before and after this re-audit, and both runs gave `808c88c2facb`. The newest mtime under src/tests is still `tests/test_web.py` at 15:07:26, so the tree hasn't moved since R2.

Independence: fresh-context. Before this re-audit, this context had seen only the ledger, the repository, and its own audits of `8683fe2442b4` (R1) and `808c88c2facb` (R2). It did not frame, prove, or build the candidate.

Primary-claim verdict: PROVED
- Evidence: the protected witnesses are unchanged. `tests/test_pipeline.py` sha256 starts `e261aac4be5d` and `tests/test_repair.py` sha256 starts `9fa23f160b9e`, both matching Proof.
- RED was observed by Proof in `scratchpad/prove/red_test_pipeline_rerun.log` and `scratchpad/prove/red_test_repair_rerun.log`.
- I reran the pipeline witnesses with `uv run pytest -q tests/test_pipeline.py -k "mid_note or registered_alias or 5000 or non_utf8 or watch_continues"`: 5 passed (`scratchpad/audit/r2/witness_pipeline.log`).
- I reran `uv run pytest -q tests/test_repair.py`: 3 passed (`scratchpad/audit/r2/witness_repair.log`).
- Code read: the per-note `db.transaction()` always clears prior artifacts first, and relations resolve through the registry in `_canonical_relation`.
- My earlier temporary-DB probes still apply, because no src code has changed since: `scratchpad/audit/probe_edge_failure.log` shows a failed edge write on a modified note leaves the counts unchanged, and a healthy rerun leaves one artifact set.
- Limit: failure injection in the witness covers doc-node writes only, and the edge-write case is covered by my probe only. `ingest` loading `ontology_registry.json` is covered only by `tests/test_db.py::test_cli_ingest_uses_registry_file_for_relations`, which was never RED.

Guardrail verdicts:
- Old entity still resolves past 5,000 newer nodes: PROVED.
  - Evidence: `test_pipeline_resolves_old_entity_past_5000_newer_nodes` was RED in Proof and is green on my run. The lookup is SQL over `name` and `json_each(aliases_json)`, and the fallback is limited to entity and theme.
  - Limit: the lookup is an unindexed scan through a Python UDF.
- Non-UTF-8 note lands in `report.errors`, and `watch` continues after a failing tick: PROVED.
  - Evidence: `test_pipeline_reports_non_utf8_note_and_ingests_the_rest` and `test_pipeline_watch_continues_after_a_run_raises` were RED in Proof and are green on my run.
  - Limit: the watch witness uses a monkeypatched `run`.
- `repair` is idempotent, and `audit`, the agent and the web UI stay read-only: PROVED.
  - Evidence: `test_repair_is_idempotent` was RED and is now green. `scratchpad/audit/probe_repair.log` shows an alias-only merge with a self-loop: 2 changes on the first run, 0 on the second. `test_read_only_enforces_pragma_query_only`, `tests/test_agent.py` and `tests/test_web.py` are green in `scratchpad/audit/r2/full_suite.log`.
  - Limit: read-only has no RED by design, and `tests/test_web.py` was amended by another session.

Scope and duty verdict: scope HELD; duties HELD.
- R2 is answered. Build now names `808c88c2facb` and attributes the `src/stock_ontology/web/catalog.py` edit (15:06:43) and the `tests/test_web.py` edit (15:07:26) to other sessions sharing the tree. Neither file is in Files changed.
- That attribution fits what I observed. The catalog change is `_safe_note_path` hardening, unrelated to this proposal. The `tests/test_web.py` mtime falls after every Build R1 log. Frame and Proof had already recorded other sessions editing `tests/test_web.py`.
- The proposal's own changes are within Frame's Include list: `db.py`, `pipeline.py`, `repair.py`, `cli.py`, `llm/prompts.py`, `tests/test_db.py`, `pyproject.toml`, `uv.lock`, `README.md`.
- The protected files are byte-identical to Proof, and no existing README invariant or non-Proof test was changed by this proposal, which matches `Invariants changed: None`.
- Duties: `README.md` "Ingestion Constraints" carries all three rules this change established: the per-note transaction, registry relation resolution before `upsert_edge`, and the SQL name/alias lookup with the entity/theme-only fallback. Each has a **Why** and a **Guarded by** naming a test that exists and passes.
- `pyproject.toml` selects `BLE`, `TRY`, `PLW1514` with no global ignore, and the 13 per-line `# noqa: TRY003` sit in touched files, as Frame allows.
- Limit: there is no git, so the attribution rests on mtimes and the ledger's statement, not on a diff. The external edits stay in the tree but are not part of this candidate's changes.

Test homes:
- `tests/test_db.py` gets five supporting tests.
  - The transaction and lookup tests belong in the DB layer.
  - The extraction-catalog test belongs to `tests/test_pipeline.py`, and the repair and ingest CLI tests belong to `tests/test_repair.py` or a CLI test home. They landed in `tests/test_db.py` because the protected hashes cover the whole of `tests/test_pipeline.py` and `tests/test_repair.py`.
- `tests/test_pipeline.py` and `tests/test_repair.py` are byte-identical to Proof.

Full gates: PASS
- `uv run pytest -q`: 73 passed (`scratchpad/audit/r2/full_suite.log`).
- `uv run ruff check` on the 5 touched src files: exit 0 (`scratchpad/audit/r2/ruff.log`).
- Limit: these are offline fake-LLM tests only, and nothing ran against the real `ontology.db`.
- `uv run ruff check src` reports 41 findings, all in files this proposal didn't touch (`scratchpad/audit/r2/ruff_src.log`). It isn't a required gate, since Frame limits fixes to touched files.

Residual risks:
- Build's Green evidence still says `uv run ruff check src` reports 6 findings. Since the global TRY003 ignore was removed, it reports 41, all in untouched files. This is a ledger inaccuracy, not a gate failure.
- Other sessions edit this working tree concurrently, so the candidate identity only holds while the tree stays quiet. Re-hash before any human-owned action.
- After a merge, the survivor's embedding is stale.
- Self-loops removed by `repair` are not counted in `RepairReport`.
- `affected_company_ids` keeps IDs from a rolled-back note, which can cause a spurious consensus error.
- The name lookup is an O(n) scan.
- Three supporting tests sit outside their natural owner.
- Running `stock-ontology repair` or a re-ingest against the real `ontology.db` is still human-owned and has not been done. ACCEPT doesn't authorize it.

Recommendation: ACCEPT

Packet: no rework is required. Optionally, correct the `ruff check src` finding count in Build's Green evidence. Before the human runs `stock-ontology repair` on the real `ontology.db`, take a backup of it and recompute the candidate hash to confirm it's still `808c88c2facb`.

## Revisions

### R1 — 2026-11-22 — Duty: durable constraints the change established were not captured in README
- Verdict: REVISE — primary claim and all three guardrails PROVED, scope HELD, full gates PASS on `tree:8683fe2442b4`; duties VIOLATED because `README.md` recorded only the per-note transaction rule, leaving two rules this change paid for undocumented (registry relation resolution in the pipeline before `upsert_edge`; SQL name/alias lookup with the entity/theme-only fallback). Also noted: `pyproject.toml` ignored `TRY003` globally, narrowing the TRY rule set beyond Frame's "fix or noqa in touched files". Independence: fresh-context.
- Changed: `README.md` — added the two Ingestion Constraints entries with **Why** and **Guarded by** naming the existing witnesses. `pyproject.toml` — removed the global `TRY003` ignore; `src/stock_ontology/db.py`, `src/stock_ontology/pipeline.py`, `src/stock_ontology/repair.py` — added 13 per-line `# noqa: TRY003`, matching Frame's allowed scope. Candidate is now `tree:d4343ca612eb`.
- Re-audit: REVISE — claims PROVED and duties HELD, but scope EXPANDED because the audited tree `808c88c2facb` was not the named `d4343ca612eb`; see R2; candidate `tree:808c88c2facb`

### R2 — 2026-11-22 — Candidate identity: audited tree differed from the named Build candidate
- Verdict: REVISE — primary claim and guardrails PROVED, duties HELD, full gates PASS on `tree:808c88c2facb`; scope EXPANDED because that tree includes edits to `src/stock_ontology/web/catalog.py` and `tests/test_web.py` that Build did not list and the ledger could not attribute. Independence: fresh-context.
- Changed: ledger only. Build now attributes both files to other Claude sessions in the same working tree (the builder did not edit them) and restates the candidate as `tree:808c88c2facb`. No code or test changes.
- Re-audit: ACCEPT — claims and guardrails PROVED, scope and duties HELD, gates PASS; candidate `tree:808c88c2facb`
