---
proposal_id: "note-entity-actions"
state: ACCEPTED
witness: independent
candidate: "8bef4e5e + workspace SHA-256 335b13d7e526e53521aa3415e2a33e038b07ece8b638e1629dbef2576328cc48 @ stock_ontology"
---

# Add and delete entities in the note reader

## Proposal

### Intent

Put Edit and Delete next to each entity in an extracted note. Retain inline matching for Edit. Add entity lets the user choose an existing ontology entity from the list. Delete confirms removal of the selected entity and its relationships in this note, preserving the canonical entity and peer notes.

### Tentative primary claim

The reader can add an existing entity to a note and edit or delete an entity directly from its row.

### Why now

The relationship table already offers these actions inline.

### Known constraints

Add selects an existing ontology entity. The note is the scope of Delete. Keep the original note text as reference.

### Non-goals

None stated.

### Open choices

None stated.

## Frame

Candidate: `8bef4e5 + workspace SHA-256 56454cd7fd21921cf32e9ea5e5c7d399f70f241127593028461ee8c25e9e9707 @ stock_ontology`. Digest is SHA-256 of `(git diff --binary HEAD -- src tests README.md docs/architecture && git hash-object src/stock_ontology/web/static/note_reader.js)`.

### Verified reality

- `.venv/bin/python -m pytest -q tests/test_web.py tests/test_pipeline.py tests/test_db.py tests/test_web_navigation.py tests/test_i18n.py` passed 177 tests. Log: `work/note-reader/entity-actions-baseline.log`.
- `web/catalog.py:_note_extraction` only builds the entity picker when membership is nonempty. The reader partial and JS already share one inline matching form.
- `pipeline.py:relink_note_entity` validates a current note and rewrites only note-owned relationships. `OntologyDB.add_note_entities` deduplicates membership by document and entity. The delete path must remove membership and this note's incident edges in a single transaction.

### Final primary claim

- On a processed note, the reader can select an existing entity to add and use Edit or confirmed Delete from each entity row. Deletion removes that membership and this note's relationships involving that entity, while the canonical entity and peer evidence remain available.

### Routing

- Witness: independent. These actions change persisted graph attribution and can delete this note's relationships.
- Human-owned irreversible action: deployment and operations against live notes.

### Decisive witness

- Offline integration through the composed library in `tests/test_web.py`. `POST /api/notes/entity/add` and `POST /api/notes/entity/delete` accept `file`, `entity_id`, and optional `expected_hash`. Success is HTTP 200. Unknown IDs, uncaptured entities on Delete, and stale or unprocessed notes return a 4xx.
- Verify Add on a processed note without entities, idempotent addition, row labels and canonical links, removal of active and pending incident edges from the current note only, and preserved source text and independent edges. Command: `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_adds_and_deletes_entities`.

### Guardrail claims

- A failed action leaves graph data intact. Deleting a membership preserves the canonical node, other notes' memberships and relationships, unrelated edges in this note, and the source file.

### Supporting obligations

- Reuse current source verification, ingestion-owned writes, and consensus refresh. Exercise Add, Edit, and canceled and confirmed Delete against a temporary app in Chromium.

### Allowed scope

- Reuse the existing reader form, entity picker, note membership and relationship storage. A display-only change cannot update note attribution.
- Include `db/storage.py`, `pipeline.py`, the reader app, catalog, template, script, stylesheet, locales, focused web or pipeline tests, and affected architecture docs. No schema or queue changes.

### Invariants changed

- None.

### Decisions required

- None.

## Proof

Candidate: `8bef4e5e + workspace SHA-256 42c15881c1eb206402ec7b0f9b5f0e887e61128421e38e4fcabe752cede00a0c @ stock_ontology`.

**Protected witness**

