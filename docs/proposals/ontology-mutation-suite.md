---
proposal_id: "ontology-mutation-suite"
state: ACCEPTED
witness: builder
candidate: "c2ff60b @ .claude/worktrees/ontology-mutation-suite"
---

# Proposal: Ontology Mutation Test Suite

## Proposal

Status: draft from `proposal-intake`, awaiting the requester's approval.

### Intent

An ontology test that goes through all the mutations and actions that can happen within the ontology graph, including bad cases, that can be run after every change to ensure the ontology is accurate.

### Tentative primary claim

After any change, one test run goes through every mutation and action that can happen within the ontology graph, including bad cases, and fails when the resulting ontology is not accurate.

### Why now

None stated.

### Known constraints

- It covers all the mutations and actions that can happen within the ontology graph.
- It includes bad cases.
- It can be run after every change.

### Non-goals

None stated.

### Open choices

- What "accurate" means for the ontology after a mutation: the expected rows exist, the graph's rules hold (no dangling references, no duplicates, valid facets), or both.
- Which actions count as "within the ontology graph": only writes to the ontology's nodes and edges, or also the claim graph (theses, memberships, catalysts) and registry adoption.
- Whether it replaces any existing tests or runs beside them.
- Where "after every change" runs: a local command, a pre-commit hook, CI on every push, or after a deploy.
- Whether it runs only on test data, or can also check a copy of the deployed `ontology.db`.
- Sequence: whether the good cases and the bad cases ship together or one after the other.

## Frame

Candidate: `dd58431 @ main (/Users/jasonbxu/Documents/GitHub/stock_ontology)`

### Verified reality
- `uv run pytest -q` at `f58072c` — proves the offline suite was green before this change: 585 passed; rerun at `dd58431` in Build. limit: an earlier run during the concurrent `node-typeahead` merge showed 2 failures in `tests/test_web_notes.py`; they did not reproduce on the settled tree.
- `src/stock_ontology/services/processing.py:48` `JOB_KINDS` (merged in `dd58431`, `job-kind-registry`) — proves the one table of job kinds that write `ontology.db`: corrections `note.relink`, `note.entity.add`, `note.entity.delete`, `note.ontology.correction`; retired but still runnable `note.relationship`, `note.relationship.add`, `note.relationship.delete`; operator `ingest`, `reembed`, `repair`, `registry.publish`, `registry.apply`, `registry.apply.preview`; and `process`. `Worker.__init__` (`src/stock_ontology/worker.py:267`) refuses to start when its executors disagree with the table. limit: does not show which kinds existing tests exercise end to end.
- `src/stock_ontology/db/storage.py` `OntologyDB` — proves the graph mutators those jobs call: `upsert_node`, `upsert_edge`, `insert_pending_edge`, `delete_pending_edges`, `update_edge`, `delete_edges`, `merge_node_into`, `delete_document_artifacts`, `add_note_entities`, `remove_note_entity`, `relink_note_entity`, `relink_document`, `upsert_consensus_view`, `replace_node_embeddings`, `migrate_facets`. limit: method names only, not their failure modes.
- `src/stock_ontology/db/schema.py` — proves edges, pending edges, `note_entities`, and `node_lookup` reference `nodes(id)` with `ON DELETE CASCADE`, and `ingestion_log.doc_id` is unique. limit: relies on SQLite foreign keys being enabled per connection; not verified here.
- `src/stock_ontology/repair.py:114` `_delete_orphan_artifacts` and `src/stock_ontology/audit.py:426` `run_ontology_audit` — prove existing read-side detectors for orphan doc artifacts and for edges unmapped or misdirected against the registry. limit: neither checks duplicates, node lookup consistency, or note membership.
- `src/stock_ontology/registry.py:743` `OntologyRegistry.check_note_edge` — proves one rule set already judges correction edges. limit: covers corrections only.
- `tests/web_support.py` (`seed_web_db`, `FakeWebLLM`) and `tests/fixtures/sample_data` — prove offline seed data and a fake LLM exist to drive jobs. limit: not checked to cover every job kind.
- `README.md` "Guarded by" entries (30) — prove mutation rules are already guarded, scattered across `test_db.py`, `test_repair.py`, `test_worker.py`, `test_official_facets.py`, `test_relationships.py`, `test_web_notes.py`, `test_registry_governance.py`. limit: no single test walks every job kind or asserts graph-wide invariants after each one.
- Repository root has no `.github/workflows` and no `.pre-commit-config.yaml` — proves "after every change" today means the local `uv run pytest`. limit: none.
- The claim graph (theses, memberships, catalysts) appears only in `docs/proposals/epics/theme-catalysts.md` (commit `a7f237f`), not in `src/` — proves it has no mutations to test yet. limit: none.

