---
proposal_id: "unified-note-corrections"
state: ACCEPTED
witness: independent
candidate: "90e1230 @ worktree claude/unified-note-corrections-0faa55"
---

# Proposal: One review path for note corrections

## Proposal

### Intent

A note correction that changes or adds a relationship can arrive two ways today. The note reader posts `/api/notes/relationship`, `/relationship/add` and `/relationship/delete`, which become `note.relationship*` jobs applied through `IngestionPipeline` methods. The Ontology page posts `/api/ontology/corrections`, which is reviewed by `services/corrections.py` and becomes a `note.ontology.correction` job with its own worker executor. Each path has its own edge validator, and they already disagree: one checks `matched`, the other `resolve_relation`, and they raise different error types. Identity edits (rename, aliases, keep previous name) are also written three times, in `services/registry.py`, `services/corrections.py` and the worker's rollout metadata.

Benefit: one set of rules for what a valid correction is, so a fix or new rule lands once. It removes a second API, a second worker executor and a second test surface, and the two pages can no longer accept an edit the other would reject.

### Tentative primary claim

A relationship or identity correction made from the note reader and the same correction made from the Ontology page are checked by the same rules and produce the same result.

### Why now

Found in the 2026-11-24 simplify review of the worker and web split. The drift is already visible, and the longer both paths take new rules, the harder they are to merge.

### Known constraints

Corrections still go through the worker as jobs. The web app stays read-only.

### Non-goals

None stated.

### Open choices

- Whether the note reader keeps its direct apply (no review step) or moves to review-then-confirm like the Ontology page.
- Whether the `note.relationship*` job kinds are retired or kept as aliases while queued jobs drain.

## Frame

Candidate: `aa33b7f @ worktree claude/unified-note-corrections-0faa55`

### Verified reality
- `uv run pytest -q` on `aa33b7f`: 553 passed. Proves the suite judging this change was green before it started. Limit: it doesn't prove both correction paths are covered for the same inputs.
- `src/stock_ontology/web/notes/routes.py:143` `_correction` and `:164-174`. Proves `/api/notes/relationship`, `/relationship/add` and `/relationship/delete` queue `note.relationship`, `note.relationship.add` and `note.relationship.delete` jobs with the raw request and validate nothing at submit. `_submitted` (`:133`) maps only `ServiceError`. Limit: none.
- `src/stock_ontology/worker.py:490` `_run_correction`. Proves the worker sends those kinds to `IngestionPipeline.correct_note_relationship`, `add_note_relationship` and `delete_note_relationship` (`pipeline.py:937-990`). Those methods validate with `_canonical_note_edge` (`pipeline.py:1035`): `canonicalize_edge(...).matched` and `endpoints_ok`, raising `ValueError`. Facets are checked only by `upsert_edge`'s `FacetSchemaError`. A corrected edge gets a new ID (`_replace_note_edge`, `:1056`, comment "Replacing the ID invalidates relationship forms opened before the correction"). Adding an identical edge twice is a silent upsert. Pending (unmapped) edges can be corrected or deleted. Limit: none.
- `src/stock_ontology/services/corrections.py:71` `_review_edge`. Proves the Ontology path validates with `resolve_relation`, editable facet keys (`edge_facet_keys - {"basis"}`), two distinct existing endpoints, `canonicalize_edge(...).endpoints_ok`, `check_facets` and a duplicate check. It raises `ServiceError` with locale keys. `review_note_correction` (`:114`) lists only non-pending edges, has no delete kind, and requires `relationship_add` to touch `record` and the note to be its source evidence. Limit: the two validators agree on most inputs. They differ on duplicates (reject vs. silent upsert), pending edges (not editable vs. editable), error type and message, and edge ID (kept by `update_edge` in `pipeline.py:1003` vs. replaced).
- `src/stock_ontology/pipeline.py:995` `apply_note_correction`. Proves the reviewed payload is applied through `_correct_note` with `update_edge` (ID kept) or `upsert_edge` (new edge). The worker's `_run_ontology_correction` (`worker.py:523`) re-reviews inside its `immediate` transaction and refuses a payload whose fresh review differs. Limit: it can't apply a delete or a pending-edge correction.
- `src/stock_ontology/web/ontology/routes.py:163-184`. Proves the Ontology page reviews at preview (`review_note_correction`, mapping `ServiceError` and `ValueError` through `rejected`) and queues the server-held payload as `note.ontology.correction` at confirm. Limit: none.
- `src/stock_ontology/services/processing.py:33` `CORRECTION_KINDS` and `:137` `submit_correction`. Prove `note.relationship*` are submittable kinds and share correction priority. Limit: none.
- Identity edits: `services/registry.py:73` `RegistryService.review_record_edit`, `services/corrections.py:132-160` (person branch of `review_note_correction`) and `worker.py:114` `_rollout_record_metadata`. Each assembles name and aliases (`keep_previous_name` and `unique_labels` in the first two; removed-alias merge in rollout), checks the alias length limit (first two), and checks that introduced labels don't identify another record or node, each with its own loop. Registry labels include the ticker. Rollout marks a collision `ambiguous` instead of raising. Limit: inputs differ (registry spec vs. graph node vs. registry diff), so only the assembly and collision rules can be shared.
- `src/stock_ontology/web/static/note_reader.js:140-170`. Proves the reader always sends `relation`, `from_id` and `to_id` (never `reverse`) and already shows a non-2xx `detail` string. So submit-time rejection needs no JS change. Limit: the API still accepts `reverse`.
- Tests that encode today's divergent rules: `tests/test_web_notes.py::test_note_reader_extraction_workflow` (invalid correction shows `data-job-state="failed"`), `::test_note_reader_adds_and_deletes_relationships` (identical add twice → both 200), `::test_note_reader_can_correct_both_relationship_endpoints`, and `tests/test_pipeline.py::test_note_correction_updates_only_current_note_edges[reverse]`, `::test_delete_note_relationship_removes_only_its_pending_edge` and `::test_add_note_relationship_accepts_required_fields_from_shipped_registry` (call the three pipeline methods directly). Also `::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus` (asserts the edited `WORKS_AT` keeps its `edge_id`) and `tests/test_worker.py:399` (submits `note.relationship.delete`).