- `tests/test_web.py::test_note_reader_adds_and_deletes_entities` exercises composed HTTP routes with temporary SQLite. It covers Add to an empty reader, idempotence, current-note incident edge cleanup in both edge stores, and canonical entity, peer, and source preservation.
- Protected path: `tests/test_web.py`. SHA-256: `bf955d2978a7d6589704a95282865442bded52e72e4607a24cb953c2ef3da9df`.

**Red evidence**

- `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_adds_and_deletes_entities` failed because the existing processed note returned HTTP 200 with no Add entity control. Log: `work/note-reader/entity-actions-red.log`.

**Supporting test plan**

- Verify Edit, Add from the existing list, and Cancel and Confirm Delete in Chromium. The witness covers public HTTP and storage, so it does not execute the client confirmation.

## Build

Candidate: `8bef4e5e + workspace SHA-256 335b13d7e526e53521aa3415e2a33e038b07ece8b638e1629dbef2576328cc48 @ stock_ontology`.

### Files changed

- `db/storage.py` and `pipeline.py` use the existing add and note-scoped incident-edge operations. Delete verifies membership, removes only this note's membership and its incident active and pending edges in one transaction, and refreshes affected consensus.
- `web/app.py` delegates Add and Delete through the ingestion writer. The reader model, template, script, stylesheet and locales share the inline picker for Add and Edit and use row-scoped Delete confirmation.
- `README.md` and `docs/architecture/web.md` record the note ownership rule and endpoints. The protected witness in `tests/test_web.py` is unchanged from Proof.

### Unit evidence

- The web witness exercises both edge stores and checks peer and unrelated evidence in real temporary SQLite.

### Green evidence

- `.venv/bin/python -m pytest -q tests/test_web.py -k 'note_reader or test_note_page'` passed 5 tests, including the protected witness. Log: `work/note-reader/entity-actions-witness-green.log`.
- `.venv/bin/python -m pytest -q` passed 493 tests. Log: `work/note-reader/entity-actions-full.log`.
- `node /private/tmp/stock-ontology-note-entity-actions.cjs` passed in Chromium. Verified inline Edit, choosing a previously unattached entity, excluded picker options, Cancel Delete, and confirming deletion of the note membership and related row. Log: `work/note-reader/entity-actions-browser.log`.
- JavaScript syntax and `git diff --check` passed.

### Intervention record

- None. Verification used temporary data and fake LLM fixtures.

### Deviations

- None.

## Audit

Candidate: `8bef4e5e + workspace SHA-256 335b13d7e526e53521aa3415e2a33e038b07ece8b638e1629dbef2576328cc48 @ stock_ontology`

Independence: fresh-context. I did not author the implementation or the protected witness.

Primary-claim verdict: PROVED. The unchanged protected witness passed through the composed HTTP app and temporary SQLite. It verifies adding an existing entity to an empty note, duplicate prevention, row actions, and deletion of the note’s membership and incident active and pending edges. I inspected the Chromium harness and passing log for inline Edit, the existing-entity picker, and canceled and confirmed deletion.

Guardrail verdicts:

- PROVED. The protected witness rejects invalid and stale operations and verifies preservation of the canonical entity, peer memberships, peer relationships, unrelated relationships in the selected note, and the original source. The writer performs membership and incident-edge removal in one transaction.

Scope and duty verdict: scope HELD, duties HELD. The implementation reuses note membership, edge storage, ingestion transactions, and the inline picker. The candidate digest and protected witness checksum match the ledger. The README records the deletion rule and names its test.

Test homes: `tests/test_web.py` owns the composed HTTP integration witness and asserts persisted graph behavior with temporary SQLite.

Full gates: PASS. Independent reruns passed 493 offline tests and the focused protected witness. `git diff --check` and the JavaScript syntax check passed. Logs: `work/note-reader/entity-actions-audit-full.log` and `work/note-reader/entity-actions-audit-witness.log`.

Residual risks:

- Verification used temporary databases and fake model calls. Chromium evidence covers the sample note workflow.

Recommendation: ACCEPT

Packet: Record acceptance for this exact candidate and return the verified workspace change.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
