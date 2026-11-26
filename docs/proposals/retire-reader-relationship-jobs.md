---
proposal_id: "retire-reader-relationship-jobs"
state: ACCEPTED
witness: independent
candidate: "fac6bfe @ branch retire-reader-relationship-jobs"
---

# Proposal: Retire the legacy note-reader relationship jobs

## Proposal

### Intent

The note reader's three relationship routes (`web/notes/routes.py`, `_reviewed_correction`) still pass the retired job-kind names `note.relationship`, `note.relationship.add` and `note.relationship.delete` into `review_reader_correction` (`services/corrections.py`). That adapter maps them through `READER_RELATIONSHIP_KINDS` to the Ontology review kinds and rebuilds a `changes` dict. `NoteRelationshipRequest.reverse` is still accepted and re-reads the note's edges, though `note_reader.js` now swaps endpoints itself and never sends it. The worker keeps a `job.kind in READER_RELATIONSHIP_KINDS` branch in `_run_ontology_correction`, and `JOB_KINDS` still declares the three kinds so jobs queued before deploy can drain. `_reviewed_correction` also copies `_submitted`'s not-found mapping.

Benefit: one correction vocabulary from browser to worker. The adapter, the unused `reverse` field, the second edge read, the legacy worker branch and three job-kind entries go away, and adding a correction rule touches one review path.

### Tentative primary claim

The note reader submits relationship corrections in the same `{kind, edge_id, changes}` shape as the Ontology page, and no code path accepts or names a `note.relationship*` job kind.

### Why now

Priority: high. Found in the 2026-11-26 /simplify pass. The compatibility layer only exists until queued legacy jobs drain after deploy, and it doubles the job-kind list that `job-kind-registry` set out to make single.

### Known constraints

Deploy first, and confirm no `note.relationship*` job is queued or running on the server before the kinds are removed. A leftover one should fail with a clear message, not run. The web app stays read-only; corrections still go through the worker.

### Non-goals

None stated.

### Open choices

- Whether the reader posts to the existing `/api/notes/relationship*` URLs with the new shape, or reuses `/api/ontology/corrections/preview` and `/confirm`.
- Whether a leftover legacy job is failed by a one-time repair command or by the worker on claim.

## Frame

Candidate: `cef04a5 @ main` (clean checkout)

