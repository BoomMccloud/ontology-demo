---
proposal_id: "job-kind-registry"
state: BUILT
witness: independent
candidate: "cd571b7 @ worktree pipeline-correction-api-47e1d2, branch claude/job-kind-registry"
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

Candidate: `6a1161a @ worktree pipeline-correction-api-47e1d2, branch claude/job-kind-registry`, with the witness tests from `7c333f8` added (no `src/` changes)

Build must implement these exact names, which are taken from Frame's example: `stock_ontology.services.processing.JOB_KINDS`, a plain mutable `dict[str, JobKind]`, where each entry has the attributes `.priority` and `.submit`. `submit` is one of `"correction"`, `"operator"`, `"process"` or `"retired"`. Of the two intake behaviors Frame allows, the witness takes the first. An undeclared spooled kind gets a job row recorded `failed` with `error_code="invalid"`, and its error names the kind. It is not dropped before insert. The `Worker` construction check must read `JOB_KINDS` when `__init__` runs, so that changing the dict in place is seen. It may raise any exception whose message names the mismatched kind.

**Protected witness**
- Undeclared kind is refused at spool intake: `tests/test_worker.py` / `test_spooled_job_of_an_undeclared_kind_fails_invalid_at_intake_and_is_never_claimed`
  - Defect and boundary: `Worker.intake` inserts any spooled kind with priority 20, and it fails only after being claimed, as "Unknown job kind". The submission crosses from the services spool file into the worker's jobs table.
  - Assertion: a hand-written `enqueue` spool file with kind `note.unknown` is consumed by `intake`, and `db.jobs.claim` then returns `None`. `ProcessingService.get_status("job_unknown")` reports `state=failed`, `error_code=invalid`, and an error containing `note.unknown`. Proves an undeclared kind is refused with a clear `invalid` error and never runs. Limit: it does not prove anything about the `retry` op, and does not check the exact error wording beyond the kind name.
- The executor map and the kind table agree, checked at construction: `tests/test_worker.py` / `test_worker_construction_fails_when_executors_and_the_kind_table_disagree`
  - Defect and boundary: executors are spread across if-chains in `_run` and `_run_correction`, and no check ties them to the services-side kind declarations. This crosses the services/worker boundary.
  - Assertion: `Worker(...)` builds with the shipped table. It raises, naming the kind, when `note.undeclared.executor` is added to `JOB_KINDS` (a declared kind with no executor). It also raises, naming `reembed`, when `reembed` is deleted from `JOB_KINDS` (an executor with no declared kind). Proves a mismatch fails when the worker is constructed, not at run time. Limit: it does not prove dispatch is a single map lookup. That shape belongs to Audit's scope review.
- Each kind is declared once, with priority and submitter, and the existing guardrail errors are kept: `tests/test_worker.py` / `test_kind_table_declares_each_kind_once_with_its_priority_and_submitter`
  - Defect and boundary: priority and the right to submit are split across `CORRECTION_KINDS`, `RETIRED_CORRECTION_KINDS`, `OPERATOR_KINDS`, `PROCESS_KIND` and `job_priority`. These are read both by `ProcessingService` and by the worker's priority.
  - Assertion 1: `submit_correction` refuses `note.relationship.add` (a retired kind) and `note.unknown` with `("invalid", "Unknown correction: <kind>")`. `submit_operator("note.relink")` refuses with `("invalid", "Unknown operator job: note.relink")`. This is a guardrail and already passes today.
  - Assertion 2: `{kind: (priority, submit)}` from `JOB_KINDS` equals exactly the current 14 kinds:
    - the four correction kinds: priority 0, `correction`
    - the three `note.relationship*` kinds: priority 0, `retired`
    - the six operator kinds: priority 10, `operator`
    - `process`: priority 20, `process`
  - Assertion 3: `job_priority(kind)` equals each entry's priority.
  - Proves one table declares every kind with its current priority, retired kinds keep correction priority, and no kind names change. Limit: it does not cover the `"scan"` pseudo-kind priority, which Frame moves to a named constant.
- Protected paths: `tests/test_worker.py`, limited to the three tests above plus the `_DECLARED_KINDS` constant and the `_job_kinds` helper next to them. Frame's Invariants changed lets Build edit lines 411-413 of `test_corrections_are_claimed_ahead_of_earlier_extraction` and nothing else in this file.
- Protected revision: `7c333f8` (commit on `claude/job-kind-registry`, not pushed).

