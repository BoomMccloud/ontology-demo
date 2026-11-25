---
proposal_id: "unified-note-corrections"
state: FRAMED
witness: independent
candidate: "aa33b7f @ worktree claude/pipeline-correction-api-47e1d2"
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

Candidate: `aa33b7f @ worktree claude/pipeline-correction-api-47e1d2` (includes the accepted `pipeline-correction-api` change, `2031c5e`)

### Verified reality
- `uv run pytest -q` on `2031c5e` — proves the suite judging this change was green before it started (553 passed, re-run by the `pipeline-correction-api` audit); limit: none.
- `src/stock_ontology/pipeline.py` `IngestionPipeline._canonical_note_edge` — proves the note reader's relationship rules: endpoints differ, both nodes exist, `registry.canonicalize_edge` must be `matched` and `endpoints_ok`; it raises plain `ValueError` with its own messages and does not check editable facet keys or duplicates. Used by `add_note_relationship`, `correct_note_relationship` and the non-pending branch of `_replace_note_edge` (entity relink).
- `src/stock_ontology/services/corrections.py:71` `_review_edge` — proves the Ontology page's rules differ: `registry.resolve_relation` instead of `matched`, facet updates limited to `edge_facet_keys(relation) - {"basis"}`, `endpoints_ok` only, `check_facets` on the result, and a "note already records that relationship" duplicate check; it raises `ServiceError` with i18n keys. Limit: the exact set of inputs on which the two disagree is not enumerated here; the decisive witness pins the ones that matter.
- `tests/test_architecture.py:37` `ALLOWED` — proves `pipeline` may not import `services` and `services` may not import `pipeline`; both may import the `ontology` layer (`registry.py`, `models.py`). So one shared validator must live in `registry.py` (or `models.py`).
- `src/stock_ontology/registry.py:30` `FacetSchemaError(ValueError)` — proves the ontology layer already raises typed `ValueError` subclasses that both callers handle; limit: it carries no i18n key today.
- `src/stock_ontology/worker.py:359-369` — proves a job's `ServiceError` fails with its own code and a `ValueError` fails as `invalid`, and the note reader shows the job's error text (`web/static/note_reader.js:180`).
- `src/stock_ontology/services/registry.py:96-102` (`review_record_edit`) and `services/corrections.py:147-153` (`review_note_correction`, person) — prove the identity edit is written twice line for line: keep the previous name as an alias, `unique_labels` excluding the new name, `check_metadata`, alias length limit. `src/stock_ontology/worker.py:164-171` (`_rollout_record_metadata`) is a different operation: it replays a published registry record change onto an existing graph node and drops aliases the record removed.
- Human decisions recorded 2026-11-25 in this session, answering the Proposal's open choices: the note reader keeps its direct apply (no review step), and both APIs and both job executors stay; the job-kind alias question is therefore moot.

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
- Existing note-reader and Ontology-page correction tests stay green, except a test that asserts the old divergent rule, which Build reports as a deviation rather than edits.
- The Ontology page still shows its localized error for each rejection (the i18n `key` survives the shared validator).
- Entity relink on the note reader still rewrites only the selected note's edges, keeping pending edges pending.

### Supporting obligations
- Add one shared relationship validator in `src/stock_ontology/registry.py` (for example `OntologyRegistry.check_note_edge(...)`) that takes the relation, the two endpoint nodes (or `None`), the facet updates, the base facets and the note's existing `(from_id, to_id, relation)` triples (excluding the edge being changed), and returns the canonical edge values or raises one `ValueError` subclass carrying `code` (`invalid` or `conflict`), `key` and message.
- `services/corrections._review_edge` calls it and converts the error to `ServiceError` with the same code, message and key. `IngestionPipeline._canonical_note_edge` calls it and lets the error surface (the worker already maps `ValueError`).
- Extract one identity helper in `services/registry.py` for keep-previous-name, `unique_labels`, `check_metadata` and the alias length limit, used by `review_record_edit` and `review_note_correction`. Existing record-edit and person-correction tests own it.

### Allowed scope
- Reuse: `_review_edge`'s rules (the stricter, localized set) moved into `registry.py`; `pipeline-correction-api`'s `_correct_note` frame and `apply_note_correction` unchanged; existing correction tests as owners.
- Cheaper alternative: making the note reader call `_review_edge` from the worker before the pipeline method. Rejected: the pipeline would still apply its own `_canonical_note_edge` rules, so two rule sets would remain.
- Include: `src/stock_ontology/registry.py`, `src/stock_ontology/pipeline.py` (`_canonical_note_edge` and its callers), `src/stock_ontology/services/corrections.py`, `src/stock_ontology/services/registry.py`, locale strings for any new i18n key under `src/stock_ontology/locales/`, and the witness tests.
- Exclude/protect: the note reader's direct-apply flow, both HTTP APIs, both job kinds and both worker executors (human decision); `src/stock_ontology/worker.py` including `_rollout_record_metadata` (different operation, and `job-kind-registry` and `worker-connection-reuse` own worker changes); `web/static/note_reader.js` and `ontology_edit.js`; relationship delete and entity add/delete; protected witnesses from `pipeline-correction-api`.

### Invariants changed
- None.

### Decisions required
- None. The Proposal's open choices were answered by the human on 2026-11-25 (see Verified reality).

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
