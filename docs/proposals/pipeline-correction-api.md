---
proposal_id: "pipeline-correction-api"
state: ACCEPTED
witness: independent
candidate: "2031c5e @ worktree claude/pipeline-correction-api-47e1d2"
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

Candidate: `1e2b8cf @ worktree claude/pipeline-correction-api-47e1d2` (witness commit on top of `378e6a5`; RED observed on this exact tree)

**Protected witness**
- `Every correction job applies its graph change and queues its consensus refresh through a public IngestionPipeline method` — `tests/test_pipeline.py` / `test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus`
  - Defect and boundary: there's no public pipeline method that applies a reviewed `note.ontology.correction` payload. The graph writes live in `Worker._run_ontology_correction`, so the rule crosses the worker/pipeline component boundary.
  - Public name Build must implement: `IngestionPipeline.apply_note_correction(path: Path, reviewed: dict[str, Any]) -> None`. `reviewed` is the exact dict `review_note_correction` returns. The method opens its own (nestable) transaction, does not refresh consensus, and raises `NoteConflictError` on a stale note.
  - Setup: the shipped registry is ingested from three notes. Acme holds Ron, Acme Widgets and `WORKS_AT` Ron→Acme. Beta holds Ron's rumor about Beta Gears. Gamma holds Gamma Tools. The person correction reviewed from the Acme note is `{"organization": "Gamma Tools", "accuracy": "low"}`.
  - Assertion (conflict): if the Acme note file changes after review, `apply_note_correction` raises `NoteConflictError`, and the person node, the note's edges, the note's entity membership and `consensus_refresh` rows are all unchanged. This proves the stale-note guardrail and the no-partial-write guarantee. Limit: it doesn't cover a graph change after review (the worker's re-review comparison stays in the worker and is still covered by the existing web/worker tests).
  - Assertion (apply): once the reviewed text is restored, the same payload applies. Ron's facets become `organization=Gamma Tools, accuracy=low`. The reviewed `WORKS_AT` edge keeps its `edge_id` and now points to Gamma Tools. Gamma Tools joins the note's entity membership. The consensus target goes up for Acme (the note's company before), Gamma (after) and Beta (the company of Ron's rumor in another note), and all three stay in `pending_consensus()`, so the method queues the refresh without running it. Proves: the public method reproduces the worker's person, edge, membership and consensus-queue outcome. Limit: it doesn't prove the worker calls this method, that `_wrote` shares the transaction (guardrail), or the `relationship` and `relationship_add` kinds. Those stay covered by the existing end-to-end tests the Frame lists.
  - Satisfiability: I checked that the witness can pass by running it GREEN against a scratch monkeypatch of the current worker logic, loaded as a pytest plugin from the scratchpad. That code was never committed and isn't evidence.
- `worker.py contains no graph-row writes and references no private IngestionPipeline member` — `tests/test_worker.py` / `test_worker_applies_graph_changes_only_through_public_pipeline_methods`
  - Defect and boundary: `Worker` calls `pipeline._refresh_consensus`, `_current_note_doc` and `_evidence_changed`, and it calls `upsert_node`, `update_edge`, `upsert_edge` and `add_note_entities` directly. That is the worker/pipeline component boundary.
  - Assertion: an AST walk of `class Worker` in `stock_ontology.worker` finds no `_`-prefixed attribute on any pipeline-typed name and no call to those four graph-write methods. Pipeline-typed names are parameters annotated `IngestionPipeline`, plus names assigned from `IngestionPipeline(...)` or `self._pipeline(...)`. Proves the structural half of the primary claim. Limit: the check is static and name-based (`getattr` or aliasing would evade it), and it doesn't prove outcomes stay the same.
  - Deviation from the Frame's wording: the check covers `class Worker`, not the whole module. The module-level `_rollout_record_metadata` (`worker.py:186`) calls `db.upsert_node` on a disposable rollout-preview copy. That code is registry rollout, outside this proposal's allowed scope, so a module-wide check would force an out-of-scope edit.