### Verified reality
- `uv run pytest tests/test_web_notes.py tests/test_worker.py tests/test_ontology_mutations.py tests/test_pipeline.py tests/test_relationships.py -q` at `cef04a5`: 161 passed. Proves the suites that judge this change were green before it started. Limit: does not run the browser script.
- `src/stock_ontology/web/notes/routes.py:43-62` (`NoteRelationshipRequest`, `NoteRelationshipAddRequest`, `NoteRelationshipDeleteRequest`) and `:165-195` (`_reviewed_correction` and the three routes). Proves the reader posts flat `relation`/`from_id`/`to_id`/`facets`/`reverse` fields, the routes pass the retired names `note.relationship`, `note.relationship.add` and `note.relationship.delete` to `review_reader_correction`, then queue `note.ontology.correction`, and `_reviewed_correction` repeats `_submitted`'s not-found mapping. Limit: none for the server side.
- `src/stock_ontology/services/corrections.py:225-258` (`READER_RELATIONSHIP_KINDS`, `review_reader_correction`). Proves the adapter maps kind names, builds `changes` from non-None fields, adds `facets` on an add, swaps endpoints from a second `_note_edges` read when `reverse` is set, and checks `expected_hash` against the review's revision with `service_error.stale_source_note`. That last check is the only behavior the reader routes need to keep. Limit: none.
- `src/stock_ontology/services/corrections.py:108-221` (`review_note_correction`). Proves it already handles `relationship`, `relationship_add` with an empty `record`, and `relationship_delete`, so it can take the reader's request directly. Limit: none.
- `src/stock_ontology/web/static/note_reader.js:110-144` and `src/stock_ontology/web/static/editor.js:215-219`. Prove the browser always sends `relation`, `from_id` and `to_id`, sends `facets` only on an add, sends `expected_hash` from `reader.dataset.hash`, never sends `reverse` (the swap button flips the inputs through `relationshipEditor.swap`), and posts to `/api/notes/${action}`. Limit: not exercised by any automated test.
- `src/stock_ontology/worker.py:53-55, 259, 572-574`. Prove the worker imports the adapter, routes the three legacy kinds to `_run_ontology_correction`, and reviews them there through `review_reader_correction`. `src/stock_ontology/worker.py:457-462` (`_run`) proves that a claimed job whose kind has no executor raises `ServiceError("invalid", "Unknown job kind: <kind>")`. Limit: does not show how the queue records that failure; `tests/test_worker.py` owns that behavior.
- `src/stock_ontology/services/processing.py:46-56` (`JOB_KINDS`). Proves the three kinds are declared `JobKind(0, "retired")` and cannot be submitted. `src/stock_ontology/worker.py:267` proves the worker refuses to start when `_executors` and `JOB_KINDS` disagree, so both must lose the kinds together. Limit: none.
- Production server check, run by the human on 2026-11-27. The deployed release is `595cc53`, which does not contain `90e1230` (`git merge-base --is-ancestor` is false; 75 commits behind `main`). `ontology.db.commands` is empty, and the `jobs` table holds no `note.relationship*` row in any state. Proves no legacy job is waiting to drain today. Limit: a job could be queued on the server between that check and the deploy.
- Human decision (2026-11-27): ship this in the same deploy that moves the server from `595cc53` to `main`, with no separate drain deploy. A legacy job queued in that window fails as `Unknown job kind`, and its edit must be redone. Human decision (2026-11-27): keep the `/api/notes/relationship`, `/relationship/add` and `/relationship/delete` URLs, with the browser sending `{edge_id, changes, expected_hash}`.
- Tests that use the legacy names or shapes: `tests/test_web_notes.py` (`test_note_reader_extraction_workflow`:488-513 sends `reverse`; `test_note_reader_can_correct_both_relationship_endpoints`; `test_note_reader_adds_and_deletes_relationships`; `test_note_reader_adds_and_deletes_entities`:948; the `_edit`/`_add`/`_delete` builders at 1133-1150 used by `test_note_reader_and_ontology_page_judge_a_relationship_correction_alike`; `test_queued_legacy_relationship_jobs_are_judged_by_the_same_review`; `test_note_reader_reverse_reviews_like_the_swapped_endpoints`), `tests/test_pipeline.py:2047-2154` (`_reader_correction` and its three callers, including the `reverse` parameter case), `tests/test_ontology_mutations.py:504-520, 728-760, 826-860` (`_legacy` and its six cases), and `tests/test_worker.py:423, 484` (`_DECLARED_KINDS` and the refused-submission loop). Limit: the line ranges are as of `cef04a5`.

### Final primary claim
- The note reader posts each relationship correction to its existing `/api/notes/relationship*` URL as `{file, edge_id, changes, expected_hash}`, and that correction is judged and applied exactly as the same edit from the Ontology page is. No source file under `src/` names a `note.relationship*` job kind, and nothing accepts a `reverse` field.

### Routing
- Witness: `independent`
- Why: it changes the browser-to-route request contract and the web-to-worker job-kind set, and it writes stored graph data through corrections.
- Human-owned irreversible action: merging to `main`, and the single production deploy that moves the server from `595cc53` to `main` with this change included.

### Decisive witness
- Layer: web route tests through the FastAPI test client, with jobs run by the real worker against a temporary database.
- Permanent owner: `tests/test_web_notes.py::test_note_reader_and_ontology_page_judge_a_relationship_correction_alike`
- Witness: with `_edit`, `_add` and `_delete` building the reader payload as `{edge_id, changes, expected_hash}` from the same `changes` dict the Ontology edit uses, all 11 cases still produce the same status, message and resulting graph for the reader and the Ontology page. A payload that has the old flat `relation`/`from_id`/`to_id` fields and no `changes` is rejected with 422 and queues nothing.

