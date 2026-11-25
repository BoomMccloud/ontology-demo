---
proposal_id: "shared-editor-script"
state: FRAMED
witness: builder
candidate: "aa1d9f7 @ worktree/shared-editor-script-8b7869"
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

Candidate: `aa1d9f7 @ worktree/shared-editor-script-8b7869` (clean tree)

### Verified reality
- `uv run pytest -q` on `aa1d9f7` — proves the suite judging this change was green before it started: 551 passed; limit: no test executes browser JavaScript.
- `src/stock_ontology/web/static/note_reader.js` `waitForJob` — proves the note reader polls `/api/jobs/{id}` every second with no limit and returns `{state: "failed"}` on a non-OK response; JSON POST and `detail` parsing are inline in the submit handler; list facets split on commas only; limit: says nothing about the server payload checks.
- `src/stock_ontology/web/static/ontology_edit.js` `awaitJob`, `post`, `jsonResponse`, `facetValue`, `initializeRelationship` — proves the Ontology page gives up after 300 polls and throws, splits list facets on commas and newlines, and builds from/relation/to choices client-side from a JSON config with endpoint-type compatibility and an anchor filter; limit: same.
- `src/stock_ontology/web/notes/views.py` `_relationship_fields`, `_note_extraction`, and `templates/partials/note_reader.html` lines 184-231 — prove the note reader renders every node and every relation as server-side `<option>`s (no compatibility filter) and per-relation `<template>`s holding only required facets, with translated labels and options; limit: none.
- `src/stock_ontology/web/ontology/views.py` `build_registry_edit_context` (`relationship_editor_config`), `_schema_fields`, `build_schema_context`, and `theme_stage_choices` — prove four call sites read `registry._facet_specs` / `registry._vocabulary`; the ontology config carries untranslated relation names and option values; limit: `services/registry.py:103` also reads `_vocabulary` but is not web code.
- `src/stock_ontology/registry.py` `_facet_specs`, `_vocabulary` — prove the private methods return `{facet: {kind, required}}` layered by entity subtype or relation, and the vocabulary group for a key; no public method returns specs with their options.
- `src/stock_ontology/web/notes/routes.py` `NoteRelationshipAddRequest.facets` and `services/corrections.py` `check_facets` — prove note relationship add accepts any facets and the server validates them against the registry; edit (`/api/notes/relationship`) accepts no facets.
- `rg` over `tests/` — proves no test references either script, `_relationship_fields`, or `relationship_editor_config`; HTML tests in `tests/test_web_notes.py` and `tests/test_web_ontology.py` own the rendered pages.

### Final primary claim
- The note reader and the Ontology page load one shared editor script and embed the same server-built relationship editor model, so a submitted relationship edit offers the same endpoint and relation choices, parses list facets on commas and newlines, waits until the job finishes (no time limit, per the human's 2026-11-25 decision), and reports the server's `detail` or job error the same way on both pages.

### Routing
- Witness: `builder`
- Why: the change is browser script and view-model code; correction APIs, URLs, payload validation (`check_facets`, `check_endpoints`), job execution, and storage are unchanged, so a defect breaks an editor form, which the server still validates, and is reverted by reverting the commit.
- Human-owned irreversible action: merging and deploying the branch.

### Decisive witness
- Layer: web view tests (FastAPI test client, rendered HTML).
- Permanent owner: `tests/test_web_notes.py` and `tests/test_web_ontology.py`.
- Witness: for one registry and graph, the note reader and the Ontology record page each embed `<script type="application/json" id="relationship-editor-model">` whose parsed JSON is equal, carries translated relation and field labels and option lists from the public registry method, and both pages load `/static/editor.js` before their page script; plus a static test that neither page script defines its own job poller or POST helper.

### Guardrail claims
- Existing note-reader and Ontology correction flows still submit the same API payload shapes to the same URLs (current `tests/test_web_notes.py` and `tests/test_web_ontology.py` action tests stay green unchanged).
- Web code reads registry field specs only through a public registry method; `rg "_facet_specs|_vocabulary" src/stock_ontology/web` finds nothing.
- The schema page and theme stage choices render the same fields and options as before (existing schema tests stay green).

### Supporting obligations
- Add `OntologyRegistry.field_specs(node_type, entity_type=None, relation=None)` returning each declared facet with kind, required, and vocabulary members; unit test in `tests/test_vocab.py` or the registry tests.
- One server function builds the editor model (nodes with id, label, endpoint type; relations with label, from/to types, symmetric flag, and non-`basis` fields with label, kind, required, translated options; placeholders). Both views call it; `_relationship_fields`, `NoteRelationshipField`, `required_relationship_fields`, and `relationship_editor_config` go away.
- `static/editor.js` exposes `postJson`, `waitForJob` (poll every second until succeeded, failed, superseded, or queued for retry; no limit), and a relationship editor that owns choice population, compatibility filtering, facet inputs, facet parsing, and one node-choice function that the later `node-typeahead` proposal will replace.
- `note_reader.js` and `ontology_edit.js` keep their page flows (inline row editor vs. review/confirm) and call the shared script.
- Manual browser check of both editors on a seeded data dir, reported in Build, since no test runs the JavaScript.

### Allowed scope
- Reuse: extends `registry._facet_specs`/`_vocabulary` behind a public method, the Ontology page's client-built editor (it already filters by compatibility), and the existing web view tests as owners.
- Cheaper alternative: share only `postJson` and `waitForJob` and leave both editors and both server models; rejected because the Proposal's intent and claim cover list-facet parsing and the duplicated editor model, which that leaves drifted.
- Include: `src/stock_ontology/registry.py` (public method only), `src/stock_ontology/web/static/editor.js` (new), `static/note_reader.js`, `static/ontology_edit.js`, `web/notes/views.py`, `web/ontology/views.py`, a small shared web module for the model if neither view is the natural home, `templates/partials/note_reader.html`, `templates/partials/ontology_registry.html`, `templates/partials/ontology_edit_forms.html`, `templates/ontology.html`, and the owning tests.
- Exclude/protect: `src/stock_ontology/worker.py`, `src/stock_ontology/pipeline.py`, correction API URLs and request models, `services/` (including `services/registry.py:103`), node typeahead, and any test assertion on existing action payloads.

### Invariants changed
- None. No README entry or test states either poller's limit, the note reader's comma-only list parsing, or the note reader's unfiltered endpoint lists. The note reader gains endpoint compatibility filtering and shows optional relation fields when adding; the Ontology page gains translated relation, field, and option labels and "name (type)" node labels. These follow from the Proposal's "behaves the same on both pages".

### Decisions required
- None. The open polling choice was decided by the human on 2026-11-25: wait until the job finishes, no time limit.

## Proof

Builder route: the decisive witness is deferred to Build. The builder authors the web view tests named in Frame and must show them failing on `aa1d9f7` before the change and passing after.

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