- Protected paths: `tests/test_pipeline.py`, `tests/test_worker.py` (the two witnesses above, plus the existing correction tests the Frame lists as guardrails).
- Protected revision: `1e2b8cf5e72037d58ae3bde8c0fcc8fb9928aac2`

**Red evidence**
- `uv run pytest "tests/test_pipeline.py::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus" "tests/test_worker.py::test_worker_applies_graph_changes_only_through_public_pipeline_methods" -vv` → 2 failed.
  - The pipeline witness gets past ingest and review, then fails with `AttributeError: 'IngestionPipeline' object has no attribute 'apply_note_correction'`.
  - The worker witness fails listing private uses at lines 451, 552, 555 and 577 (`_refresh_consensus`, `_current_note_doc`, `_evidence_changed`) and graph writes at lines 537, 545, 547 and 549 (`upsert_node`, `update_edge`, `upsert_edge`, `add_note_entities`).
  - The other 53 tests in both files pass.
  - Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/proof-red.log`
- The primary claim has no proof until this command is observed RED. It was observed RED on `1e2b8cf`.

**Supporting test plan**
- Shared private frame in `pipeline.py` with the six note-reader corrections ported onto it (per-method affected-company sets kept) → Build: existing `tests/test_pipeline.py` correction tests (`test_note_correction_updates_only_current_note_edges`, `test_delete_note_relationship_removes_only_its_pending_edge`, `test_add_note_relationship_accepts_required_fields_from_shipped_registry`) and `tests/test_web_notes.py::test_note_reader_extraction_workflow` must stay green without edits. They catch a lost edit, a wrong affected set or a missing refresh.
- Public `refresh_consensus` used by `_finish_consensus` and `_run_ingest` → Build: existing `tests/test_worker.py` consensus tests (`test_late_consensus_attempt_cannot_publish_over_newer_evidence`, `test_consensus_refresh_rows_commit_with_extraction_and_roll_back_with_it`) stay green. They catch a changed refresh or retry behavior.
- Guardrail: the ontology correction still moves its job to the consensus stage in the same transaction as the graph write, and a conflict leaves the graph unchanged → Build: existing `tests/test_web_ontology.py::test_ontology_registry_editing_note_correction`, `::test_ontology_registry_editing_relationship_add_source` and `tests/test_pipeline.py::test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors` stay green without edits.

## Build

Candidate: `2031c5e @ worktree claude/pipeline-correction-api-47e1d2`

### Files changed

- `src/stock_ontology/pipeline.py` — adds private `_correct_note(path, expected_hash, edit, *, doc_id=None, refresh=True)`, the one transaction frame (check note, edit, recheck, queue consensus, refresh after commit). Ports `add_note_entity`, `delete_note_entity`, `relink_note_entity`, `add_note_relationship`, `delete_note_relationship` and `correct_note_relationship` onto it with their existing affected-company sets. Adds public `apply_note_correction(path, reviewed)`, which applies a reviewed `note.ontology.correction` with `refresh=False` and raises `NoteConflictError` when the current doc is not the reviewed `doc_id`. Renames `_refresh_consensus` to public `refresh_consensus(company_ids, report=None) -> IngestReport`. Satisfies the primary claim.
- `src/stock_ontology/worker.py` — `_run_ontology_correction` keeps the outer `immediate` transaction, `_check`, the re-review comparison and `_wrote`, and replaces its graph writes with `pipeline.apply_note_correction(path, fresh)`. `_finish_consensus` and `_run_ingest` call `pipeline.refresh_consensus`. `open_store`, `run_once` and the `_run_correction` dispatch are untouched. Satisfies the primary claim and the same-transaction guardrail.
- `README.md` — one constraint entry: apply correction graph changes through public `IngestionPipeline` methods and keep graph writes and private pipeline calls out of `Worker`, guarded by both witnesses.

### Unit evidence

- `uv run pytest "tests/test_pipeline.py::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus" "tests/test_worker.py::test_worker_applies_graph_changes_only_through_public_pipeline_methods" -vv` — RED on `1e2b8cf` (recorded in Proof); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/proof-red.log`.
- No new unit tests: the shared frame's supporting obligations are owned by the existing correction tests Proof's supporting test plan names, which pass unedited.