### Guardrail claims
- A `note.relationship`, `note.relationship.add` or `note.relationship.delete` job already in the queue when the worker starts is claimed and ends `failed` with error code `invalid` and the message `Unknown job kind: <kind>`. The note graph is unchanged and the worker keeps processing other jobs.
- A reader correction whose `expected_hash` does not match the note's processed revision is still refused at submit with 409 `service_error.stale_source_note`, and queues nothing.
- Submitting any `note.relationship*` kind through `ProcessingService.submit_correction` is still refused as `invalid`.

### Supporting obligations
- Replace the three request models with one shape: `file`, `edge_id` (default `""`), `changes` (default `{}`), `expected_hash`. The route supplies `kind` from its URL (`relationship`, `relationship_add` or `relationship_delete`) and calls `review_note_correction` directly. Unit-test candidate: the existing `test_note_reader_extraction_workflow` stale-hash assertion at :513.
- Move the `expected_hash` check from `review_reader_correction` into the reader route, and have `_reviewed_correction` reuse `_submitted`'s not-found mapping instead of repeating it.
- Delete `READER_RELATIONSHIP_KINDS` and `review_reader_correction`. Delete the three retired entries from `JOB_KINDS`, the legacy keys in `Worker._executors`, and the `READER_RELATIONSHIP_KINDS` branch and imports in `worker.py`.
- `note_reader.js`: build `payload.changes = {relation, from_id, to_id}` for an edit, the same plus `facets` (when non-empty) for an add, and send only `edge_id` for a delete. This is the same shape `ontology_edit.js:102-104` builds.
- Update the tests listed in Verified reality to the new shape. Remove `test_note_reader_reverse_reviews_like_the_swapped_endpoints`, the `reverse` case of `test_note_correction_updates_only_current_note_edges`, and the six `_legacy` mutation cases. Point `tests/test_pipeline.py::_reader_correction` at `review_note_correction`. Replace `test_queued_legacy_relationship_jobs_are_judged_by_the_same_review` with a test of the first guardrail. Drop the retired rows from `_DECLARED_KINDS`. `test_every_declared_job_kind_has_a_good_and_a_bad_case` must pass with the shorter table.
- A source check, such as `rg -n "note\.relationship" src`, returns nothing.

### Allowed scope
- Reuse: the existing reader URLs and `_submitted`; `review_note_correction` and `note.ontology.correction` as the only review and queue path; the existing alike test as the decisive witness; `Worker._run`'s unknown-kind failure for leftover jobs, with no new repair command.
- Cheaper alternative: keep the browser's flat payload and delete only the worker branch, the `JOB_KINDS` entries and `reverse`, leaving a route-local mapping from flat fields to `changes`. Rejected: the human-approved claim and decision require the reader to send the same `{kind, edge_id, changes}` shape as the Ontology page, and a route-local mapping is the adapter under another name.
- Include: `src/stock_ontology/web/notes/routes.py`, `src/stock_ontology/services/corrections.py`, `src/stock_ontology/services/processing.py`, `src/stock_ontology/worker.py`, `src/stock_ontology/web/static/note_reader.js`, `README.md` (the two rules under Invariants changed), and the tests named in Supporting obligations.
- Exclude/protect: `/api/ontology/corrections/preview` and `/confirm` and `ontology_edit.js`, which must not change; `review_note_correction`'s rules and `IngestionPipeline.apply_note_correction`; the entity routes (`relink`, `entity/add`, `entity/delete`) and `_run_correction`; the reader template and its swap button; the web app's read-only database rule; `deploy.sh` and the server. The follow-up `one-job-kind-declaration` is out of scope.

### Invariants changed
- `README.md:239` — today: "The note reader reviews at submit and queues the reviewed payload as `note.ontology.correction`; `note.relationship*` jobs can no longer be submitted, and the worker reviews any still queued by the same rules", guarded in part by `tests/test_web_notes.py::test_queued_legacy_relationship_jobs_are_judged_by_the_same_review`. After: the note reader posts `{edge_id, changes, expected_hash}`, reviews at submit and queues `note.ontology.correction`; no `note.relationship*` kind exists, and a leftover one fails as `Unknown job kind`. The guard becomes the replacement test for the first guardrail.
- `README.md:231` — today: "Retire a kind by marking it `retired`, not by deleting it, while queued jobs may still hold it." After: unchanged. This change deletes three retired kinds because the human confirmed on 2026-11-27 that no queued job holds them, and accepted that a job queued before the deploy fails.