### Final primary claim
- One test module, run by the default `uv run pytest`, drives every job kind in `JOB_KINDS` through the worker on offline test data, including its refused cases, and fails when any job leaves the ontology inaccurate: either the job's expected rows are wrong, or a graph-wide invariant check fails.

### Routing
- Witness: `builder`
- Why: on test data the change adds tests and a test-only helper; it can break nothing outside the test suite.
- Human-owned irreversible action: None.

### Decisive witness
- Layer: worker-level integration test with fake LLM clients, temporary `ONTOLOGY_DATA_DIR` and `ontology.db`.
- Permanent owner: `tests/test_ontology_mutations.py`.
- Witness: for each job kind, a good case asserts the expected node, edge, pending edge, and membership rows and then passes the invariant check; a bad case asserts the job fails or is refused and the database digest (`tests/web_support.py` `db_digest`) is unchanged.

### Guardrail claims
- An inventory test fails when `JOB_KINDS` declares a kind the suite does not exercise, so new mutations cannot land uncovered.
- The invariant check itself fails on a deliberately corrupted database (dangling edge endpoint, membership to a missing node, duplicate canonical edge, required facet missing, orphan doc artifact), so a vacuous checker cannot pass.
- `src/` is unchanged and no test calls a live LLM provider.

### Supporting obligations
- A test-only `assert_ontology_invariants(db, registry)` helper: no dangling edge, pending edge, membership, or lookup rows; no duplicate `(from, canonical relation, to)` edges; every node and edge passes the registry facet schema; every edge relation maps through the registry; `run_ontology_audit` reports no unmapped or direction-issue edges; no orphan doc artifacts by the same rule as `_delete_orphan_artifacts`. Unit-test it against the corrupted fixtures above.
- Enable or assert `PRAGMA foreign_keys` on the test connection so cascades are part of what is checked.
- Bad cases per kind: unmapped relation held pending, missing required facet, over-length name, relink to a missing entity, delete of a missing membership, stale revision superseded, registry apply against a changed registry.

### Allowed scope
- Reuse: `tests/web_support.py` seed and `FakeWebLLM`, `tests/fixtures/sample_data`, `Worker` and `services.ProcessingService` for submission, `run_ontology_audit`, `OntologyRegistry` facet checks.
- Cheaper alternative: rely on the existing scattered tests. Rejected because nothing checks graph-wide invariants after each job or fails when a new job kind lands uncovered, which the claim needs.
- Include: `tests/test_ontology_mutations.py`; additions to `tests/web_support.py` only if a seed is missing for a job kind.
- Exclude/protect: all of `src/`; existing tests (the suite runs beside them, none replaced); the claim graph; CI or pre-commit setup; any deployed `ontology.db`.

### Invariants changed
- None.

### Decisions required
- None. Decision 1 resolved by the requester on 2026-11-26: test data only. The existing read-only `uv run stock-ontology audit` stays the production check, and the route stays `builder`.

Open choices settled at the cheapest option (no stored-data exposure): "accurate" means both expected rows and graph rules; only `ontology.db` writes count, since the claim graph is not built; runs beside existing tests; runs in the default `uv run pytest`; good and bad cases ship together.

## Proof

- Route `builder`: the decisive witness in `tests/test_ontology_mutations.py` is builder-owned and deferred to Build. No protected witness for this run.
- Requester direction (2026-11-26): the suite reads every content rule from `ontology_registry.json` (through `OntologyRegistry`) and every structure rule from the SQLite schema, and keeps no second copy of either. Moving domain rules into the registry is a separate later proposal.
- Requester decision (2026-11-26) on the Build deviation: a refused job is judged by `_stored_state` (every table except `jobs`, plus the registry file and the notes tree) in place of the `db_digest` the Frame named.

## Build

Candidate: `c2ff60b @ .claude/worktrees/ontology-mutation-suite`

### Files changed

