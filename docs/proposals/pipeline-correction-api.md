---
proposal_id: "pipeline-correction-api"
state: FRAMED
witness: independent
candidate: "aa1d9f7 @ worktree claude/pipeline-correction-api-47e1d2"
---

# Proposal: Corrections owned by the pipeline, not the worker

## Proposal

### Intent

The worker's `note.ontology.correction` executor (`worker.py`, `_run_ontology_correction`) writes graph rows itself with `upsert_node`, `update_edge`, `upsert_edge` and `add_note_entities`. The worker also calls private pipeline methods: `_current_note_doc`, `_evidence_changed` and `_refresh_consensus`. The six note-reader correction methods in `pipeline.py` each repeat the same frame: open a transaction, re-check the note revision, edit, re-check, collect affected companies, mark evidence changed, refresh consensus.

Benefit: the worker goes back to claiming and running jobs, and the evidence and consensus rules live in one place. A pipeline change can no longer silently break the worker through a private method, and the repeated transaction frame becomes one helper, so a new correction is a few lines.

### Tentative primary claim

Every correction job applies its graph change through a public pipeline method, and the worker contains no graph-editing logic of its own.

### Why now

Found in the 2026-11-24 simplify review. It pairs naturally with `unified-note-corrections` and is cheaper to do first.

### Known constraints

None stated.

### Non-goals

None stated.

### Open choices

- Sequence relative to `unified-note-corrections`: before it, after it, or as one change.

## Frame

Candidate: `aa1d9f7 @ worktree claude/pipeline-correction-api-47e1d2`

### Verified reality
- `uv run pytest -q` on `aa1d9f7` — proves the suite judging this change was green before it started (551 passed); limit: does not prove every correction path is covered.
- `src/stock_ontology/worker.py:523` `Worker._run_ontology_correction` — proves the worker writes graph rows itself (`db.upsert_node`, `db.update_edge`, `db.upsert_edge`, `db.add_note_entities`) and calls private `pipeline._current_note_doc` (line 552) and `pipeline._evidence_changed` (line 555), all inside one `db.transaction(immediate=True)` that also re-reviews with `services/corrections.py:114` `review_note_correction`, checks the claim (`self._check`) and moves the job to its consensus stage (`self._wrote`); limit: none.
- `src/stock_ontology/worker.py:451` (`_finish_consensus`) and `:577` (`_run_ingest`) — proves the worker also calls private `pipeline._refresh_consensus`; limit: `_finish_consensus` and `_run_ingest` are outside `open_store`/`run_once`, so changing them does not collide with `worker-connection-reuse`.
- `src/stock_ontology/pipeline.py:868-990` — proves the six note-reader corrections (`add_note_entity`, `delete_note_entity`, `relink_note_entity`, `add_note_relationship`, `delete_note_relationship`, `correct_note_relationship`) each repeat: open `db.transaction()`, `_current_note_doc`, edit, `_current_note_doc` again, collect affected companies, `_evidence_changed`, then `_refresh_consensus` after commit; limit: the affected-company set differs per method (none for `add_note_entity`, before-only for delete, before plus after for relink and correct, after-only for add), so a shared frame must let each edit return its own set.
- `src/stock_ontology/db/storage.py:159` `OntologyDB.transaction` — proves transactions nest by depth and only the outermost commits, so a pipeline method's transaction can run inside the worker's `immediate` one; limit: consensus refresh must not run inside the worker's outer transaction, because `_rebuild_company_consensus` publishes in its own transaction after synthesis.
- `src/stock_ontology/pipeline.py:126-137` — proves `_evidence_changed` calls `commit_check`, which the worker sets in `Worker._pipeline` (`worker.py:417`) to recheck its claim and record company revisions; limit: none.
- `grep` over `src` and `tests` for `_refresh_consensus`, `_evidence_changed`, `_current_note_doc` outside `pipeline.py` — proves the worker is the only outside caller; limit: none.
- `tests/test_web_ontology.py::test_ontology_registry_editing_note_correction` and `::test_ontology_registry_editing_relationship_add_source`, `tests/test_web_notes.py::test_note_reader_extraction_workflow`, `tests/test_pipeline.py::test_note_correction_updates_only_current_note_edges`, `::test_delete_note_relationship_removes_only_its_pending_edge`, `::test_add_note_relationship_accepts_required_fields_from_shipped_registry` — prove end-to-end coverage of ontology corrections (person, relationship, relationship_add, stale note, ownership race) and note-reader corrections; limit: none calls a pipeline method for the ontology correction directly, because none exists.