### Green evidence

- Decisive witness and gate: `uv run pytest -q` — 553 passed (551 before plus the 2 witnesses); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/build-green.log`.
- `git diff 1e2b8cf -- tests/` — empty; protected witnesses and guardrail tests unchanged.
- `uv run ruff check .` — all checks passed.

### Intervention record

- None: internal refactor with no user-facing outcome to measure.

### Deviations

- None. One behavior note for Audit: `relink_note_entity` with a replacement equal to the original entity used to return inside the transaction before the second note check and the empty consensus queue; it now runs both (queueing nothing), so a stale note there raises `NoteConflictError` instead of silently doing nothing.

## Audit

Candidate: `2031c5e @ worktree claude/pipeline-correction-api-47e1d2` (audited at HEAD `f66d9f2`; `git diff --quiet 2031c5e HEAD -- src tests README.md` confirms the audited source, tests and README are identical to `2031c5e`)

Independence: fresh-context. Before this audit I had seen only the task brief: the ledger path, the candidate identity and the repository. I read the ledger, the diffs and the witnesses myself and saw none of the builder's or prover's working context.

Primary-claim verdict: PROVED. Evidence:
- Both protected witnesses are unchanged. `git diff 1e2b8cf 2031c5e -- tests/` is empty, and `1e2b8cf` resolves to the recorded protected revision `1e2b8cf5e72037d58ae3bde8c0fcc8fb9928aac2`.
- I reproduced RED myself on a `git archive 1e2b8cf` tree with `PYTHONPATH` pointed at that tree's `src`. Both tests failed: the pipeline witness with `AttributeError: 'IngestionPipeline' object has no attribute 'apply_note_correction'`, and the AST witness on its private-use and graph-write findings. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/audit-red.log`.
- On the candidate, `uv run pytest "tests/test_pipeline.py::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus" "tests/test_worker.py::test_worker_applies_graph_changes_only_through_public_pipeline_methods" -vv` gives 2 passed. Log: `.../scratchpad/audit-witness.log`.
- The diff confirms the shape. `Worker._run_ontology_correction` now calls only `pipeline.apply_note_correction(path, fresh)`. `_finish_consensus` and `_run_ingest` call public `refresh_consensus`.
- `grep` finds no `_refresh_consensus`, `_evidence_changed` or `_current_note_doc` reference outside `pipeline.py` in `src`.
- In `worker.py`, the only remaining graph write is module-level `_rollout_record_metadata` at line 186. That is the rollout-preview path Proof deliberately scoped out of the check.

Limit: the AST witness is static and name-based, so `getattr` or aliasing would evade it. "Outcomes stay the same" for the `relationship` and `relationship_add` ontology kinds rests on the existing end-to-end tests, not on the decisive witness.

Guardrail verdicts:
- Existing correction tests stay green without edits: PROVED. Evidence:
  - `git diff --stat aa1d9f7 2031c5e -- tests` shows only the two witness additions.
  - I ran the Frame and Proof guardrail set with `uv run pytest`: `test_web_ontology.py::test_ontology_registry_editing_note_correction`, `::test_ontology_registry_editing_relationship_add_source`, `test_web_notes.py::test_note_reader_extraction_workflow`, the four named `test_pipeline.py` correction tests and the two `test_worker.py` consensus tests. Result: 16 passed, counting parametrized cases. Log: `.../scratchpad/audit-guardrails.log`.

  Limit: these tests cover only the scenarios they exercise.
