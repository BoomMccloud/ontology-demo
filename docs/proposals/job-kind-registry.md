---
proposal_id: "job-kind-registry"
state: FRAMED
witness: independent
candidate: "e1304fb @ worktree pipeline-correction-api-47e1d2, branch claude/job-kind-registry"
---

# Proposal: One table of job kinds

## Proposal

### Intent

Job kinds are defined in three places that must stay in sync: the `CORRECTION_KINDS` and `OPERATOR_KINDS` sets that set priority in `services/processing.py`, the if-chain in `Worker._run` (which also inlines the whole `registry.apply.preview` executor), and a second elif-chain in `Worker._run_correction`. The notes router adds six near-identical endpoints and request models for the correction kinds.

Benefit: adding a job kind means one entry, not three edits across files. A missing entry fails at submission with a clear error instead of at run time as "Unknown job kind" or a wrong priority. The worker dispatch shrinks to one lookup.

### Tentative primary claim

Each job kind's priority and executor are declared once, and submitting an undeclared kind is refused.

### Why now

Found in the 2026-11-24 simplify review. More job kinds are likely as browser editing grows.

### Known constraints

Queued jobs already in a database keep running after the change.

### Non-goals

None stated.

### Open choices

- Whether the six note correction endpoints collapse into one `POST /api/notes/{action}` or stay as separate URLs.

## Frame

Candidate: `e1304fb @ worktree pipeline-correction-api-47e1d2, branch claude/job-kind-registry` (local main after the unified-note-corrections merge)

### Verified reality
- `uv run pytest -q` on `e1304fb` — proves the suite judging this change was green before it started (582 passed); limit: none.
- `src/stock_ontology/services/processing.py:35-52` — proves kinds and priority live in four sets and one function: `CORRECTION_KINDS` (`note.relink`, `note.entity.add`, `note.entity.delete`, `note.ontology.correction`), `RETIRED_CORRECTION_KINDS` (three `note.relationship*`, still run, no longer submitted), `OPERATOR_KINDS` (six), `PROCESS_KIND`, and `job_priority`, which also prices the pseudo-kind `"scan"` (`worker.py:380`). `submit_correction` and `submit_operator` (`:141-153`) already refuse kinds outside their set; `request_processing` submits `process`. Limit: a hand-written spool file can still carry any kind.
- `src/stock_ontology/worker.py:304-318` `Worker.intake` — proves the worker inserts every spooled kind with `job_priority(kind)` without checking it is declared; an unknown kind gets priority 20 and fails only when claimed, at `worker.py:460` ("Unknown job kind").
- `src/stock_ontology/worker.py:439-460` `Worker._run` — proves dispatch is an if-chain with a `note.` prefix test and the whole `registry.apply.preview` executor inlined; `:538-555` `_run_correction` has a second chain for `note.relink`, `note.entity.add`, `note.entity.delete`, with `note.ontology.correction` and `READER_RELATIONSHIP_KINDS` (`services/corrections.py:225`) sent to `_run_ontology_correction`.
- `tests/test_architecture.py:37` `ALLOWED` — proves `worker` may import `services` but `services` may not import `worker`, so the kind table (needed by services for submission) must live in `services` and the worker must key its executors by it.
- `src/stock_ontology/web/notes/routes.py:143-195` — proves six note-correction endpoints (`/api/notes/relink`, `/entity/add`, `/entity/delete`, `/relationship`, `/relationship/add`, `/relationship/delete`) plus `/process`; after `shared-editor-script` the browser posts `/api/notes/${action}` to these same URLs (shared notes, `shared-editor-script.md`). Limit: none.
- `tests/test_worker.py:411-413` — proves one test reads `RETIRED_CORRECTION_KINDS` directly.

### Final primary claim
- Each job kind is declared once, in one table that states its priority and who may submit it; the worker runs a kind by one lookup in an executor map keyed by that table, a declared kind without an executor (or an executor without a declared kind) fails when the worker is constructed, and an undeclared kind is refused at submission and at spool intake with a clear `invalid` error instead of failing later as "Unknown job kind".

### Routing
- Witness: `independent`
- Why: it rewires how every job is prioritized, admitted and dispatched across the services/worker boundary, the core lifecycle of every write.
- Human-owned irreversible action: merging and deploying; jobs already queued in a live database must keep running on the new worker.

### Decisive witness
- Layer: unit tests on `ProcessingService` and `Worker` with a temporary workspace, no HTTP.
- Permanent owner: `tests/test_worker.py`.
- Witness: (1) a spool submission with an undeclared kind is not run: after `intake` the job is recorded failed with code `invalid` naming the kind (or is refused before insert), and `claim` never returns it. (2) Constructing a `Worker` whose executor map and the kind table disagree raises. (3) For every declared kind, `job_priority` equals the table's priority, retired kinds keep correction priority, and a retired kind is refused by `submit_correction`.

### Guardrail claims
- Jobs already queued under any currently declared kind, retired `note.relationship*` included, still run with their current priority and outcome.
- Correction and operator submission keep their current error codes and messages for undeclared kinds.
- The existing worker, web and CLI tests stay green, except the one listed under Invariants changed.

### Supporting obligations
- Replace the four sets in `services/processing.py` with one table (for example `JOB_KINDS: dict[str, JobKind]`, `JobKind(priority, submit)` where `submit` is `correction`, `operator`, `process` or `retired`); keep `job_priority(kind)` reading it, with the scan priority as a named constant.
- `submit_correction`, `submit_operator` and `request_processing` check the table; `Worker.intake` refuses an undeclared kind clearly.
- In `worker.py`, one executor map keyed by kind replaces the `_run` if-chain and the `_run_correction` elif chain; move the inline `registry.apply.preview` executor into its own method; check the map against the table in `Worker.__init__`.

### Allowed scope
- Reuse: the existing sets' home `services/processing.py` becomes the table; existing executor methods unchanged in behavior; `tests/test_worker.py` as owner.
- Cheaper alternative: adding only an intake check for undeclared kinds. Rejected: the claim needs priority and executor declared once and a missing executor caught before run time.
- Include: `src/stock_ontology/services/processing.py`, `src/stock_ontology/services/__init__.py` (exports), `src/stock_ontology/services/corrections.py` only if `READER_RELATIONSHIP_KINDS` must read the table, `Worker.__init__`, `intake`, `_run`, `_run_correction` and the new preview method in `src/stock_ontology/worker.py`, witness tests, and the test listed under Invariants changed.
- Exclude/protect: the note-correction HTTP routes and request models. The Proposal's open choice (one `POST /api/notes/{action}` or separate URLs) is not material: the browser posts the same URLs and bodies either way, so the cheaper option, keeping the routes as they are, is taken. Also excluded: executor bodies, `open_store`, `run_once`, `_execute` error mapping, job kind names, and the database schema.

### Invariants changed
- `tests/test_worker.py:411-413` (`test_corrections_are_claimed_ahead_of_earlier_extraction`) — today: reads priority through `RETIRED_CORRECTION_KINDS`; after: reads the retired kinds from the kind table, same assertion that they share correction priority.

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