### Final primary claim
- A relationship correction (edit, add or delete) submitted from the note reader and the same correction from the Ontology page are judged by one review, `review_note_correction`, and applied by one pipeline method, `apply_note_correction`. Given the same note, graph and edit, both return the same error code and locale key when invalid, and the same graph rows when valid.

### Routing
- Witness: `independent`
- Why: it moves validation of user corrections to stored graph data across the web/worker boundary and changes which corrections are accepted, so a mistake stores a bad edge or drops a valid correction.
- Human-owned irreversible action: merging and deploying the branch. Queued `note.relationship*` jobs drain on the new worker.

### Decisive witness
- Layer: web route tests driving one worker run (the `_note_action` pattern in `tests/test_web_notes.py`), plus one unit test on the shared identity rule.
- Permanent owner: `tests/test_web_notes.py`. The identity witness goes in `tests/test_web_ontology.py` or `tests/test_registry_governance.py`, the builder's pick.
- Witness: (1) A parametrized table of edits: unregistered relation, endpoints the registry forbids, same node at both ends, missing required edge facet, duplicate of an existing note edge, valid edit, valid add, delete of another note's edge, valid delete. Each goes through `/api/notes/relationship*` and through `/api/ontology/corrections/preview` plus confirm on the same fixture. Both produce the same HTTP error status and locale key, or the same resulting `list_note_edges` (ignoring generated IDs). (2) A person correction and a registry record edit given the same name/alias change apply the same rules: keep previous name, deduplicated aliases, alias over the name length limit rejected, a label that identifies another record rejected as `conflict`.

### Guardrail claims
- A `note.relationship`, `note.relationship.add` or `note.relationship.delete` job already queued before deploy still succeeds or fails on the new worker, judged by the same review. New ones can't be submitted.
- A correction whose note changed, or whose reviewed graph rows changed, after review still fails with a conflict and leaves the graph unchanged. A note-reader form opened before a correction to the same edge can't silently re-apply, because a corrected edge still gets a new ID.
- Existing Ontology-page correction tests (`tests/test_web_ontology.py::test_ontology_registry_editing_note_correction`, `::test_ontology_registry_editing_relationship_add_source`) and the person-accuracy test (`tests/test_pipeline.py::test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors`) stay green without edits.