- Ontology correction moves its job to the consensus stage in the same transaction as its graph write: PROVED. Evidence:
  - By inspection, `apply_note_correction` and `self._wrote(db, job)` both still run inside the worker's `db.transaction(immediate=True)`.
  - `apply_note_correction` passes `refresh=False`, so no consensus publish happens inside the outer transaction.
  - `OntologyDB.transaction` nesting means only the outer transaction commits.
  - The end-to-end ontology correction tests pass unedited.

  Limit: no test injects a crash between the graph write and `_wrote` to observe a retry directly. This rests on code inspection plus the existing tests.
- A correction whose note or reviewed graph changed after review fails with a conflict and leaves the graph unchanged: PROVED. Evidence:
  - The witness's conflict assertion passes: a stale note raises `NoteConflictError`, and the person node, the note's edges, its entity membership and the `consensus_refresh` rows are all unchanged.
  - The worker's `fresh != reviewed` re-review comparison is retained unchanged.
  - `test_ontology_registry_editing_note_correction` passes.

  Limit: the graph-changed-after-review path is covered only by the existing web and worker tests, not by the new witness.

Scope and duty verdict: scope HELD; duties HELD. Evidence:
- The changed files are `src/stock_ontology/pipeline.py`, `src/stock_ontology/worker.py` (only `_run_ontology_correction`, `_finish_consensus` and `_run_ingest`), `README.md` and the ledger.
- `open_store`, `run_once`, the elif dispatch, `services/corrections.py` and the JS files are untouched.
- The supporting obligations are met:
  - One private `_correct_note` frame. Its `doc_id` keyword is needed for the reviewed-doc check.
  - The six note-reader methods are ported, with their per-method affected sets preserved: empty for `add_note_entity`, before-only for the deletes, before plus after for relink and correct, after-only for add.
  - Public `apply_note_correction` with `refresh=False`.
  - Public `refresh_consensus`.
- The cheaper alternative was correctly not taken.
- Frame lists `Invariants changed: None`, and no existing README invariant or non-Proof test was altered.
- The one new `README.md` entry satisfies the constraint-capture duty. It has a `**Why:**`, and its `**Guarded by:**` names two tests that exist and pass.

Limit: `relink_note_entity` with a replacement equal to the original now runs the second note check inside the transaction. Before, it returned early. In practice this changes behavior only if the note file changes between two in-transaction reads. `mark_consensus_pending(set())` writes nothing, so the no-op path is otherwise identical. Build disclosed this as a behavior note rather than a deviation. I judge it within the Frame's "no outcome change" exclusion, but it is not covered by a test. `refresh_consensus` now returns its `IngestReport`, which no caller uses. That is trivial added surface.

Test homes: `tests/test_pipeline.py` (`test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus`) is the permanent owner of `IngestionPipeline` correction behavior. `tests/test_worker.py` (`test_worker_applies_graph_changes_only_through_public_pipeline_methods`) is the permanent owner of `Worker` structure. Both were authored by Proof at `1e2b8cf` and left unedited by Build, which added no tests.

Full gates: PASS. Results:
- `uv run pytest -q`: 553 passed. Log: `.../scratchpad/audit-full.log`.
- `uv run ruff check .`: all checks passed. Log: `.../scratchpad/audit-ruff.log`.

Limit: offline suite with fake LLM clients only, as `AGENTS.md` requires. No live worker or web run was exercised.

Residual risks:
- The AST witness can be evaded by `getattr`, aliasing or a pipeline name that is neither annotated nor assigned from `IngestionPipeline(...)` or `self._pipeline(...)`. A future regression of that shape would pass.
- The narrow race change in a no-op `relink_note_entity` (stale note now raises `NoteConflictError`) has no test.
- The same-transaction retry guarantee for ontology corrections is shown by inspection, not by a crash-injection test.

Recommendation: ACCEPT
Packet: No further pipeline action. Merging and deploying the branch stay human-owned and need separate authorization. Logs are under `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/` (`audit-red.log`, `audit-witness.log`, `audit-full.log`, `audit-guardrails.log`, `audit-ruff.log`).

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
