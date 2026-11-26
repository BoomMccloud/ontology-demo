---
proposal_id: "unified-note-corrections"
state: PROVED
witness: independent
candidate: "f547b8d @ worktree claude/pipeline-correction-api-47e1d2"
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