### Supporting obligations
- Extend `review_note_correction` with a `relationship_delete` kind (before row, empty after). Include the note's pending edges as editable `before` rows, tagged so apply knows which table they live in. Make the `relationship_add` anchor rule (touches `record`, note is its source evidence) apply only when `record` is given. Map `FacetSchemaError` from facet checks to `ServiceError("invalid", ...)`.
- Add one converter in `services/corrections.py` from a note-reader request (`edge_id`, `relation`, `from_id`, `to_id`, `reverse`, `facets`) to a review request, resolving `reverse` against the current row. Use it from the note-reader routes and the worker's legacy-kind branch.
- Note-reader routes: review at submit with the converter, reject a given `expected_hash` that differs from the reviewed hash as `conflict`, map `ServiceError` and `ValueError`, and queue the reviewed payload as `note.ontology.correction`.
- `apply_note_correction`: delete for an empty `after`, and replace (new ID, keep `created_at`) instead of `update_edge` for an edited edge, from the pending or main table. Remove `correct_note_relationship`, `add_note_relationship` and `delete_note_relationship` from `IngestionPipeline`.
- Worker: for a queued `note.relationship*` job, convert, review and apply through the same `apply_note_correction` path, with no graph writes or private pipeline calls in `Worker`. Remove the three kinds from what `ProcessingService.submit_correction` accepts, but keep their correction priority so already-queued ones still run first.
- One edge validator: `_review_edge` and `IngestionPipeline._canonical_note_edge` (still used by relink) share one registry-level check, for example `OntologyRegistry.check_edge(relation, from_node, to_node, facets)`. It covers registered relation, two distinct existing endpoints, allowed endpoints and facet check. Each caller maps its error type.
- One identity rule in `services/registry.py`: a helper that assembles name and aliases (keep previous name, `unique_labels`, alias length limit) and a helper that tests whether introduced labels identify another record. `review_record_edit` and the person review use both. `_rollout_record_metadata` uses the collision helper, still marking a collision `ambiguous`.

### Allowed scope
- Reuse: the Ontology review (`review_note_correction`, `_review_edge`) and `IngestionPipeline.apply_note_correction` / `_correct_note` from `pipeline-correction-api`, the `note.ontology.correction` worker executor, and `tests/test_web_notes.py::_note_action`.
- Cheaper alternative: make only the two edge validators call one shared check and leave both APIs and job kinds. Rejected: the human chose one review path (decisions 1 and 2 below), and the claim needs the same duplicate, pending-edge and error rules, which live in the review, not the validator.
- Include: `src/stock_ontology/services/corrections.py`, `services/registry.py`, `services/processing.py` (`CORRECTION_KINDS` / submit guard only), `web/notes/routes.py`, `pipeline.py` (correction methods, `_canonical_note_edge`), `registry.py` (one shared edge check), `worker.py` (`_run_correction` legacy branch and `_rollout_record_metadata` collision call only), locale files only if a new `service_error.*` key is needed, `README.md` invariants, and the tests listed under Invariants changed plus the new witnesses.
- Exclude/protect: `web/static/note_reader.js`, `web/static/ontology_edit.js`, `web/notes/views.py::_relationship_fields` and `relationship_editor_config` (owned by `shared-editor-script`). `Worker.open_store` and `run_once` (owned by `worker-connection-reuse`). Restructuring the correction-kind dispatch beyond removing the three branches (owned by `job-kind-registry`). Entity corrections (`note.relink`, `note.entity.*`) beyond sharing the edge check. The Ontology page's preview/confirm flow.

### Invariants changed
- `tests/test_web_notes.py::test_note_reader_extraction_workflow` (`:498-504`). Today: an invalid reader correction is queued, fails in the worker, and the reader shows `data-job-state="failed"`. After: it is rejected at submit with 4xx and its locale message, and no job is queued.
- `tests/test_web_notes.py::test_note_reader_adds_and_deletes_relationships` (`:842-847`). Today: adding an identical relationship twice succeeds twice with one row. After: the second add is rejected as `conflict` (`service_error.relationship_exists`), as on the Ontology page.
- `tests/test_pipeline.py::test_note_correction_updates_only_current_note_edges[reverse]`, `::test_delete_note_relationship_removes_only_its_pending_edge` and `::test_add_note_relationship_accepts_required_fields_from_shipped_registry`. Today: they call the three removed pipeline methods and expect `ValueError` or `FacetSchemaError`. After: they cover the same outcomes through the reviewed path (`review_note_correction` + `apply_note_correction`) with `ServiceError` codes.
- `tests/test_pipeline.py::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus`. Today: the reviewed `WORKS_AT` edge keeps its `edge_id`. After: it is replaced by an edge with a new ID and the same `created_at`, so a stale form from either page fails.
- `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction` (`:399`). Today: it submits `note.relationship.delete` through `submit_correction`. After: it submits a still-submittable correction kind, because `note.relationship*` can no longer be submitted.
- `README.md:227-229` ("Add relationships with the current note's document ID...") and `:224-226`. Today: they guard with the removed pipeline methods' test. After: they cite the reviewed path and the new witnesses.