### Decisions required
- None.

## Proof

Candidate: `e113c2e` (branch `retire-reader-relationship-jobs`), plus the test-only witness changes committed as `d215310`. RED was observed on that tree. No file under `src/` changed.

**Protected witness**
- Primary claim: the reader posts `{file, edge_id, changes, expected_hash}` to its existing URL and is judged and applied exactly as the Ontology page edit is. Owner: `tests/test_web_notes.py` / `test_note_reader_and_ontology_page_judge_a_relationship_correction_alike` (11 cases), via the builders `_edit`, `_add`, `_delete` and the new `_SOURCE_HASH`; plus `test_note_reader_and_ontology_page_judge_more_relationship_corrections_alike` via `_add_with_facets`.
  - Defect and boundary: the reader routes accept only the flat `relation`/`from_id`/`to_id`/`reverse` models and send them through the `note.relationship*` adapter. Boundary: browser request to FastAPI route, then review, then a `note.ontology.correction` job run by the real worker on a temporary database.
  - Assertion: the reader's `(phase, status, detail, graph)` equals the Ontology page's for every case. Proves the new shape reaches the same review and worker apply path with the same outcome. Limit: does not run `note_reader.js`, so it does not prove the browser builds this payload.
- Primary claim, retired shape: `tests/test_web_notes.py` / `test_note_reader_refuses_the_retired_flat_relationship_payload` (cases `flat-edit`, `reverse-edit`, `flat-add`).
  - Defect and boundary: the routes still accept the flat fields and `reverse`. Boundary: HTTP route to the job queue.
  - Assertion: 422, the job queue unchanged after worker intake (`_queued_job_ids`), and the note graph unchanged. Proves nothing accepts the old flat payload or `reverse`. Limit: covers the edit and add URLs; the delete shape does not change.
- Guardrail 1, leftover legacy job: `tests/test_web_notes.py` / `test_leftover_legacy_relationship_jobs_fail_as_unknown_kind`. It replaces `test_queued_legacy_relationship_jobs_are_judged_by_the_same_review`.
  - Defect and boundary: the worker still has executors for the three kinds and applies them. Boundary: queued job row to worker claim to job status API and graph.
  - Assertion: three `note.relationship*` jobs queued at priority 0 ahead of a valid `note.ontology.correction`. The valid job ends 200. Each legacy job ends `failed` with `error_code == "invalid"` and `error == "Unknown job kind: <kind>"`, and the graph shows only the valid correction. Proves a leftover job fails clearly, changes nothing, and does not stop the worker. Limit: the jobs are inserted with a literal priority, so it does not prove how the previous release prioritized them.
- Guardrail 2, stale `expected_hash`: `tests/test_web_notes.py` / `test_note_reader_refuses_a_relationship_correction_for_an_older_revision` (cases `edit`, `add`, `delete`).
  - Defect and boundary: the `expected_hash` check lives in the adapter that this change deletes, so it must survive the move into the route. Boundary: HTTP route to the job queue.
  - Assertion: with the note unchanged and `expected_hash` set to `"0"*64`, the response is 409 with the `service_error.stale_source_note` message, and the queue and graph are unchanged. Limit: the behavior already holds today in the old shape. `edit` and `add` are RED only because the new shape gets 422, and `delete` passes today, so it is a regression guard, not proof.
- Guardrail 3, `submit_correction` refuses `note.relationship*` as `invalid`: this already holds at `e113c2e`, because `JOB_KINDS` marks the kinds `retired`. The closing loop of `test_leftover_legacy_relationship_jobs_fail_as_unknown_kind` asserts it as a regression guard for when the entries leave `JOB_KINDS`. It is not counted as proof.
- Protected paths: in `tests/test_web_notes.py`, the functions `test_note_reader_and_ontology_page_judge_a_relationship_correction_alike`, `test_note_reader_and_ontology_page_judge_more_relationship_corrections_alike`, `test_note_reader_refuses_the_retired_flat_relationship_payload`, `test_note_reader_refuses_a_relationship_correction_for_an_older_revision` and `test_leftover_legacy_relationship_jobs_fail_as_unknown_kind`, and the helpers `_SOURCE_HASH`, `_edit`, `_add`, `_delete`, `_add_with_facets`, `_queued_job_ids`, `_reader_judgement`, `_ontology_judgement`, `_judged`, `_run_job`, `_note_graph` and `_correction_workspace`. The rest of the file is open to Build for the supporting updates Frame lists.
- Protected revision: `d215310` (`git diff --stat e113c2e d215310` gives `tests/test_web_notes.py`, 104 insertions and 37 deletions).

