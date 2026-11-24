---
proposal_id: "worker-connection-reuse"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Fewer database opens in the worker and status polling

## Proposal

### Intent

Each `Worker.open_store()` builds a new writable `OntologyDB`. Every open loads sqlite-vec, runs the schema script and migration check, and parses and hashes the applied registry. An idle `run_once` opens three times, and each job adds a claim open, an execute open, a fail open on error, and the next claim open. Job status polling from the browser (once a second per waiting tab) also opens a read-only database per poll, and the worker only reads the spool once per tick, so with the default 60-second interval a submitted job can wait up to a minute while the tab polls about 60 times.

Benefit: lower CPU and I/O on the server while idle and while jobs run, and faster pickup of submitted jobs, so the Process button and corrections feel responsive instead of waiting for the next scan tick.

### Tentative primary claim

A job submitted from the browser starts within a few seconds, and an idle worker does not reopen the database several times per tick.

### Why now

Found in the 2026-11-24 simplify review. It matters more now that the worker runs as a long-lived service on the production server.

### Known constraints

Only the worker opens `ontology.db` for writing. A registry change must still be detected (today via `RegistryChangedError` on open).

### Non-goals

None stated.

### Open choices

- How quickly a submitted job should start (the spool check cadence) versus how often the notes folder is rescanned.

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