### Decisions required
- None. Both open choices were settled by the human on 2026-11-25, relayed through the starting session. (1) The note reader keeps direct apply: `/api/notes/relationship*` runs the same server-side review at submit and queues the reviewed payload, with `note_reader.js` untouched. (2) `note.relationship*` jobs are no longer submitted, but the worker still accepts already-queued ones, routed through the unified review.

## Proof

Candidate: `a8abf55 @ worktree claude/unified-note-corrections-0faa55` (witness commit on top of `e62635d`; production source unchanged from `e62635d`)

**Protected witness**
- Primary: a relationship correction from the note reader and the same correction from the Ontology page get one judgement. Path: `tests/test_web_notes.py` / `test_note_reader_and_ontology_page_judge_a_relationship_correction_alike` (11 rows: `unregistered-relation`, `forbidden-endpoints`, `same-node`, `missing-required-facet`, `duplicate-add`, `delete-other-notes-edge`, `note-changed`, `valid-edit`, `valid-pending-edit`, `valid-add`, `valid-delete`).
  - Defect and boundary: the reader queues raw requests that a second validator in the worker (`IngestionPipeline` `note.relationship*` methods) judges, while the Ontology page reviews at preview with `review_note_correction`. They disagree on error phase, status, message, duplicates, pending edges and delete. The defect crosses web submit, the job queue, the worker and the graph.
  - Assertion: each row builds two identical fixtures. One runs through `/api/notes/relationship*`, the other through `/api/ontology/corrections/preview` and confirm. For delete rows the Ontology side calls `review_note_correction(kind="relationship_delete", edge_id=..., changes={})` and submits that payload as `note.ontology.correction`, because the page has no delete form and its routes are out of scope. Each run gives phase (submit or worker), HTTP status, detail and the note's main, pending and peer edges without IDs. Invalid rows must be rejected at submit with the pinned locale key (`missing-required-facet` pins only 422), the graph must be untouched, and the reader's judgement must equal the Ontology one. Valid rows must produce the expected graph on both paths. Proves the claim at the public HTTP and graph boundary, including "rejected at submit, nothing queued". Limit: delete compares at the service and worker level, not the Ontology HTTP route. `valid-edit` and `valid-add` already pass and act as regression guards, not proof. Edge-ID replacement is covered by the stale-form guardrail.
- Guardrail: queued legacy jobs are judged by the same review, and new ones can't be submitted. Path: `tests/test_web_notes.py` / `test_queued_legacy_relationship_jobs_are_judged_by_the_same_review`.
  - Defect and boundary: the legacy executor upserts a duplicate add silently, and `ProcessingService.submit_correction` still accepts `note.relationship*`. Boundary: job store to worker to graph, and the submit API.
  - Assertion: three legacy jobs are inserted directly with `db.jobs.insert` (the pre-deploy queue). A duplicate `note.relationship.add` fails 409 with the graph unchanged. A `note.relationship` edit of a pending edge and a `note.relationship.delete` succeed with the expected graph. Then `submit_correction` raises `ServiceError("invalid")` for all three kinds. Limit: doesn't check the job error text, and doesn't prove legacy jobs keep correction priority.
- Guardrail: a reader form opened before an Ontology correction can't re-apply. Path: `tests/test_web_notes.py` / `test_note_reader_form_opened_before_an_ontology_correction_cannot_reapply`.
  - Defect and boundary: `apply_note_correction` keeps the edge ID through `update_edge`, so a stale reader form with the old `edge_id` applies on top. Boundary: the Ontology confirm, the worker and the graph, then the reader's submit.
  - Assertion: after an Ontology edit of `original` (to_id becomes c), a reader edit holding `edge_id="original"` is rejected at submit with 404 `service_error.relationship_missing`, and the graph stays as corrected. Limit: doesn't separately assert that `created_at` is kept.