**Red evidence**
- `uv run pytest tests/test_web_notes.py -q -k "judge_a_relationship_correction_alike or judge_more_relationship or retired_flat or older_revision or leftover_legacy" -p no:cacheprovider` → `19 failed, 3 passed`. The orchestrator reproduced it on the same tree. Log: `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-5wagqH/1f55141b-79fc-4311-8dae-7b370704d3ed/scratchpad/prove-red.log`.
  - `judge_a_relationship_correction_alike`: 9 of 11 fail, because the reader gets 422 `Field required` for the new payload while the Ontology page gets the expected result. The two delete cases pass, since that shape is unchanged.
  - `judge_more_relationship_corrections_alike`: 4 of 4 fail with the same 422.
  - `refuses_the_retired_flat_relationship_payload`: 3 of 3 fail with `assert 202 == 422`.
  - `refuses_a_relationship_correction_for_an_older_revision`: `edit` and `add` fail with 422 instead of 409. `delete` passes.
  - `leftover_legacy_relationship_jobs_fail_as_unknown_kind`: fails with 409 instead of 200, because the legacy `note.relationship.add` job ran and added `a BUY c`, and the valid correction then collided with it.
  - Every failure is an assertion failure caused by the missing behavior. There are no import or setup errors.
- The primary claim and Guardrail 1 have no proof until this command is observed RED, and it was. Guardrail 2 has only a shape-transition RED. Guardrail 3 has no RED because it already holds.

**Supporting test plan**
- Source check `rg -n "note\.relationship" src` returns nothing → Build: run it as a gate. Catches leftover kind names.
- Worker startup check that `_executors` and `JOB_KINDS` agree → Build: `tests/test_worker.py`, dropping the retired rows from `_DECLARED_KINDS`. `test_every_declared_job_kind_has_a_good_and_a_bad_case` must pass with the shorter table. Catches drift between the two lists.
- `tests/test_pipeline.py::_reader_correction` points at `review_note_correction`, and the `reverse` case is removed → Build: `tests/test_pipeline.py`. Catches imports of the deleted adapter.
- The six `_legacy` cases are removed → Build: `tests/test_ontology_mutations.py`. Catches dependence on the deleted adapter.
- `note_reader.js` builds `changes` → no automated owner. Audit records the browser payload as manually unverified.

## Build

Candidate: `fac6bfe` (branch `retire-reader-relationship-jobs`)

### Files changed

