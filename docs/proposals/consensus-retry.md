---
proposal_id: "consensus-retry"
state: ABANDONED
witness: builder
candidate: "unassigned"
---

# Proposal: Retry failed company consensus

## Proposal

### Intent

Fix the gap where a failed company consensus, from a provider outage or a summary over the registry's 1,000-character limit, is never retried because the note is already logged as done. Today that leaves the company's consensus stale or missing until someone runs `ingest --rebuild-consensus`.

### Tentative primary claim

After a company's consensus fails, the next ingest or watch run retries that company without re-extracting notes, and stops retrying once it succeeds.

### Why now

The gap was found in the 2026-11-23 status review, and the human chose to fix it first.

### Known constraints

None stated.

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