- The `note-changed` row covers the stale-source part of the second guardrail at submit. The worker-time race is still covered by the existing `test_ontology_registry_editing_note_correction[stale-note]`.
- The third guardrail needs no new witness. Its tests are protected as-is: `tests/test_web_ontology.py::test_ontology_registry_editing_note_correction`, `::test_ontology_registry_editing_relationship_add_source` and `tests/test_pipeline.py::test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors`. All 9 cases pass on `a8abf55`. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/guardrail-existing-green.log`.
- Protected paths: the three new tests in `tests/test_web_notes.py` and their helpers (`_FIXTURE_SOURCE`, `_correction_workspace`, `_note_graph`, `_Judgement`, `_run_job`, `_judged`, `_reader_judgement`, `_ontology_judgement`, `_edit`, `_add`, `_delete`, and the row constants). Also the three existing guardrail tests named above. Build may still edit the invariant-changed tests the Frame lists elsewhere in `tests/test_web_notes.py`.
- Protected revision: `a8abf55` (compare with `git diff a8abf55 -- tests/test_web_notes.py tests/test_web_ontology.py tests/test_pipeline.py`).

**Red evidence**
- `uv run pytest tests/test_web_notes.py -k "judge_a_relationship_correction_alike or legacy_relationship_jobs or cannot_reapply" -v` gives 11 failed and 2 passed (`valid-edit`, `valid-add`). Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/red.log`. The failures, all from missing behavior:
  - `unregistered-relation`, `forbidden-endpoints`, `same-node`, `missing-required-facet`, `note-changed`: the Ontology side matches the expected key, but the reader decides in the worker (`phase 'worker' != 'submit'`) with a different detail.
  - `duplicate-add`: the reader succeeds (200) where the Ontology page returns 409 `relationship_exists`.
  - `delete-other-notes-edge`, `valid-delete`: the review has no delete kind. It returns 422 "Choose a person or relationship correction."
  - `valid-pending-edit`: the Ontology review can't see pending edges (404).
  - Legacy test: `assert 200 == 409`, because the duplicate legacy add is upserted silently.
  - Stale form: `('worker', 200) != ('submit', 404)`, because the old edge ID re-applied and the graph became a BUY d.
