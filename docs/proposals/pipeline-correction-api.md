---
proposal_id: "pipeline-correction-api"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Corrections owned by the pipeline, not the worker

## Proposal

### Intent

The worker's `note.ontology.correction` executor (`worker.py`, `_run_ontology_correction`) writes graph rows itself with `upsert_node`, `update_edge`, `upsert_edge` and `add_note_entities`. The worker also calls private pipeline methods: `_current_note_doc`, `_evidence_changed` and `_refresh_consensus`. The six note-reader correction methods in `pipeline.py` each repeat the same frame: open a transaction, re-check the note revision, edit, re-check, collect affected companies, mark evidence changed, refresh consensus.

Benefit: the worker goes back to claiming and running jobs, and the evidence and consensus rules live in one place. A pipeline change can no longer silently break the worker through a private method, and the repeated transaction frame becomes one helper, so a new correction is a few lines.

### Tentative primary claim

Every correction job applies its graph change through a public pipeline method, and the worker contains no graph-editing logic of its own.

### Why now

Found in the 2026-11-24 simplify review. It pairs naturally with `unified-note-corrections` and is cheaper to do first.

### Known constraints

None stated.

### Non-goals

None stated.

### Open choices

- Sequence relative to `unified-note-corrections`: before it, after it, or as one change.

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