**Red evidence**
- `uv run pytest tests/test_worker.py -v -k "undeclared_kind or disagree or declares_each_kind"` gives 3 failed, 25 deselected. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/jobkind-red.log`.
  - Intake witness: `AssertionError: an undeclared kind must never be claimed, got note.unknown`. The job was claimed with `priority=20` and `state=running`.
  - Construction and table witnesses: `AssertionError: services.processing.JOB_KINDS must be the one table of job kinds`, because the table is missing.
  - Full `uv run pytest tests/test_worker.py -q` gives 3 failed, 25 passed, so no other test is affected. `ruff check` is clean.
- The construction check's raise is guarded by the missing-table assertion. Its raising behavior has no proof until Build adds `JOB_KINDS` and that test is re-observed failing when the table is changed, before it passes.

**Supporting test plan**
- The retired `note.relationship*` jobs already queued still run with their current outcome. Build: the existing owner `tests/test_web_notes.py` (the `queue_legacy` test near line 1224) must stay green. It catches a retired kind losing its executor.
- `test_corrections_are_claimed_ahead_of_earlier_extraction` must read the retired kinds from `JOB_KINDS` (entries with `submit == "retired"`) instead of `RETIRED_CORRECTION_KINDS`. Build: `tests/test_worker.py:411-413`. It catches the old sets surviving alongside the table.
- `request_processing` checks the table for `process`. Build: the existing `tests/test_worker.py` processing tests stay green. They catch `process` being dropped from the table.

## Build

Candidate: `cd571b7 @ worktree pipeline-correction-api-47e1d2, branch claude/job-kind-registry`

### Files changed

- `src/stock_ontology/services/processing.py` — replaces `CORRECTION_KINDS`, `RETIRED_CORRECTION_KINDS` and `OPERATOR_KINDS` with `JobKind(priority, submit)` and the one table `JOB_KINDS` (14 kinds, with names and priorities unchanged). `job_priority(kind)` reads the table. The scan pseudo-kind becomes `SCAN_PRIORITY = 20`. `submit_correction` and `submit_operator` check the table entry's `submit` and keep their messages. Satisfies the primary claim and the submission guardrail.
- `src/stock_ontology/worker.py` — `Worker.__init__` builds `self._executors` keyed by kind and raises `ValueError` naming any kind that the table and the map do not share. `_run` is one lookup, with an `Unknown job kind` fallback for a row an older worker queued. The inline `registry.apply.preview` executor moves to `_run_apply_preview`. `_run_ontology_correction` takes `(db, job)` like the other executors. The `_run_correction` chain keeps only the three entity kinds. `intake` records an undeclared spooled kind through `insert_refused` as failed with `invalid` and `Unknown job kind: <kind>`. The scan job uses `SCAN_PRIORITY`. Executor bodies, `open_store`, `run_once` and `_execute` are unchanged.
- `src/stock_ontology/db/jobs.py` — adds `JobStore.insert_refused(...)`, which inserts a job already in the `failed` state with an error code and message. No schema change. This is a scope expansion the human approved on 2026-11-26 (see Deviations).
- `tests/test_worker.py:411-414` — the Invariants-changed item: it reads the retired kinds from `JOB_KINDS` instead of `RETIRED_CORRECTION_KINDS`, with the same assertion.
- `README.md` — one constraint entry: add a job kind as one `JOB_KINDS` entry plus one `Worker._executors` executor, and retire a kind instead of deleting it. Guarded by the three witnesses.

### Unit evidence

- Protected witnesses: `uv run pytest tests/test_worker.py -v -k "undeclared_kind or disagree or declares_each_kind"` — RED on `7c333f8` (3 failed, recorded in Proof); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/jobkind-red.log`.
- Construction-check RED that Proof required once the table exists: with `JOB_KINDS` in place and the `__init__` check disabled in a scratch copy of `worker.py`, `uv run pytest tests/test_worker.py -q -k disagree` gives 1 failed. Restoring the check gives 1 passed. Log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/jobkind-construction-red.log`.

### Green evidence

- Decisive witnesses and gate: `uv run pytest -q` — 585 passed (582 before, plus the 3 witnesses); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-pipeline-correction-api-47e1d2/40d1e94b-3844-4421-b662-f9bf33856003/scratchpad/jobkind-green.log`.
- `git diff 7c333f8 --stat -- tests/` — only `tests/test_worker.py`, at the Invariants-changed lines. The three protected witnesses are unchanged.
- `uv run ruff check .` — all checks passed.

### Intervention record

- None: internal change with no user-facing outcome.

### Deviations

- Scope expansion, approved: `src/stock_ontology/db/jobs.py`. The protected intake witness needs an undeclared kind recorded as a failed job, but `JobStore.fail` only closes a claimed job, and the architecture test keeps SQL in the storage layer. The human approved adding one `JobStore` method for this on 2026-11-26, before the file was changed.
- Note for Audit: a refused job is a normal failed row, so `ProcessingService.retry` can reopen it. It then fails at claim with the same `Unknown job kind` error through the `_run` fallback.

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
