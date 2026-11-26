---
proposal_id: "one-identity-rule"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: One rule for what makes a record's identity taken

## Proposal

### Intent

Registry edits (`services/registry.py`, around line 133) treat a ticker as an identity label: `identity_labels(name, ticker, *aliases)`. The rollout check in `_rollout_record_metadata` (`worker.py`, around line 155) leaves the ticker out of the labels, then compares company tickers separately with `normalize_ticker`. `labels_taken` is a one-line wrapper that does not reconcile the two.

Benefit: a registry edit and its rollout agree on whether a name, alias or ticker collides with another record, so a change the editor accepted cannot become `ambiguous` at rollout, or the reverse.

### Tentative primary claim

A name, alias or ticker that collides with another record is judged the same way by the registry editor and by rollout.

### Why now

Priority: high. Found in the 2026-11-26 /simplify pass. The two rules can already disagree on the same record, and it touches stored graph identity.

### Known constraints

None stated.

### Non-goals

None stated.

### Open choices

- Whether a ticker that equals another record's alias counts as a collision.

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
