---
proposal_id: "note-relationship-actions"
state: ACCEPTED
witness: independent
candidate: "8bef4e5e + workspace SHA-256 7371f15af6b5108e5b1c88e2cc21c5b52e822433a452dd3be086035bb6b10374 @ stock_ontology"
---

# Add and delete relationships in the note reader

## Proposal

### Intent

Allow users to add a relationship or delete an existing relationship directly in the note reader's table. Add uses the same inline From, Relationship, and To editor. Delete confirms the selected row.

### Tentative primary claim

A reader can add and delete ontology relationships for the current note from the table. Other ontology views reflect the changes.

### Why now

Editing a row already works inline. Add and Delete belong in the same table.

### Known constraints

Keep the current note workflow simple. The reader applies corrections to the selected note's graph records.

### Non-goals

None stated.

### Open choices

None stated.

## Frame

Candidate: `8bef4e5e + workspace SHA-256 7a906aa2df1ac45513f758236a0596b9e98aa759850b8106e9920c8ba3991d98 @ stock_ontology`. Digest is SHA-256 of `(git diff --binary HEAD -- src tests README.md docs/architecture && git hash-object src/stock_ontology/web/static/note_reader.js)`.

### Verified reality

- `.venv/bin/python -m pytest -q tests/test_web.py tests/test_pipeline.py tests/test_db.py tests/test_web_navigation.py tests/test_i18n.py` passed 174 tests. Log: `work/note-reader/relationship-actions-baseline.log`.
- `web/templates/partials/note_reader.html` and `web/static/note_reader.js` already share one inline relationship form. With no edges, the current view renders an empty message and the mapper returns no choices.
- `IngestionPipeline.correct_note_relationship` validates the source hash and note ownership, and refreshes affected consensus. `OntologyDB.upsert_edge` deduplicates canonical edges by endpoints, relation, and source document. The storage delete methods take edge IDs and rely on ingestion to check ownership first.

### Final primary claim

- The table on a processed note lets a user add a valid relationship or confirm deletion of a listed relationship. It updates the selected note's contribution to the shared graph, including when the table starts or ends empty.

### Routing

- Witness: independent. The existing web-to-ingestion boundary gains graph add and delete operations.
- Human-owned irreversible action: deployment and actions on real notes during this proposal run.

### Decisive witness

- Layer and owner: offline HTTP integration in `tests/test_web.py`, through CLI composition with temporary SQLite.
- Contract: `POST /api/notes/relationship/add` accepts `file`, `from_id`, `relation`, `to_id`, and optional `expected_hash`. `POST /api/notes/relationship/delete` accepts `file`, `edge_id`, and optional `expected_hash`. Success returns HTTP 200. Invalid endpoints, stale or unprocessed notes, and deletion outside the note return a 4xx.
- Verify Add in a processed empty table when nodes are available, graph visibility, retrying Add without a duplicate, deletion of the exact note edge, and preservation of a peer edge and source text. Command: `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_adds_and_deletes_relationships`.

### Guardrail claims

- Invalid, stale, and other-note actions leave persisted relationships intact. Add and Delete preserve peer-note evidence and source text.

### Supporting obligations

- Share existing registry, endpoint, and note provenance checks and affected-company consensus refresh. Honor the existing pending-edge storage path.
- Verify empty-table Add and row-level confirmation in Chromium using temporary data.

### Allowed scope

- Reuse the inline editor, web delegation, ingestion transaction, registry and storage APIs. Changes limited to the reader display cannot persist graph changes. No new tables or queues.
- Include: pipeline, web app and catalog, reader template, script and CSS, locales, focused tests in `tests/test_web.py` or `tests/test_pipeline.py`, and affected architecture documentation.
- Protect: read-only routes, existing inline corrections, note and relationship provenance, and live data.

### Invariants changed

- None.

### Decisions required

- None.

## Proof

Candidate: `8bef4e5e + workspace SHA-256 e1ea18289e2859ec7467fcfd90c61cad03b6eb0ef2e785e24c352bde96971681 @ stock_ontology`.

**Protected witness**

- `tests/test_web.py::test_note_reader_adds_and_deletes_relationships` exercises the real reader and ingestion routes with temporary SQLite. It checks Add from an empty table, ontology visibility, retries, deletion, stale and invalid inputs, and source and peer isolation. It does not execute the browser script or use live data.
- Protected path: `tests/test_web.py`, SHA-256 `39280b4734eaf6129095563b33cfdd16a500fbbfe88ec05dd40c2c7a46f65334`.

**Red evidence**

- `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_adds_and_deletes_relationships` failed because the existing HTTP 200 processed page has no relationship table when empty. Log: `work/note-reader/relationship-actions-red.log`.

**Supporting test plan**

- Exercise inline Add and the confirm/cancel flow for Delete in Chromium. Keep existing correction and endpoint tests green.

## Build

