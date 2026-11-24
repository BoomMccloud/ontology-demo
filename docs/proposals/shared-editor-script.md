---
proposal_id: "shared-editor-script"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: One browser script for job polling and the relationship editor

## Proposal

### Intent

`static/note_reader.js` and `static/ontology_edit.js` each implement job polling, JSON POST with error parsing, and a relationship editor. They have drifted: one poller stops after 300 tries and throws, the other polls forever and returns failed jobs; one splits list facets on commas only, the other on commas and newlines. On the server, the relationship editor model is also built twice (`_relationship_fields` in `web/notes/views.py` and `relationship_editor_config` in `web/ontology/views.py`), and the ontology side reaches into the registry's private `_facet_specs` and `_vocabulary`.

Benefit: a submitted job behaves the same on both pages, list facets are parsed the same way, and an editor fix lands once. A public registry method for field specs stops web code depending on registry internals.

### Tentative primary claim

Submitting an edit from the note reader or the Ontology page waits for, reports, and parses the result the same way on both pages.

### Why now

Found in the 2026-11-24 simplify review. The two copies are new and diverging.

### Known constraints

None stated.

### Non-goals

None stated.

### Open choices

- Which polling behavior is right: give up after a time limit, or wait until the job finishes.

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
