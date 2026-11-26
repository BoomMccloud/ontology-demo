---
proposal_id: "retire-reader-relationship-jobs"
state: FRAMED
witness: independent
candidate: "cef04a5 @ main"
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
