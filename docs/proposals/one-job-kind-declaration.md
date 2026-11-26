---
proposal_id: "one-job-kind-declaration"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Declare each job kind's executor with its priority

## Proposal

### Intent

`job-kind-registry` put each kind's priority and submitter in `JOB_KINDS` (`services/processing.py`), but the worker keeps a parallel string-keyed `_executors` map and raises at startup when the two disagree. `_run_correction` then switches on `job.kind` a second time for `note.relink`, `note.entity.add` and `note.entity.delete`. `request_processing` also checks `_declared(PROCESS_KIND, "process")`, a module constant against a table in the same module, so it can never fail.

Benefit: adding a job kind is one entry, checked when the code is written rather than when the worker starts, and the worker's dispatch is one lookup instead of two levels of kind switching.

### Tentative primary claim

Each job kind names its executor in one declaration, and the worker dispatches with a single lookup.

### Why now

Priority: medium. Found in the 2026-11-26 /simplify pass. Today's drift check works; this removes the second table rather than fixing a failure. Easier after `retire-reader-relationship-jobs`.

### Known constraints

Only the worker opens `ontology.db` for writing; `services` must not import the worker.

### Non-goals

None stated.

### Open choices

- Whether the executor is named in `JobKind` (resolved by the worker) or the worker's map becomes the only table and the submit sets derive from it.

## Frame

<!-- Replaced only by proposal-frame. Include verified reality; one primary claim;
guardrail claims; supporting obligations; allowed scope with the reuse it extends and
the cheaper alternative it rejected; routing; witness owner; invariants changed;
blocking decisions. -->

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
