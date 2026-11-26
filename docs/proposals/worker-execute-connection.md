---
proposal_id: "worker-execute-connection"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Run job attempts on the worker's existing connection

## Proposal

### Intent

`worker-connection-reuse` gave the worker one long-lived queue connection, but each job attempt in `_execute` still opens a second writable `OntologyDB` through `open_store`: schema script, migration anti-join over all nodes, sqlite-vec load and applied-registry parse. `_pipeline` then parses the applied registry again through `RegistryService.get_applied(db)` although `db.registry` holds it. `_queue` builds its `OntologyDB` itself with its own one-retry `RegistryChangedError` loop, separate from `_execute`'s `REGISTRY_REOPENS`, and has a `finally` close branch that every current caller makes unreachable.

Benefit: less CPU and I/O per job on the production server, one place that decides how the worker opens the database and retries after a registry change, and a simpler connection lifecycle.

### Tentative primary claim

A job attempt does not open a new database connection or parse the applied registry more than once, and a registry change is still detected before the next write.

### Why now

Priority: medium. Found in the 2026-11-26 /simplify pass. The per-attempt open predates the review; the shared connection makes removing it cheap.

### Known constraints

Only the worker opens `ontology.db` for writing. A registry change must still raise `RegistryChangedError` and reopen. An executor that calls `db.use_registry` must not leak that registry into the next job.

### Non-goals

None stated.

### Open choices

None stated.

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
