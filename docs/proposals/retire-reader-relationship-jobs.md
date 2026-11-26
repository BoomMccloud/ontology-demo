---
proposal_id: "retire-reader-relationship-jobs"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Retire the legacy note-reader relationship jobs

## Proposal

### Intent

The note reader's three relationship routes (`web/notes/routes.py`, `_reviewed_correction`) still pass the retired job-kind names `note.relationship`, `note.relationship.add` and `note.relationship.delete` into `review_reader_correction` (`services/corrections.py`). That adapter maps them through `READER_RELATIONSHIP_KINDS` to the Ontology review kinds and rebuilds a `changes` dict. `NoteRelationshipRequest.reverse` is still accepted and re-reads the note's edges, though `note_reader.js` now swaps endpoints itself and never sends it. The worker keeps a `job.kind in READER_RELATIONSHIP_KINDS` branch in `_run_ontology_correction`, and `JOB_KINDS` still declares the three kinds so jobs queued before deploy can drain. `_reviewed_correction` also copies `_submitted`'s not-found mapping.

Benefit: one correction vocabulary from browser to worker. The adapter, the unused `reverse` field, the second edge read, the legacy worker branch and three job-kind entries go away, and adding a correction rule touches one review path.

### Tentative primary claim

The note reader submits relationship corrections in the same `{kind, edge_id, changes}` shape as the Ontology page, and no code path accepts or names a `note.relationship*` job kind.

### Why now

Priority: high. Found in the 2026-11-26 /simplify pass. The compatibility layer only exists until queued legacy jobs drain after deploy, and it doubles the job-kind list that `job-kind-registry` set out to make single.

### Known constraints

Deploy first, and confirm no `note.relationship*` job is queued or running on the server before the kinds are removed. A leftover one should fail with a clear message, not run. The web app stays read-only; corrections still go through the worker.

### Non-goals

None stated.

### Open choices

- Whether the reader posts to the existing `/api/notes/relationship*` URLs with the new shape, or reuses `/api/ontology/corrections/preview` and `/confirm`.
- Whether a leftover legacy job is failed by a one-time repair command or by the worker on claim.

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
