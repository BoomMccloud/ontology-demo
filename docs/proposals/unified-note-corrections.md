---
proposal_id: "unified-note-corrections"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: One review path for note corrections

## Proposal

### Intent

A note correction that changes or adds a relationship can arrive two ways today. The note reader posts `/api/notes/relationship`, `/relationship/add` and `/relationship/delete`, which become `note.relationship*` jobs applied through `IngestionPipeline` methods. The Ontology page posts `/api/ontology/corrections`, which is reviewed by `services/corrections.py` and becomes a `note.ontology.correction` job with its own worker executor. Each path has its own edge validator, and they already disagree: one checks `matched`, the other `resolve_relation`, and they raise different error types. Identity edits (rename, aliases, keep previous name) are also written three times, in `services/registry.py`, `services/corrections.py` and the worker's rollout metadata.

Benefit: one set of rules for what a valid correction is, so a fix or new rule lands once. It removes a second API, a second worker executor and a second test surface, and the two pages can no longer accept an edit the other would reject.

### Tentative primary claim

A relationship or identity correction made from the note reader and the same correction made from the Ontology page are checked by the same rules and produce the same result.

### Why now

Found in the 2026-11-24 simplify review of the worker and web split. The drift is already visible, and the longer both paths take new rules, the harder they are to merge.

### Known constraints

Corrections still go through the worker as jobs. The web app stays read-only.

### Non-goals

None stated.

### Open choices

- Whether the note reader keeps its direct apply (no review step) or moves to review-then-confirm like the Ontology page.
- Whether the `note.relationship*` job kinds are retired or kept as aliases while queued jobs drain.

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