- The legacy test's submit refusal, observed before the asserts were reordered (pytest reported `DID NOT RAISE ServiceError`), is reproduced standalone: `submit_correction` accepts and queues all three `note.relationship*` kinds. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/red-submit-legacy-kind.log`.
- The rest of `tests/test_web_notes.py` is unaffected: 32 passed, and only the 11 new witnesses fail. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/web-notes-full.log`. `ruff check` is clean.
- The primary claim and the first two guardrails have no proof until the command above is observed RED, and it was observed RED on `a8abf55`.

**Supporting test plan**
- Shared identity rule (Frame witness 2) goes to Build, in `tests/test_registry_governance.py` or `tests/test_web_ontology.py`. It catches drift between `RegistryService.review_record_edit` and the person branch of `review_note_correction` on keep-previous-name, alias dedup, the alias length limit and `conflict` on a label taken by another record. There's no Proof witness because today both functions already apply these rules the same way, and both raise `conflict`, though with different keys (`identifier_taken` vs `name_taken`) that the Frame doesn't require to match. Nothing can fail before the change, so this is a refactor guard Build owns. Also covers `_rollout_record_metadata` still marking a collision `ambiguous`.
- Shared edge check (`OntologyRegistry.check_edge`) goes to Build, in `tests/test_registry*.py`. It catches relink (`_canonical_note_edge`) and `_review_edge` disagreeing on registered relation, distinct existing endpoints, allowed endpoints and facets.
- Note-reader converter (`reverse` resolved against the current row) goes to Build, in `tests/test_web_notes.py` outside the protected tests. It catches a reader `reverse: true` edit producing a different `after` than the same explicit endpoints.
- Legacy priority goes to Build, in `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction`. It catches an already-queued `note.relationship*` job losing correction priority once it can't be submitted.

## Build

Candidate: `90e1230 @ worktree claude/unified-note-corrections-0faa55`

### Files changed

- `src/stock_ontology/db/storage.py`, `src/stock_ontology/db/__init__.py`: add `OntologyDB.check_edge(relation, from_id, to_id, facets)` and `EdgeRejected(reason)`, the one check for a corrected or added edge: mapped relation, two different existing endpoints, allowed endpoint types, registry facets. Satisfies the primary claim (one validator).
- `src/stock_ontology/services/corrections.py`: `_review_edge` calls `check_edge`, maps `EdgeRejected` to the existing `service_error.*` keys and `FacetSchemaError` to `ServiceError("invalid")`. `review_note_correction` also lists the note's pending edges (marked `pending`, skipped by the person `WORKS_AT` scan and the duplicate check), adds a `relationship_delete` kind, and applies the `relationship_add` anchor rule only when `record` is given. New `READER_RELATIONSHIP_KINDS` and `review_reader_correction` turn a note-reader request into a review request (resolving `reverse` against the current row) and refuse a different `expected_hash` as `conflict`. The person branch uses the shared identity helpers. Satisfies the primary claim and the stale-note guardrail.
- `src/stock_ontology/services/registry.py`: adds `identity_aliases`, `identity_labels` and `labels_taken`, and `review_record_edit` uses them. Satisfies the identity obligation.
- `src/stock_ontology/pipeline.py`: removes `add_note_relationship`, `delete_note_relationship`, `correct_note_relationship` and `_find_note_edge`. `_canonical_note_edge` (relink) calls `check_edge`. `apply_note_correction` deletes on an empty `after`, and replaces an edge whose relation or endpoints change, or a pending edge, with a new ID that keeps `created_at`. A facet-only edit still uses `update_edge`. Satisfies the primary claim and the stale-form guardrail.
- `src/stock_ontology/services/processing.py`: `note.relationship*` move from `CORRECTION_KINDS` to `RETIRED_CORRECTION_KINDS`, so `submit_correction` refuses them while `job_priority` keeps them at correction priority. Satisfies the legacy-job guardrail.
- `src/stock_ontology/worker.py`: `_run_correction` sends `note.relationship*` jobs to `_run_ontology_correction`, which reviews them with `review_reader_correction` inside the same `immediate` transaction and applies them through `apply_note_correction`. The three legacy `elif` branches are removed and no other dispatch changed. `_rollout_record_metadata` checks name and alias collisions with `labels_taken` (ticker check unchanged, a collision is still `ambiguous`). `open_store` and `run_once` are untouched.
- `src/stock_ontology/web/notes/routes.py`: new `_reviewed_correction` used by `/api/notes/relationship`, `/relationship/add` and `/relationship/delete`. It reviews at submit, maps `ServiceError` through `http_error` and `ValueError` to 422 (as the Ontology preview does), keeps `api.raw_note_not_found` for a missing file, and queues the reviewed payload as `note.ontology.correction`. Request models are unchanged.
- `README.md`: one constraint entry after "Add relationships with the current note's document ID...": one review, one apply method, one edge check, one identity rule, and a new edge ID on a relation or endpoint change, guarded by the three Proof witnesses and the two new unit tests.
- Invariant-changed tests, each to the rule the Frame states:
  - `tests/test_web_notes.py::test_note_reader_extraction_workflow`: no failed job after an invalid correction.
  - `::test_note_reader_adds_and_deletes_relationships`: second identical add gets 409.
  - `tests/test_pipeline.py::test_note_correction_updates_only_current_note_edges[reverse]`, `::test_delete_note_relationship_removes_only_its_pending_edge` and `::test_add_note_relationship_accepts_required_fields_from_shipped_registry`: go through a new `_reader_correction` helper with `ServiceError` codes.
  - `::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus`: new ID, same `created_at`.
  - `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction`: submits `note.entity.delete`.
- New unit tests:
  - `tests/test_db.py::test_check_edge_is_the_one_edge_check_for_corrections`
  - `tests/test_registry_governance.py::test_record_edits_person_corrections_and_rollout_share_one_identity_rule`
  - `tests/test_web_notes.py::test_note_reader_reverse_reviews_like_the_swapped_endpoints`
  - a legacy-priority assertion in `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction`
- Coordination (`shared-editor-script`): `web/static/note_reader.js`, `web/static/ontology_edit.js`, `web/notes/views.py::_relationship_fields` and `relationship_editor_config` are not changed. The reader JS already shows a non-2xx `detail`, so submit-time rejection needs no JS change. Coordination (`worker-connection-reuse`): `Worker.open_store` and `run_once` are not changed.

### Unit evidence

- Proof witnesses: `uv run pytest tests/test_web_notes.py -k "judge_a_relationship_correction_alike or legacy_relationship_jobs or cannot_reapply" -v`. RED on `a8abf55` is recorded in Proof.
- The new unit tests, run against the `a8abf55` source tree with this candidate's test files: `uv run pytest -q tests/test_db.py::test_check_edge_is_the_one_edge_check_for_corrections tests/test_registry_governance.py::test_record_edits_person_corrections_and_rollout_share_one_identity_rule tests/test_web_notes.py::test_note_reader_reverse_reviews_like_the_swapped_endpoints tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction`. RED: 4 failed on missing `EdgeRejected`, `identity_aliases`, `review_reader_correction` and `RETIRED_CORRECTION_KINDS`. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/unit-red.log`. They are GREEN on `90e1230` (in the gate below).

### Green evidence