- `src/stock_ontology/web/notes/routes.py`: replaces the three relationship request models with one `NoteRelationshipRequest` (`file`, `edge_id=""`, `changes={}`, `expected_hash`, extra fields forbidden). Each URL supplies its kind (`relationship`, `relationship_add`, `relationship_delete`) and calls `review_note_correction` directly. The `expected_hash` check moves here from the adapter, and `_note_error` gives `_submitted` and `_reviewed_correction` one not-found mapping. Satisfies the primary claim and Guardrail 2.
- `src/stock_ontology/services/corrections.py`: deletes `READER_RELATIONSHIP_KINDS` and `review_reader_correction`. Satisfies the primary claim.
- `src/stock_ontology/services/processing.py`: deletes the three `retired` entries from `JOB_KINDS`. Satisfies the primary claim and Guardrail 1. The `retired` submit value and its docstring stay, since README still names it for future retirements.
- `src/stock_ontology/worker.py`: drops the adapter imports, maps only `note.ontology.correction` to `_run_ontology_correction`, and removes the legacy review branch. A leftover kind now reaches `_run`'s `Unknown job kind`. Satisfies Guardrail 1.
- `src/stock_ontology/web/static/note_reader.js`: builds `payload.changes = {relation, from_id, to_id}`, adds `facets` on an add only when non-empty (as `ontology_edit.js:102-104` does), and sends `edge_id` on an edit. Satisfies the primary claim.
- `tests/test_web_notes.py` (unprotected parts only): moves `test_note_reader_extraction_workflow` (the old `reverse` call becomes explicitly swapped endpoints), `test_note_reader_can_correct_both_relationship_endpoints`, `test_note_reader_adds_and_deletes_relationships`, `test_note_reader_adds_and_deletes_entities` and `test_note_reader_form_opened_before_an_ontology_correction_cannot_reapply` to the new shape, and removes `test_note_reader_reverse_reviews_like_the_swapped_endpoints`.
- `tests/test_pipeline.py`: points `_reader_correction` at `review_note_correction`. The `reverse` case of `test_note_correction_updates_only_current_note_edges` becomes a `swap` case with explicit endpoints, which keeps its "a corrected edge gets a new ID" assertion. `test_delete_note_relationship_removes_only_its_pending_edge` and `test_add_note_relationship_accepts_required_fields_from_shipped_registry` move to the new kinds.
- `tests/test_ontology_mutations.py`: removes the six `note.relationship*` cases, the `_legacy` and `_ids` helpers, and the now-unused imports.
- `tests/test_worker.py`: drops the retired rows from `_DECLARED_KINDS`, and drops the retired-priority assertion from `test_corrections_are_claimed_ahead_of_earlier_extraction`.
- `README.md:239`: rewrites the relationship-correction rule as Frame's Invariants changed states. The Why line names this proposal (2026-11-27), and Guarded by replaces `test_queued_legacy_relationship_jobs_are_judged_by_the_same_review` with `test_note_reader_refuses_the_retired_flat_relationship_payload` and `test_leftover_legacy_relationship_jobs_fail_as_unknown_kind`.

### Unit evidence

- Supporting tests were updated rather than newly authored. No new internal behavior needed a unit RED first: the route change is covered by the protected witness, and the remaining work was removal.
- `uv run pytest tests/test_web_notes.py tests/test_worker.py tests/test_ontology_mutations.py tests/test_pipeline.py tests/test_relationships.py -q`, after the source change and before the test updates → 18 failed, 149 passed. Every failure was a supporting test still using the old shape, the legacy adapter or the retired kinds, matching Frame's list. No log kept.
- The same command after the test updates → GREEN, all passed (included in the gate below).

### Green evidence

- Decisive witness: `uv run pytest tests/test_web_notes.py -q -p no:cacheprovider -k "judge_a_relationship_correction_alike or judge_more_relationship or retired_flat or older_revision or leftover_legacy"` → 22 passed. Log: `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-5wagqH/1f55141b-79fc-4311-8dae-7b370704d3ed/scratchpad/build-witness.log`.
- Protected witness integrity: an AST comparison of the 17 protected functions and helpers in `tests/test_web_notes.py` against `d215310` shows none changed.
- Gate: `uv run pytest -q -p no:cacheprovider` → 629 passed. Log: `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-5wagqH/1f55141b-79fc-4311-8dae-7b370704d3ed/scratchpad/build-gate.log`.
- Gate: `uv run ruff check src tests` → clean.
- Gate: `rg -n "note\.relationship" src` → no matches.

### Intervention record

