---
proposal_id: "unified-note-corrections"
state: ACCEPTED
witness: independent
candidate: "fcae484 @ worktree claude/pipeline-correction-api-47e1d2"
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

Candidate: `230f734 @ worktree claude/pipeline-correction-api-47e1d2` (includes the accepted `pipeline-correction-api` change, `2031c5e`, and this ledger's first-run witness `84f92b2`)

### Verified reality
- `uv run pytest -q` on `2031c5e` — proves the suite judging this change was green before it started (553 passed, re-run by the `pipeline-correction-api` audit); limit: none.
- `src/stock_ontology/pipeline.py` `IngestionPipeline._canonical_note_edge` — proves the note reader's relationship rules: endpoints differ, both nodes exist, `registry.canonicalize_edge` must be `matched` and `endpoints_ok`; it raises plain `ValueError` with its own messages and does not check editable facet keys or duplicates. Used by `add_note_relationship`, `correct_note_relationship` and the non-pending branch of `_replace_note_edge` (entity relink).
- `src/stock_ontology/services/corrections.py:71` `_review_edge` — proves the Ontology page's rules differ: `registry.resolve_relation` instead of `matched`, facet updates limited to `edge_facet_keys(relation) - {"basis"}`, `endpoints_ok` only, `check_facets` on the result, and a "note already records that relationship" duplicate check; it raises `ServiceError` with i18n keys. Limit: the exact set of inputs on which the two disagree is not enumerated here; the decisive witness pins the ones that matter.
- `tests/test_architecture.py:37` `ALLOWED` — proves `pipeline` may not import `services` and `services` may not import `pipeline`; both may import the `ontology` layer (`registry.py`, `models.py`). So one shared validator must live in `registry.py` (or `models.py`).
- `src/stock_ontology/registry.py:30` `FacetSchemaError(ValueError)` — proves the ontology layer already raises typed `ValueError` subclasses that both callers handle; limit: it carries no i18n key today.
- `src/stock_ontology/worker.py:359-369` — proves a job's `ServiceError` fails with its own code and a `ValueError` fails as `invalid`, and the note reader shows the job's error text (`web/static/note_reader.js:180`).
- `src/stock_ontology/services/registry.py:96-102` (`review_record_edit`) and `services/corrections.py:147-153` (`review_note_correction`, person) — prove the identity edit is written twice line for line: keep the previous name as an alias, `unique_labels` excluding the new name, `check_metadata`, alias length limit. `src/stock_ontology/worker.py:164-171` (`_rollout_record_metadata`) is a different operation: it replays a published registry record change onto an existing graph node and drops aliases the record removed.
- Human decisions recorded 2026-11-25 in this session, answering the Proposal's open choices: the note reader keeps its direct apply (no review step), and both APIs and both job executors stay; the job-kind alias question is therefore moot.
- `tests/test_web_notes.py:846-849` (`test_note_reader_adds_and_deletes_relationships`) — proves the note reader today accepts adding a relationship the note already records (the second identical add succeeds and leaves one edge), the opposite of the Ontology page's "already records" conflict. Found by the first Build attempt, which was otherwise green (561 passed, 1 failed on this test).
- Human decision recorded 2026-11-26 in this session: both surfaces reject a duplicate, showing "This note already records that relationship." on both.

### Final primary claim
- The same relationship add or change, submitted from the note reader (`add_note_relationship`, `correct_note_relationship`) and from the Ontology page (`review_note_correction` with `relationship_add` or `relationship`, then `apply_note_correction`), is accepted or rejected by the same rules with the same rejection message, and an accepted edit stores the same canonical relation, direction and facets.

### Routing
- Witness: `independent`
- Why: it changes which user corrections are accepted into stored graph data on two surfaces, across the services/pipeline boundary.
- Human-owned irreversible action: merging and deploying the branch.

### Decisive witness
- Layer: unit tests calling the pipeline methods and the services review on the same seeded graph, no HTTP.
- Permanent owner: `tests/test_relationships.py` (relationship rules), or `tests/test_pipeline.py` if the prover finds it a better home.
- Witness: a table of relationship edits applied through both paths on identical fixtures, covering at least: an unregistered relation, a relation whose endpoint types the registry forbids, a duplicate of a relationship the note already records, a facet key the registry does not list for that relation, a missing or identical endpoint, and one valid add and one valid change. For each row both paths accept or both reject; rejections carry the same message; accepted rows store equal `(from_id, to_id, relation, facets)`.

### Guardrail claims
- Existing note-reader and Ontology-page correction tests stay green, except the one listed under Invariants changed; any other test that asserts an old divergent rule is a Build deviation, not an edit.
- The Ontology page still shows its localized error for each rejection (the i18n `key` survives the shared validator).
- Entity relink on the note reader still rewrites only the selected note's edges, keeping pending edges pending.

### Supporting obligations
- Add one shared relationship validator in `src/stock_ontology/registry.py` (for example `OntologyRegistry.check_note_edge(...)`) that takes the relation, the two endpoint nodes (or `None`), the facet updates, the base facets and the note's existing `(from_id, to_id, relation)` triples (excluding the edge being changed), and returns the canonical edge values or raises one `ValueError` subclass carrying `code` (`invalid` or `conflict`), `key` and message.
- `services/corrections._review_edge` calls it and converts the error to `ServiceError` with the same code, message and key. `IngestionPipeline._canonical_note_edge` calls it and lets the error surface (the worker already maps `ValueError`).
- Extract one identity helper in `services/registry.py` for keep-previous-name, `unique_labels`, `check_metadata` and the alias length limit, used by `review_record_edit` and `review_note_correction`. Existing record-edit and person-correction tests own it.

### Allowed scope
- Reuse: `_review_edge`'s rules (the stricter, localized set) moved into `registry.py`; `pipeline-correction-api`'s `_correct_note` frame and `apply_note_correction` unchanged; existing correction tests as owners.
- Cheaper alternative: making the note reader call `_review_edge` from the worker before the pipeline method. Rejected: the pipeline would still apply its own `_canonical_note_edge` rules, so two rule sets would remain.
- Include: `src/stock_ontology/registry.py`, `src/stock_ontology/pipeline.py` (`_canonical_note_edge` and its callers), `src/stock_ontology/services/corrections.py`, `src/stock_ontology/services/registry.py`, locale strings for any new i18n key under `src/stock_ontology/locales/`, the witness tests, and the one assertion in `tests/test_web_notes.py` listed under Invariants changed.
- Exclude/protect: the note reader's direct-apply flow, both HTTP APIs, both job kinds and both worker executors (human decision); `src/stock_ontology/worker.py` including `_rollout_record_metadata` (different operation, and `job-kind-registry` and `worker-connection-reuse` own worker changes); `web/static/note_reader.js` and `ontology_edit.js`; relationship delete and entity add/delete; protected witnesses from `pipeline-correction-api`.

### Invariants changed
- `tests/test_web_notes.py:846-849` (`test_note_reader_adds_and_deletes_relationships`) — today: a second identical note-reader add succeeds and leaves one edge; after: the second add fails with "This note already records that relationship." and still leaves one edge. Authority: the Proposal's intent (one set of rules) and the human decision of 2026-11-26.

### Decisions required
- None. The Proposal's open choices were answered by the human on 2026-11-25, and the duplicate rule on 2026-11-26 (see Verified reality).

## Proof

Candidate: `f547b8d @ worktree claude/pipeline-correction-api-47e1d2`. Its `tests/` and `src/` are byte-identical to `84f92b2` (checked with `git diff --quiet 84f92b2 f547b8d -- tests/ src/`), and its `src/` is identical to `1151bef`.

The witness needed no amendment for the rerun Frame. The 2026-11-26 decision says both surfaces reject a duplicate with "This note already records that relationship." The `duplicate add` and `change into a duplicate` rows already require the reader's outcome to equal the Ontology page's outcome, which is `("rejected", "This note already records that relationship.")`. The `tests/test_web_notes.py:846-849` assertion is Frame's Invariants-changed item for Build to update. Proof did not touch it.

**Protected witness**
- The same relationship add or change from the note reader and from the Ontology page gets the same verdict, the same rejection message and the same stored edges. Duplicates are rejected on both surfaces with "This note already records that relationship." Witness: `tests/test_pipeline.py` / `test_note_reader_and_ontology_page_apply_the_same_relationship_rules` (parametrized over `_SAME_RULES_ROWS`).
  - Defect and boundary: `IngestionPipeline._canonical_note_edge` (plus the duplicate merge in `OntologyDB.upsert_edge`) and `services/corrections._review_edge` each run their own edge rules. They disagree on unregistered relations, forbidden endpoint types, duplicates, unlisted facet keys, and missing or identical endpoints. This crosses the pipeline/services boundary, through `add_note_relationship` / `correct_note_relationship` on one side and `review_note_correction` plus `apply_note_correction` on the other.
  - Assertion: each row runs on two identically seeded DBs, using the shipped registry, companies A to D, and note edges `focus` (A OWNS B) and `second` (A COMPETE C). The test asserts that both surfaces return the same outcome. A rejection is `("rejected", message)`, where the message is `str(ValueError)` for the reader and `ServiceError.message` for the Ontology page. An acceptance is `("accepted", sorted (from_id, to_id, relation, facets) of the note's edges)`. For any `ServiceError` it also asserts that a locale `key` is present.
    - Proves: the primary claim, including the duplicate decision, for these nine inputs.
    - Limit: it does not cover HTTP routes, worker job executors, relationship delete, entity relink or person/identity edits. It checks only the note's non-pending edges, not note-entity membership. It does not check that the code shares one validator, only that the outcomes are equal.
  - Rows, RED (seven):
    - `unregistered relation`, `registry forbids endpoint types`, `missing endpoint` and `identical endpoints`: both surfaces reject, but with different messages.
    - `duplicate add`, `unlisted facet key` and `change into a duplicate`: the reader accepts (it merges the duplicate or stores `bogus_key`), while the Ontology page rejects.
  - Rows, GREEN guards only, not RED evidence: `valid add through an inverse alias` (D SUBSIDIARY_OF A stored as A OWNS D) and `valid change` (focus to COMPETE).
- Guardrails:
  - Localized key: covered by the `exc.key` assertion inside this witness. It is green today and is a guard only.
  - Existing correction tests staying green, apart from the Invariants-changed assertion `tests/test_web_notes.py:846-849`, and entity relink keeping pending edges pending: owned by the existing tests (`test_note_correction_updates_only_current_note_edges`, `test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus`, `test_add_note_relationship_accepts_required_fields_from_shipped_registry`, `test_note_reader_adds_and_deletes_relationships` and the person-correction tests). No new RED is claimed for these.
- Protected paths: `tests/test_pipeline.py` (the `_SAME_RULES_ROWS` table and `test_note_reader_and_ontology_page_apply_the_same_relationship_rules`).
- Protected revision: `84f92b2`, unchanged through `f547b8d` (compare with `git diff 84f92b2 -- tests/test_pipeline.py`).

**Red evidence**
- `uv run pytest tests/test_pipeline.py -v -k test_note_reader_and_ontology_page_apply_the_same_relationship_rules` on `f547b8d` gave 7 failed, 2 passed. Every failure is the witness's own `AssertionError` on a verdict or message mismatch. Two of them come from duplicates: the reader accepts, while the Ontology page rejects with "This note already records that relationship." None is an import, setup or unrelated error. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/unified-red-f547b8d.log` (first run on `84f92b2`: `.../scratchpad/unified-red.log`, same result).
- The primary claim has no proof until this command is observed RED. It has now been observed RED on `f547b8d` for the seven rows listed.

**Supporting test plan**
- Shared relationship validator in `src/stock_ontology/registry.py`, carrying `code`, `key` and message. Build owner: `tests/test_pipeline.py` (this witness), plus existing Ontology-page correction tests for the `ServiceError` code and key conversion, and `tests/test_web_notes.py::test_note_reader_adds_and_deletes_relationships` for the reader's HTTP-visible duplicate rejection, updated only at lines 846-849 as Frame's Invariants changed allows. It catches a validator that drops the `conflict` code or the i18n key when `_review_edge` converts its error.
- Identity helper in `src/stock_ontology/services/registry.py` (keep-previous-name, `unique_labels`, `check_metadata`, alias length limit). Build owner: the existing record-edit tests and person-correction tests (`test_registry_person_identity_correction_survives_matching_extraction`, `test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors`). It catches drift between the person identity rules in `review_record_edit` and `review_note_correction`.

## Build

Candidate: `fcae484 @ worktree claude/pipeline-correction-api-47e1d2`

### Files changed

- `src/stock_ontology/registry.py` — adds `EdgeRuleError(ValueError)` (with `code`, `key` and `message`) and `OntologyRegistry.check_note_edge(relation, *, from_node, to_node, base_facets, facet_updates, existing)`, the one rule set: the relation must resolve, facet updates must be registry-listed keys other than `basis`, both endpoints must exist and differ, the endpoints must be allowed, `check_facets` must pass, and the result must not duplicate one of the note's other triples. It carries the Ontology page's messages and i18n keys. Satisfies the primary claim.
- `src/stock_ontology/services/corrections.py` — `_review_edge` keeps its `edit_text` input checks, calls `check_note_edge` and converts `EdgeRuleError` to `ServiceError` with the same code, message and key. The person correction uses `edit_identity`. Satisfies the primary claim and the localized-key guardrail.
- `src/stock_ontology/pipeline.py` — `_canonical_note_edge` calls `check_note_edge`. `add_note_relationship` passes the user's facets as updates and the note's triples. `correct_note_relationship` passes the note's triples without the edited edge. Entity relink passes no triples, so it still merges into an existing edge as before, and it still keeps pending edges pending. Adds `_note_triples`. Satisfies the primary claim and the relink guardrail.
- `src/stock_ontology/services/registry.py` — adds `edit_identity` (keep the previous name, `unique_labels`, `check_metadata`, the alias length limit), used by `review_record_edit` and the person correction. Satisfies the identity supporting obligation.
- `tests/test_web_notes.py:846-851` — the Invariants-changed item: the second identical note-reader add now expects a 4xx carrying "This note already records that relationship.", and still exactly one edge.
- `README.md` — one constraint entry: check every note relationship add or change with `OntologyRegistry.check_note_edge` and edit identity with `edit_identity`, guarded by the witness.

### Unit evidence

- Protected witness: `uv run pytest tests/test_pipeline.py -v -k test_note_reader_and_ontology_page_apply_the_same_relationship_rules` — RED on `f547b8d` (7 failed, 2 passed; recorded in Proof); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/unified-red-f547b8d.log`.
- No new unit tests. The identity helper's owners are the existing record-edit and person-correction tests named in Proof, and they pass unedited.

### Green evidence

- Decisive witness and gate: `uv run pytest -q` — 562 passed (all nine witness rows included); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/unified-build-green.log`.
- `git diff 84f92b2 --stat -- tests/` — only `tests/test_web_notes.py` (the Invariants-changed assertion); the protected `tests/test_pipeline.py` is unchanged.
- `uv run ruff check .` — all checks passed.

### Intervention record

- None: the user-visible change is one rejection message on the note reader, with nothing to measure.

### Deviations

- None. Notes for Audit:
  - The first Build attempt stopped on `tests/test_web_notes.py:846-849`. The human chose the duplicate rule on 2026-11-26, Frame was rerun to list that assertion under Invariants changed, and Proof was re-observed RED on `f547b8d` before this candidate.
  - A note-reader duplicate fails its job with error code `invalid`, not `conflict`, because `Worker._run` maps every `ValueError` to `invalid` and `worker.py` is excluded from scope. The message is the same on both surfaces.

## Audit

Candidate: `fcae484 @ worktree claude/pipeline-correction-api-47e1d2` (HEAD `72d686a` differs only in `docs/proposals/unified-note-corrections.md`; `git diff --quiet fcae484 72d686a -- src tests README.md` exits 0)

Independence: fresh-context. The auditing context had seen only the audit skill, the ledger, the repository and the commands listed here. It saw no Build transcript.

Primary-claim verdict: PROVED. Evidence: the protected witness `tests/test_pipeline.py::test_note_reader_and_ontology_page_apply_the_same_relationship_rules` (9 rows over `_SAME_RULES_ROWS`) is byte-identical to Proof's protected revision (`git diff --quiet 84f92b2 fcae484 -- tests/test_pipeline.py` exits 0). I re-observed it RED myself on a `git archive f547b8d` tree, run with `PYTHONPATH` pointed at that tree's `src` (confirmed by `stock_ontology.__file__`). Result: 7 failed, 2 passed. All seven failures are the witness's own `AssertionError` on a verdict or message mismatch (unregistered relation, forbidden endpoint types, duplicate add, unlisted facet key, missing endpoint, identical endpoints, change into a duplicate). Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/unified-audit-red-f547b8d.log`. On the candidate, `uv run pytest tests/test_pipeline.py -v -k test_note_reader_and_ontology_page_apply_the_same_relationship_rules` gives 9 passed. Log: `.../scratchpad/unified-audit-witness.log`. The diff confirms both callers now delegate to `OntologyRegistry.check_note_edge`: `IngestionPipeline._canonical_note_edge` calls it, and `services/corrections._review_edge` calls it and converts `EdgeRuleError` to `ServiceError` with the same code, message and key. Both build the duplicate set from `db.list_note_edges(doc_id)`, excluding the edited edge. Limit: the proof covers the nine witnessed inputs, at the pipeline and services layer only. It does not cover HTTP routes or worker executors, and it does not cover pending-edge-only notes. The two `valid` rows were never RED, so they are guards only.

Guardrail verdicts:
- Existing note-reader and Ontology-page correction tests stay green, except the listed Invariants-changed assertion: PROVED. Evidence: `git diff 84f92b2 fcae484 --stat -- tests/` touches only `tests/test_web_notes.py`, and only inside `test_note_reader_adds_and_deletes_relationships`, as Frame's Invariants changed allows. `uv run pytest -q` gives 562 passed. Limit: the guarantee is only as strong as those existing tests. No new RED was claimed.
- The Ontology page still shows its localized error for each rejection: PROVED. Evidence: the witness's `exc.key` assertion passes on every `ServiceError` row. `EdgeRuleError` carries the same keys `_review_edge` used before, and those keys exist in `src/stock_ontology/locales/*.json` (for example `service_error.relationship_exists` and `service_error.choose_two_endpoints`). Limit: this guard was green before the change. It checks that a key is present, not how it renders.
- Entity relink on the note reader still rewrites only the selected note's edges and keeps pending edges pending: PROVED. Evidence: the relink call site (`pipeline.py:953`) is unchanged and still passes `keep_pending=pending`, which skips `_canonical_note_edge`. The existing relink tests named in Proof pass in the full suite. Limit: the evidence is existing tests only. Relink now also runs `check_facets` on a non-pending edge's stored facets, which the old reader validator did not. No test covers legacy facets that fail that check.

Scope and duty verdict: scope HELD; duties HELD. Evidence: `git show --stat fcae484` changes only `README.md`, `src/stock_ontology/registry.py`, `src/stock_ontology/pipeline.py`, `src/stock_ontology/services/corrections.py`, `src/stock_ontology/services/registry.py` and `tests/test_web_notes.py`, all inside Allowed scope. `worker.py`, `note_reader.js`, `ontology_edit.js`, the HTTP APIs, the job kinds, delete, and entity add/delete are untouched. The supporting obligations are met:
- The shared validator is in `registry.py` and carries `code`, `key` and message.
- `_review_edge` converts its error to `ServiceError`, and `_canonical_note_edge` lets it surface.
- `edit_identity` in `services/registry.py` is used by both `review_record_edit` and the person correction, and its owner tests pass unedited.

The build follows the reuse Frame named, moving `_review_edge`'s rules into `registry.py`. It adds nothing beyond that. The one Invariants-changed item was made as listed. Constraint capture: `README.md` gained one entry with `**Why:**` and `**Guarded by:**`, and the named test exists at `tests/test_pipeline.py:2556`. Limit: scope was judged from the diff. I did not judge the new code's style.

Test homes: `tests/test_web_notes.py` (`test_note_reader_adds_and_deletes_relationships`, lines 846-852) is the existing permanent owner of the note reader's HTTP add and delete behavior. The amendment is the Frame-authorized duplicate-rejection assertion. Separately, the protected witness in `tests/test_pipeline.py` was authored by Proof and is unchanged.

Full gates: PASS. Results:
- `uv run pytest -q` gives 562 passed (log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/unified-audit-full.log`). This run includes `tests/test_architecture.py`.
- `uv run ruff check .` reports all checks passed (log: `.../scratchpad/unified-audit-ruff.log`).

Limit: offline suite only. No live LLM, no deployed server, no browser check of either page.

Residual risks:
- A duplicate rejected on the note reader fails its job with code `invalid`, while the Ontology page uses `conflict`, because `Worker._run` maps every `ValueError` to `invalid` and `worker.py` was out of scope. The message is the same on both surfaces, and the claim does not cover job codes. Build disclosed this.
- Entity relink now applies `check_facets` to existing non-pending edges. A stored edge whose facets no longer pass the current registry would now block a relink that used to succeed. No test covers this.
- Relink passes no existing triples, so it still merges into a duplicate instead of rejecting it. That preserves the old behavior, but it is outside the shared duplicate rule.
- Before this change, `add_note_relationship` silently overwrote a caller-supplied `basis` facet. Now it rejects any `basis` key as a non-editable field. That matches the Ontology page, but it is a reader behavior change that no test names.

Recommendation: ACCEPT
Packet: none required. Merging and deploying stay human-owned. If the reviewer wants the second residual risk covered, the smallest follow-up is a test in `tests/test_pipeline.py` that relinks an entity whose edge holds stale facets, decided by a human before any code change.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