- Decisive witness: `uv run pytest -q tests/test_web_notes.py -k "judge_a_relationship_correction_alike or legacy_relationship_jobs or cannot_reapply"`. 13 passed. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/witness-green.log`.
- Gate: `uv run pytest -q`. 569 passed (553 before, plus 13 witness cases and 3 new unit tests). Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/build-green.log`.
- `uv run ruff check .`: all checks passed.
- Protected witnesses: `git diff a8abf55 HEAD -- tests/test_web_ontology.py` is empty. In `tests/test_web_notes.py` the diff from `a8abf55` touches only the two invariant-changed tests and appends one new test. In `tests/test_pipeline.py` it touches only the four invariant-changed tests and adds a helper. `test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors` is unchanged.

### Intervention record

- None: no measured user-facing outcome. The note reader's visible change (errors shown at submit instead of after the job) needs no new UI.

### Deviations

- None blocking. A note for Audit on edge IDs: the Frame's supporting obligation says to replace an edited edge "instead of `update_edge`". Build replaces it only when its relation or an endpoint changes, or when it was pending, and keeps `update_edge` for a facet-only edit. The protected guardrail `tests/test_web_ontology.py::test_ontology_registry_editing_note_correction[person|relationship]` asserts that a facet-only `WORKS_AT` edit keeps `employment-0`, and the Frame requires it to stay green without edits. The stale-form witness changes an endpoint, so it still gets a new ID. A note-reader edit only changes relation or endpoints (a no-op edit is refused as `no_changes`), so every applied reader edit still rotates the ID, as before.
- Behavior note: a note-reader edit whose values equal the current edge used to succeed silently and now returns 422 `service_error.no_changes`, as on the Ontology page. No test covered the old behavior.

## Audit

Candidate: `90e1230 @ worktree claude/unified-note-corrections-0faa55` (checked out at `75af9a6`, which differs from `90e1230` only in `docs/proposals/unified-note-corrections.md`; working tree clean)

Independence: fresh-context. Before this audit the auditing context had seen only the ledger, `.codex/skills/proposal-audit/SKILL.md`, the repo `AGENTS.md`, and the candidate diff and tests read during the audit. It did not build or prove the candidate.

Primary-claim verdict: PROVED. Evidence: `uv run pytest -v tests/test_web_notes.py -k "judge_a_relationship_correction_alike or legacy_relationship_jobs or cannot_reapply"` gave 13 passed, including all 11 rows of `test_note_reader_and_ontology_page_judge_a_relationship_correction_alike` (log `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/audit/witness.log`). `git diff a8abf55 90e1230 -- tests/test_web_notes.py` touches only the two Frame-listed invariant tests and appends one new test. The protected witness and its helpers are byte-identical to Proof's revision `a8abf55`, where Proof recorded 11 RED. In the code, `/api/notes/relationship*` now calls `review_reader_correction`, which goes to `review_note_correction`, and queues `note.ontology.correction`. Both paths apply through `apply_note_correction`. Limit: the delete rows compare at the service and worker level, because the Ontology page has no delete route. `valid-edit` and `valid-add` were green before the change and act only as regression guards.

Guardrail verdicts:
- Already-queued `note.relationship*` jobs are judged by the same review, and new ones can't be submitted: PROVED. Evidence: `test_queued_legacy_relationship_jobs_are_judged_by_the_same_review` passed and is unchanged from `a8abf55`. It was RED in Proof. The worker sends these kinds to `_run_ontology_correction` through `review_reader_correction`, and `submit_correction` refuses them through `RETIRED_CORRECTION_KINDS`. Correction priority is kept, checked by the new assertion in `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction` (passed). Limit: the job error text isn't asserted. The priority check calls `job_priority` directly and doesn't claim a retired-kind job.
- A stale note or stale graph still fails with a conflict, and a reader form opened before a correction can't re-apply: PROVED. Evidence: the `note-changed` row and `test_note_reader_form_opened_before_an_ontology_correction_cannot_reapply` passed (RED in Proof, unchanged). `test_ontology_registry_editing_note_correction[stale-note]` passed, which covers the race at worker time. Limit: a facet-only Ontology edit keeps its edge ID (see the deviation under scope). A stale form for a facet-only edit is caught only by the fresh-review comparison, not by the ID changing. The note reader can't make a facet-only edit, so the reader's stale-form case is unaffected.
- The existing Ontology correction tests and the person-accuracy test stay green without edits: PROVED. Evidence: `git diff a8abf55 90e1230 -- tests/test_web_ontology.py` is empty. `test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors` is unchanged. All 9 cases passed (log `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/audit/guardrails-units.log`). Limit: none beyond what these tests cover.

