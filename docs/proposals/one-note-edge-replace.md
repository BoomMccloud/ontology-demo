---
proposal_id: "one-note-edge-replace"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: One way to replace a note edge

## Proposal

### Intent

Two code paths decide what replacing a note edge means. `apply_note_correction` (`pipeline.py`) deletes the old edge, mints `edge_<uuid>`, keeps `created_at` only when present, upserts, and records new entity endpoints. `_replace_note_edge`, used by entity relink, does the same with a `pedge` prefix for pending edges, always copies `created_at`, and checks the edge through `_canonical_note_edge`. They already differ in those details.

Benefit: a change to edge IDs, `created_at` or note-entity bookkeeping lands once, and a relink and a correction cannot treat the same edge differently.

### Tentative primary claim

A relationship correction and an entity relink replace a note edge through one helper and produce edges with the same ID and `created_at` rules.

### Why now

Priority: medium. Found in the 2026-11-26 /simplify pass. No known wrong result yet, but the two paths have started to drift.

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