- `tests/test_ontology_mutations.py` (new, the permanent owner). It satisfies the primary claim and both guardrails:
  - **Base workspace.** Copies the shipped `ontology_registry.json` and adopts it. It processes `note.md` and `peer.md` through `ProcessingService` and `Worker` with an offline `_FakeLLM` (extraction, consensus, embeddings). That gives companies, a person, a theme, an event, ABOUT, EXPOSED_TO, WORKS_AT and BUY edges, one unmapped `PARTNERS_WITH` held pending, and note memberships. Each test gets a copy of this base.
  - **Good cases.** 14, one per kind in `JOB_KINDS`, including the three retired `note.relationship*` kinds, queued straight into `jobs` the way pre-deploy jobs sit. Each runs through the worker and asserts the exact rows it adds and removes in nodes, edges, pending edges and memberships. Kinds that change no graph rows get an extra `check`: reembed vectors, registry published but not applied, applied revision after `registry.apply`, and the preview diff `NVIDIA linked` with the live graph untouched. Every good case then passes `assert_ontology_invariants`.
  - **Bad cases.** 14, one per kind: missing required facet, over-length name refused by ingest, relink to a missing entity, add of a missing entity, delete of a missing membership, note changed after review, unmapped relation, duplicate add, delete of a missing edge, embedding count mismatch, graph changed after repair review, published registry changed, registry changed after apply review, and preview of a non-browser publication. Each asserts the error code and a fragment of the reason, an unchanged stored state, and passing invariants.
  - **Inventory.** `test_every_declared_job_kind_has_a_good_and_a_bad_case` takes coverage from the same case tables that parametrize the run tests, and each run test asserts the job it ran had that case's kind. `test_inventory_fails_when_a_new_job_kind_lands_without_cases` monkeypatches a new kind into `JOB_KINDS` and checks that it is reported.
  - **`assert_ontology_invariants(db, registry)` and `ontology_problems`.** No second copy of any rule. Structure: asserts `PRAGMA foreign_keys` is on, then `PRAGMA foreign_key_check` and `PRAGMA integrity_check`. `node_lookup` is compared against `rebuild_node_lookup` on a `copy_to` scratch DB. Orphan doc artifacts are found by running `repair._delete_orphan_artifacts` on that copy. Content: `validate_rollout`, plus `run_ontology_audit` must report no unmapped or direction-issue edges. Duplicates: edges grouped by `canonicalize_edge` with the product's key of from, canonical relation, to and source doc. Promotable pending edges: any pending edge `canonicalize_edge` marks matched with allowed endpoints, the rule `_promote_pending_edges` uses.
  - **Helper unit tests.** Nine corrupted-DB cases each trip their named rule: dangling edge endpoint, membership to a missing node, duplicate canonical edge via the `SUPPLIES_TO` inverse alias, required facet missing, orphan doc artifact, stale node_lookup, unmapped relation, over-length name, promotable pending edge. Two more check that the clean base passes and that a connection with foreign keys off fails.
- `README.md` — one Web UI constraint entry under build rule 8: every job kind gets a good and a bad case in `tests/test_ontology_mutations.py`, and invariant rules are only called from the registry, SQLite or product code, never restated. Why: proposal `ontology-mutation-suite`, 2026-11-26. Guarded by the inventory test and the corrupted-database test.
- Nothing changed under `src/`, in `tests/web_support.py`, or in any existing test.

### Unit evidence

Logs under `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-I0pfca/0c1a0ca9-2218-4e67-a896-ec059c4f196b/scratchpad/build-logs/`.

- Builder-owned decisive witness: `uv run pytest tests/test_ontology_mutations.py -v` — RED with empty case tables: both inventory tests failed, listing every kind as uncovered; log: `red-helper-and-inventory.log`.
- `uv run pytest tests/test_ontology_mutations.py -v` — RED with `ontology_problems` stubbed to `[]`: all 9 corruption cases and the foreign-keys test failed, clean-base test passed; log: `red-helper-and-inventory.log`.
- `uv run pytest tests/test_ontology_mutations.py -v -k invariant` — GREEN, 11 passed; log: `green-helper.log`.
- Manual non-vacuity check, not logged: dropping one expected membership from `NEW_NOTE_ROWS` failed the `process` and `ingest` good cases; file restored.

### Green evidence

- Decisive witness: `uv run pytest tests/test_ontology_mutations.py -v` — pass, 41 tests; log: `green-witness.log`. Orchestrator rerun at `c2ff60b`: 41 passed.
- Gate: `uv run pytest -q` — pass, 629 tests; log: `gate.log`. Orchestrator rerun at `c2ff60b`: 629 passed.
- `uv run ruff check tests/test_ontology_mutations.py` — pass (not logged).

### Intervention record

- None. Test-only change with no user-facing outcome to measure.

### Deviations

- Frame's decisive witness says a bad case asserts `tests/web_support.py` `db_digest` is unchanged. That cannot hold for a job the worker runs and refuses, because the worker records the failed job in the `jobs` table inside the same `ontology.db`, so the file's bytes and mtime always change. Bad cases compare `_stored_state` instead: every table except `jobs` (vec0 shadow tables included), plus the registry file bytes and the notes tree (`web_support.note_tree`). Audit should accept this or name another check.
- No src bug found. Every good and bad case passed the invariant check against the shipped registry.

## Audit

Candidate: `c2ff60b @ .claude/worktrees/ontology-mutation-suite` (HEAD `c2ff60b1b482bb01a07240c15da8b4bfa486893a`, branch `proposal/ontology-mutation-suite`, clean worktree, diff from base `dd58431` is `README.md` +3 and `tests/test_ontology_mutations.py` +1058)