- None. There is no repository intervention ledger, and the user-facing outcome (the reader's relationship editor behaving the same) has no metric. The browser payload built by `note_reader.js` was not exercised in a browser.

### Deviations

- None. One note for Audit: Frame's supporting obligation said to remove the `reverse` case of `test_note_correction_updates_only_current_note_edges`. Build converted it to an explicit endpoint swap in the same test file instead, so the new-ID assertion keeps an owner. The file is in scope, and no protected path changed.

## Audit

Candidate: `fac6bfe` (branch `retire-reader-relationship-jobs`). Audited from the tree at ledger commit `d8b3749`. `git diff --quiet fac6bfe HEAD -- src tests README.md` confirms its code, tests and README are identical to `fac6bfe`.

Independence: fresh context. The auditor saw only the ledger path, the candidate identity, the repository and the audit brief, and took no part in Frame, Proof or Build.

Primary-claim verdict: PROVED.
- The protected witness is unchanged. An AST comparison of all 17 protected functions and helpers in `tests/test_web_notes.py`, decorators and parametrize lists included, between `d215310` and `fac6bfe` finds every one the same (`/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-5wagqH/1f55141b-79fc-4311-8dae-7b370704d3ed/scratchpad/audit-protected.log`).
- RED reproduced independently. On a `git archive d215310` copy, the witness selection gave 19 failed, 3 passed, all assertion failures (`.../scratchpad/audit-red.log`).
- On the candidate, `uv run pytest tests/test_web_notes.py -q -p no:cacheprovider -k "judge_a_relationship_correction_alike or judge_more_relationship or retired_flat or older_revision or leftover_legacy"` gives 22 passed (`.../scratchpad/audit-witness.log`).
- `rg -n "note\.relationship" src` finds no matches (`.../scratchpad/audit-rg.log`). `NoteRelationshipRequest` sets `extra="forbid"` and has no `reverse` field.
- Read only, not run: `note_reader.js` builds `changes = {relation, from_id, to_id}`, adds `facets` only when non-empty on an add, and sends `edge_id` on edit and delete.
- Limit: no test runs `note_reader.js`. The flat-payload refusal is tested on the edit and add URLs, not delete.

Guardrail verdicts:
- A leftover `note.relationship*` job fails as `Unknown job kind`, the graph is unchanged, and the worker continues: PROVED. The test was RED at `d215310` and is GREEN at `fac6bfe`. Limit: the jobs are inserted at literal priority 0, and a job queued between the human's server check and the deploy is not covered.
- A stale `expected_hash` is refused with 409 `service_error.stale_source_note` and nothing is queued: PROVED. The check now lives in `_reviewed_correction`, after the review, which is the adapter's order. Limit: the RED was a shape-transition RED for edit and add, and the delete case is a regression guard.
- `submit_correction` refuses `note.relationship*` as `invalid`: PROVED as a regression guard only. It never had a RED, because the behavior already held.

Scope and duty verdict: scope HELD, duties HELD.
- `git diff --stat e113c2e fac6bfe` touches only the files Frame includes. `ontology_edit.js`, the templates, `deploy.sh` and `review_note_correction`'s rules are unchanged.
- `README.md:239` is rewritten as Frame's Invariants changed states, with a Why and a Guarded by that name existing, passing tests. `README.md:231` is unchanged.
- Two test edits go beyond the literal obligations. The disclosed `reverse` to `swap` conversion in `tests/test_pipeline.py`, and the dropped retired-priority assertion in `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction`, are both judged necessary consequences of Frame's deletions, made in files Frame includes. Limit: a stricter reading of "remove" would call them small deviations.

Test homes: `tests/test_web_notes.py` owns the note-reader routes and the witnesses. `tests/test_pipeline.py` owns the apply path. `tests/test_ontology_mutations.py` owns the job-kind mutation table. `tests/test_worker.py` owns the job-kind registry and claim order.

Full gates: PASS. `uv run pytest -q -p no:cacheprovider` gives 629 passed (`.../scratchpad/audit-gate.log`). `uv run ruff check src tests` is clean (`.../scratchpad/audit-ruff.log`). The source check finds no matches. Limit: all gates are offline with fake LLMs, and nothing ran in a browser.

Residual risks:
- The browser payload from `note_reader.js` has no automated owner. A manual check of edit, add with and without facets, swap-then-save, and delete is still unverified.
- A `note.relationship*` job queued on the server after the 2026-11-27 check and before the deploy fails as `Unknown job kind`, and its edit must be redone. The human accepted this.
- A browser tab left open across the deploy with the old JS cached gets a 422 until it is reloaded.

Recommendation: ACCEPT
Packet: no rework. The human-owned steps are a manual browser check of the reader's relationship editor, the merge to `main`, and the single deploy from `595cc53`. Re-confirm that no `note.relationship*` job is queued right before deploying.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