Scope and duty verdict: scope HELD; duties HELD. Evidence: every Frame invariant change was made and matches its entry: `test_note_reader_extraction_workflow`, `test_note_reader_adds_and_deletes_relationships`, the three `test_pipeline.py` tests that called the removed methods, `test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus` (new ID, same `created_at`), `tests/test_worker.py:399`, and the README entry. No other existing test was edited. `note_reader.js`, `ontology_edit.js`, `web/notes/views.py`, `Worker.open_store` and `run_once` are untouched. Apart from removing the three legacy branches, the dispatch change is one added `or` condition. The supporting obligations are met: a `relationship_delete` kind; pending edges included and tagged; the anchor rule applies only when `record` is given; `FacetSchemaError` maps to `ServiceError("invalid")`; one converter is used by both the routes and the worker; the three pipeline methods are removed; one edge check is shared by `_review_edge` and `_canonical_note_edge`; and one identity rule is used by `review_record_edit`, the person review, and rollout, where a collision is still `ambiguous`. The constraint-capture duty is met. The new `README.md` entry has a **Why:** and a **Guarded by:**, and all 5 tests it names exist and pass. The recorded deviation, keeping `update_edge` for a facet-only edit, is justified: the protected `test_ontology_registry_editing_note_correction[relationship]` asserts that a facet-only edit keeps `employment-0`. Limit: the shared edge check landed as `OntologyDB.check_edge` in `src/stock_ontology/db/storage.py` and `db/__init__.py`, not in `registry.py` as Frame's Include list says. Build didn't record this as a deviation. I judged it HELD because Frame named `OntologyRegistry.check_edge` only "for example", the check needs node lookups that live on the DB, `registry.py` is untouched, and it adds no behavior beyond the framed obligation. A stricter reader could call this EXPANDED.

Test homes:
- `tests/test_web_notes.py`: two invariant-changed tests, plus `test_note_reader_reverse_reviews_like_the_swapped_endpoints`. This is the Frame's permanent owner for note-reader correction behavior.
- `tests/test_pipeline.py`: four invariant-changed tests and a `_reader_correction` helper. They stay with the pipeline apply behavior they already covered.
- `tests/test_db.py::test_check_edge_is_the_one_edge_check_for_corrections`: placed next to `OntologyDB`, which owns `check_edge`. Proof's plan said `tests/test_registry*.py`, but this follows where the code actually landed.
- `tests/test_registry_governance.py::test_record_edits_person_corrections_and_rollout_share_one_identity_rule`: one of the two owners Frame allowed.
- `tests/test_worker.py::test_corrections_are_claimed_ahead_of_earlier_extraction`: the owner Proof's plan named for legacy priority.

Full gates: PASS.
- `uv run pytest -q`: 569 passed (log `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/audit/full-gate.log`).
- `uv run ruff check .`: all checks passed (log `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/audit/ruff.log`).
- Decisive witnesses and guardrail tests: 13 plus 13 passed (logs above).
- Limit: offline suite only. No live LLM and no migration or deploy check.

Residual risks:
- `_review_edge` now checks the relation after merging facets. An Ontology preview with an unregistered relation and a non-dict `changes.facets` now raises `AttributeError`, which is a 500, where it used to return 422 `choose_relationship_type`. Reproduced with `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-unified-note-corrections-0faa55/23990f0d-aeb2-4ecd-b74d-f0968dcaed6a/scratchpad/audit/probe_facets.py`. Only a hand-crafted request can reach it, since the shipped JS sends a dict, and nothing is written.
- The identity-rule and edge-check unit tests mostly check structure. They inspect the AST to confirm the helpers are called, plus helper unit cases. No behavioral test covers rollout marking a name or alias collision `ambiguous`. The existing `test_browser_registry_edit_rollout_preserves_unmatched_graph[ambiguous]` covers multiple matches, not label collision. I checked the rollout refactor by reading it, and it is equivalent.
- A note-reader edit that changes nothing now returns 422 `service_error.no_changes` where it used to succeed silently. This is recorded in Build and untested.
- Jobs already queued as `note.relationship*` before deploy are only exercised in tests, through `db.jobs.insert`. Draining a real queue is part of the human-owned deploy.

Recommendation: ACCEPT
Packet: no fix is required. Optional follow-ups for the human: restore relation-first ordering in `_review_edge` (`src/stock_ontology/services/corrections.py`), or guard against non-dict `facets`, so the 500 goes back to a 422; and record the `db/storage.py` placement of `check_edge` as a Build deviation. Merge, deploy and draining the queue stay human-owned.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