Independence: fresh-context. Before the audit, this context had seen only the audit prompt, the ledger, the repository instructions and the candidate. It had not seen the build or the builder's session.

Primary-claim verdict: PROVED. Evidence: `tests/test_ontology_mutations.py` has 14 good cases and 14 bad cases, one of each per kind in `JOB_KINDS`. The three retired `note.relationship*` kinds are queued straight into `jobs`. Every case runs through `Worker.run_once` with `_FakeLLM`, and each run test asserts `status["kind"] == case.kind`. Good cases assert exact added and removed node, edge, pending and membership rows, then `assert_ontology_invariants`. Bad cases assert the error code, the reason fragment, an unchanged `_stored_state` and the invariants. `uv run pytest tests/test_ontology_mutations.py -q`: 41 passed. RED checked in a scratch `git archive` copy of the candidate (`scratchpad/audit-copy`): with `relink_note_entity` changed to skip its remove, `[note.relink-to-existing-entity]` failed (1 failed, 40 passed). Limit: `_graph` leaves consensus views and synthesized edges out of the expected-row diff, so only the invariant check covers them. Each kind has one bad case, not every failure mode.

Guardrail verdicts:
- An inventory test fails when a kind in `JOB_KINDS` has no case: PROVED. Evidence: `test_every_declared_job_kind_has_a_good_and_a_bad_case` reads coverage from the same `GOOD_CASES` and `BAD_CASES` lists that parametrize the run tests. `test_inventory_fails_when_a_new_job_kind_lands_without_cases` monkeypatches in a new kind. In the scratch copy, removing the reembed good case failed both inventory tests (2 failed, 38 passed). The builder's RED log `build-logs/red-helper-and-inventory.log` agrees. Limit: coverage counts one case per kind, not depth.
- The invariant check fails on a deliberately corrupted database: PROVED. Evidence: 9 corruption cases each trip their named rule (dangling endpoint, missing membership node, duplicate canonical edge via `SUPPLIES_TO`, missing facet, orphan artifact, stale lookup, unmapped relation, over-length name, promotable pending), and a connection with foreign keys off also fails. In the scratch copy, stubbing `ontology_problems` to `[]` failed all 9 corruption tests, the foreign-keys test and the repair good case (11 failed). Limit: rules come from product code, including the private `repair._delete_orphan_artifacts`, so a wrong product rule would be judged by itself.
- `src/` is unchanged and no test calls a live LLM provider: PROVED. Evidence: `git diff --stat dd58431 HEAD` shows no `src/` paths. The `Worker` requires `llm_factory` (`src/stock_ontology/worker.py:242`), and every LLM path in it (lines 316, 610, 658) goes through that factory, which the suite sets to `_FakeLLM`. Limit: static inspection only, network was not sandboxed.

Scope and duty verdict: scope HELD; duties HELD. Evidence: only the Frame's included test file changed, plus one `README.md` entry under build rule 8, with a `**Why:**` and `**Guarded by:**` naming two tests that exist and pass. `tests/web_support.py`, the existing tests, CI and the claim graph are untouched, which matches `Invariants changed: None`. Every Frame obligation is met: the invariant helper with its corrupted-fixture unit tests, `PRAGMA foreign_keys` asserted, and the listed bad cases (missing facet, over-length name, relink to a missing entity, delete of a missing membership, note changed after review, registry changed after apply review, and the unmapped relation held pending in the base workspace). The `_stored_state` comparison used instead of `db_digest` was accepted by the requester in Proof on 2026-11-26; it reuses `web_support.note_tree` and the named product APIs. Limit: whether the 1058-line module is the smallest form was judged against the Frame's alternatives, not line by line.

Test homes: `tests/test_ontology_mutations.py`, the permanent owner the Frame named, a new worker-level integration module beside the existing tests.

Full gates: PASS. `uv run pytest tests/test_ontology_mutations.py -q`: 41 passed. `uv run pytest -q`: 629 passed. `uv run ruff check tests/test_ontology_mutations.py`: all checks passed. Limit: the repository has no CI or pre-commit gate, so "after every change" means a local `uv run pytest`.

Residual risks:
- The invariant check borrows product code (`_delete_orphan_artifacts`, `rebuild_node_lookup`, `validate_rollout`, `run_ontology_audit`). A bug shared by the product and that code passes unseen.
- Consensus views and synthesized edges are only checked by the invariants, not as expected rows.
- The base workspace is module-scoped and copied for each test. A future case that writes to `base_root` itself would leak state into the other tests.
- The suite covers test data only. Production still relies on `uv run stock-ontology audit`, as the requester decided.

Recommendation: ACCEPT
Packet: no rework needed. Merging `proposal/ontology-mutation-suite` stays a human decision.

## Revisions
