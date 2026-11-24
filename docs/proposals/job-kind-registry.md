---
proposal_id: "job-kind-registry"
state: PROPOSAL
witness: builder
candidate: "unassigned"
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