### Final primary claim
- Every correction job applies its graph change and queues its consensus refresh through a public `IngestionPipeline` method: `src/stock_ontology/worker.py` contains no graph-row writes and references no private `IngestionPipeline` member, while correction outcomes (graph rows, note conflicts, consensus refresh) stay the same.

### Routing
- Witness: `independent`
- Why: it moves the code that writes stored graph data for user corrections across the worker/pipeline component boundary, so a mistake corrupts or silently drops a correction.
- Human-owned irreversible action: merging and deploying the branch.

### Decisive witness
- Layer: unit tests on `IngestionPipeline` plus a static check on the worker module.
- Permanent owner: `tests/test_pipeline.py` (public correction method) and `tests/test_worker.py` (worker structure).
- Witness: (1) calling the new public `IngestionPipeline` method with a reviewed person correction (from `review_note_correction`) updates the person node and its reviewed edges, records the note's new entity membership, and marks consensus pending for the note's companies plus the person's rumor companies on an accuracy change; when the note file changes before the call it raises `NoteConflictError` and writes nothing. (2) An AST check of `worker.py` finds no attribute access starting with `_` on a pipeline object and no call to `upsert_node`, `update_edge`, `upsert_edge` or `add_note_entities`.

### Guardrail claims
- The existing correction tests listed above stay green without edits.
- An ontology correction still moves its job to the consensus stage in the same transaction as its graph write, so a retried job never applies it twice.
- A correction whose note or reviewed graph changed after review still fails with a conflict and leaves the graph unchanged.

### Supporting obligations
- Add one private frame in `pipeline.py` (for example `_correct_note(path, expected_hash, edit, *, refresh=True)`) that opens the transaction, resolves the current doc, runs `edit(doc_id)` returning affected company IDs, re-checks the note, queues `_evidence_changed`, and refreshes consensus after commit unless `refresh=False`. Port the six note-reader corrections onto it with their current affected sets.
- Add a public method (for example `apply_note_correction(path, reviewed)`) that applies a reviewed `note.ontology.correction` payload through the same frame with `refresh=False`, raising `NoteConflictError` if the current doc is not the reviewed `doc_id`.
- Make consensus refresh public (`refresh_consensus`) and use it from the worker's `_finish_consensus` and `_run_ingest`.
- Keep in the worker: the outer `immediate` transaction, `self._check`, the re-review comparison, `self._wrote`, and `_finish_consensus`.

### Allowed scope
- Reuse: `IngestionPipeline`'s existing note-correction helpers (`_current_note_doc`, `_evidence_changed`, `_canonical_note_edge`) and the existing correction tests as permanent owners.
- Cheaper alternative: renaming the three private methods to public and leaving the graph writes in the worker. Rejected because the primary claim needs the graph writes out of the worker and the six repeated frames folded.
- Include: `src/stock_ontology/pipeline.py`; `Worker._run_correction`, `_run_ontology_correction`, `_finish_consensus`, `_run_ingest` in `src/stock_ontology/worker.py`; new tests in `tests/test_pipeline.py` and `tests/test_worker.py`.
- Exclude/protect: `Worker.open_store` and `Worker.run_once` (owned by `worker-connection-reuse`); the correction-kind elif dispatch (owned by `job-kind-registry`); edge validation in `services/corrections.py` and unifying the two correction APIs (owned by `unified-note-corrections`); `web/static/note_reader.js` and `ontology_edit.js`; any change to correction outcomes or error messages.

### Invariants changed
- None.

### Decisions required
- None. The Proposal's open choice was settled by the human through the starting session: this proposal goes first, before `unified-note-corrections`, as its own change.

## Proof

<!-- Replaced only by proposal-prove, or by the orchestrator with the builder-route
deferred-witness status. Reference native witness path, exact command, concise RED
result, and candidate identity. -->

## Build

<!-- Replaced only by proposal-build. Reference changed paths, protected witnesses,
exact GREEN command(s), concise result, candidate identity, and deviations. -->

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
