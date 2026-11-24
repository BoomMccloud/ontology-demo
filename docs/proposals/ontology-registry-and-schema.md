---
proposal_id: "ontology-registry-and-schema"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Ontology Registry and Schema

## Proposal

### Intent

Implement the Registry and Schema sections of the Ontology page shown in `work/ontology-tab.html`. In Registry, users can search the Companies, Themes, and People tabs and open a record with a breadcrumb, details, name and aliases, and any relationships they can inspect or act on. Each edit action opens the fields in its own section. Company and theme edits follow the registry review, publish, and apply flow. Person corrections and relationship changes link to their supporting notes.

Schema is where users inspect shared node and relationship definitions, including required fields, allowed endpoints, and direction.

### Tentative primary claim

From the Ontology page, users can find and edit a company, theme, or person in Registry and inspect the shared rules for those records and their relationships in Schema.

### Why now

The requester is ready to move the mockup into the product. The design work clarified where edits belong, where shared definitions belong, and which information helps users complete a task.

### Known constraints

Start with the basic task on each screen and add an element only if it helps users find a record, understand it, or act on it. Use **Ontology → Registry → record** as the breadcrumb without a separate back link. Show provenance where it supports inspection or correction. Keep shared schema definitions in Schema.

### Non-goals

Implementing the Suggestions and Run history sections of the mockup in this phase.

### Open choices

Whether to deliver Registry and Schema together or sequence them as separate increments within this scope.

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