Candidate: `8bef4e5e + workspace SHA-256 7371f15af6b5108e5b1c88e2cc21c5b52e822433a452dd3be086035bb6b10374 @ stock_ontology`.

### Files changed

- `src/stock_ontology/pipeline.py` adds note-scoped Add and Delete and reuses the source, registry, ownership, and consensus rules from correction.
- `src/stock_ontology/web/app.py` delegates the actions through the existing ingestion writer. `web/catalog.py`, the reader partial, stylesheet and script, and the six locales add the table controls, reuse the edit form, and show the applied registry's required Add fields.
- `tests/test_pipeline.py` checks that removing a pending relationship preserves peer evidence. `tests/test_web.py` retains the protected witness.
- `README.md` and `docs/architecture/web.md` describe note ownership and the new endpoints.

### Unit evidence

- `.venv/bin/python -m pytest -q tests/test_pipeline.py -k test_delete_note_relationship_removes_only_its_pending_edge` failed on missing Delete before implementation. Log: `work/note-reader/relationship-actions-pending-red.log`.
- `.venv/bin/python -m pytest -q tests/test_pipeline.py -k 'delete_note_relationship or test_note_correction'` passed 3 tests. Log: `work/note-reader/relationship-actions-pending-green.log`.

- `.venv/bin/python -m pytest -q tests/test_pipeline.py -k 'add_note_relationship or delete_note_relationship'` passed both tests. The required-field case failed before repair and now checks missing, invalid and valid sentiment using the shipped registry. Logs: `work/note-reader/relationship-actions-revision-red.log` and `work/note-reader/relationship-actions-revision-unit.log`.

### Green evidence

- `.venv/bin/python -m pytest -q tests/test_web.py -k 'note_reader or test_note_page'` passed 4 tests, including the protected witness. Log: `work/note-reader/relationship-actions-revision-witness.log`.
- `.venv/bin/python -m pytest -q` passed 492 tests. Log: `work/note-reader/relationship-actions-revision-full.log`.
- `node /private/tmp/stock-ontology-add-delete-required.cjs` passed in Chromium using a temporary app wired to the shipped registry. Verified canceled and confirmed Delete, Add in the empty table, and saving both BUY and EXPOSED_TO with selected sentiment. Log: `work/note-reader/relationship-actions-revision-browser.log`.
- `git diff --check` and `node --check src/stock_ontology/web/static/note_reader.js` passed.

### Intervention record

- None. Verification used temporary data and offline LLM fixtures.

### Deviations

- None.

## Audit

Candidate: `8bef4e5e + workspace SHA-256 7371f15af6b5108e5b1c88e2cc21c5b52e822433a452dd3be086035bb6b10374 @ stock_ontology`

Independence: fresh-context. I reviewed the previous candidate and did not author the implementation, repair, or protected witness.

Primary-claim verdict: PROVED. The protected witness covers Add from an empty table, duplicate prevention, Delete, and visibility in the shared graph. Independent verification with the shipped registry confirmed that the reader renders the EXPOSED_TO sentiment field and the composed HTTP app saves a valid company-to-theme relationship. Chromium verified the inline field and save. Log: `work/note-reader/relationship-actions-audit-r1-required.log`.

Guardrail verdicts:

- PROVED. The protected witness checks invalid and stale input, peer evidence, and source preservation. The pending-edge test checks scoped deletion. The shipped-registry reproduction confirmed that missing or invalid sentiment creates no edge.

Scope and duty verdict: scope HELD, duties HELD. The repair collects required fields through the validated ingestion path. The candidate digest, protected witness checksum, and README ownership rule match the approved scope.

Test homes: `tests/test_web.py` covers the composed reader workflow. `tests/test_pipeline.py` covers pending deletion and shipped-registry required fields.

Full gates: PASS. Independent reruns passed all 492 tests, the protected witness and four focused pipeline tests. The diff and JavaScript syntax checks passed. Logs: `work/note-reader/relationship-actions-audit-r1-full.log`, `work/note-reader/relationship-actions-audit-r1-witness.log`, and `work/note-reader/relationship-actions-audit-r1-pipeline.log`.

Residual risks:

- Verification used the shipped registry, temporary data, and fake model calls.

Recommendation: ACCEPT

Packet: Record acceptance for the audited candidate. The subsequent row-label request is a presentation-only follow-up.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->

### R1 · 2026-11-24 · Required relationship fields

- Verdict: REVISE. Add offered EXPOSED_TO without a way to supply its required sentiment.
- Changed: the editor renders required fields from the registry for Add, the route passes the provided values to ingestion, and the registry validates them before the write. The shipped-registry pipeline test and Chromium run cover EXPOSED_TO.
- Re-audit: ACCEPT. The protected witness and the shipped-registry checks pass on candidate `7371f15af6b5108e5b1c88e2cc21c5b52e822433a452dd3be086035bb6b10374`.
