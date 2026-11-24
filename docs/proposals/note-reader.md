---
proposal_id: "note-reader"
state: ACCEPTED
witness: independent
candidate: "8bef4e5e2195348face75cf78d2419c8e1f612dd + 1f7fd3066e78a3cc4069e43a81b31d82f2927f8482687e655b2a12babb547a27 @ stock_ontology"
---

# Note reader proposal

## Proposal

### Intent

Use the **Extraction first** design. Show the extraction section above the original note text. A green **Extracted** icon means the current file has a saved extraction. Show its entities and relationships and let the user correct them. To correct an entity match, the user selects an existing ontology entity or creates a new one. The ontology links the note and its affected extracted relationships to the chosen entity, so other views reflect the correction. A new or changed note shows a gray **Not processed** icon and a **Process** button. Show the current file as the source reference.

### Tentative primary claim

When a reader opens a note, they can review and correct the extraction for its current text or process the current file. A successful reprocess replaces the note's previous extraction in the ontology.

### Why now

The note reader should present ontology data through a dedicated template and keep the original text available for reference.

### Known constraints

- A note can contain arbitrary text and can be a `.md` or `.txt` file.
- The extraction section gets its data from the ontology.
- Changed text counts as **Not processed** and the earlier extraction is hidden in the reader. On successful processing, the previous note-owned extraction is deleted as part of saving its replacement.
- Corrections update the ontology graph. Reprocessing replaces the note-owned links and relationships from the current extraction. Canonical entities remain shared records.

### Non-goals

Extraction history or a separate **Source changed** state.

### Open choices

None stated.

## Frame

Candidate: `8bef4e5e2195348face75cf78d2419c8e1f612dd @ stock_ontology`

### Verified reality

- `.venv/bin/python -m pytest -q tests/test_web.py tests/test_pipeline.py tests/test_db.py tests/test_note_intake.py tests/test_architecture.py tests/test_web_navigation.py` passed 176 tests before changes. Log: `work/note-reader/baseline.log`.
- `web/catalog.py:_scan_raw_notes` compares source and logged hashes. `_note_detail` already builds the frozen reader model. It does not establish entity attribution. `pipeline.py:_write_extraction` resolves mentions to shared nodes and records edge provenance. An isolated entity mention is lost as note provenance today.
- `pipeline.py:_process_document` atomically replaces note artifacts and writes the log. `IngestionPipeline.run` scans the whole tree. `db/storage.py:delete_document_artifacts` keeps canonical entities. `upsert_node` and `upsert_edge` validate against the applied registry and maintain graph lookup and document-specific edge identity.

### Final primary claim

- In the Extraction first reader, a current note extraction exposes its entities and relationships for correction. A missing or outdated extraction shows Process. A successful Process replaces this note's old extraction, and a correction changes the ontology seen from other views by repointing only links sourced to this note. The current source stays below the extraction.

### Routing

- Witness: independent. The web request crosses into ingestion and affects persisted graph data.
- Human-owned irreversible action: deployment and processing or migration of live notes during this proposal run.

### Decisive witness

- Layer and owner: offline web integration in `tests/test_web.py`, with real temporary SQLite, a fake extractor, and the composition used by `serve`.
- Contract: private local reader JSON POSTs to `/api/notes/process` with `file`, `/api/notes/relink` with `file`, `entity_id` and either `replacement_id` or `new_entity` (`name`, `facets` including `entity_type`), and `/api/notes/relationship` with `file`, `edge_id`, `relation`, optional `reverse`. Success is HTTP 200. The reader exposes `data-note-status="extracted"` or `data-note-status="not-processed"` and shows Process in the second state.
- Verify current and changed status, isolation of the selected note, entities without edges, relink to existing and new entities, relationship correction, downstream graph visibility, and replacement that preserves other notes' evidence. Focused command: `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_extraction_workflow`.

### Guardrail claims

- Process and corrections leave the raw source untouched. Correction and replacement leave other notes' relationships intact.
- An invalid or stale edit leaves the extraction unchanged. Failed reprocessing leaves the last committed ontology data intact while the reader shows Not processed until the current source is processed.

### Supporting obligations

- Persist entity membership through the existing document transaction, including isolated entities and empty extractions, with support for canonical merges. Treat older notes without complete recorded attribution as Not processed in the reader and offer Process on demand.
- Apply corrections only to current, selected-note provenance. Validate node and edge edits using the existing registry. Rebuild affected-company consensus via the existing pipeline path. Handle overlapping ingest/edit by guarding writes against stale extraction state.
- Keep the web reader read-only. Inject two explicit ingestion-owned operations at CLI composition. Preserve safe note paths, raw anchors, existing note presentation contract, and all six UI locales.

### Allowed scope

- Reuse: catalog reader, `OntologyDB`, existing ingestion transactions and registry validation. An edge-only reader is cheaper and cannot show entities without edges or persist corrections. Use one current set of note memberships and existing rows for edges.
- Include: `src/stock_ontology/{cli,config,pipeline}.py`, `src/stock_ontology/db/{schema,storage}.py`, `src/stock_ontology/web/{app,catalog}.py`, the existing reader partial and stylesheet, a reader script, locales, `tests/{test_web,test_pipeline,test_db}.py`, and affected README/architecture documentation.
- Protect: `AGENTS.md` ingestion write ownership, architecture import boundaries, the frozen note reader model, catalog and raw source navigation, and live ontology data.

### Invariants changed

- `docs/architecture/web.md:3` currently describes pasted-note creation as the web app's sole write. The note reader may initiate processing and corrections through injected ingestion operations; the renderer and the rest of the web app still open query-only DB connections.
- `README.md:189` and `tests/test_web.py::test_note_page_templates_only_see_presentation_models` retain the frozen model requirement and existing source/navigation evidence.

### Decisions required

- None.

## Proof

Candidate: `8bef4e5e2195348face75cf78d2419c8e1f612dd @ stock_ontology` plus the protected witness.

**Protected witness**

- `tests/test_web.py::test_note_reader_extraction_workflow` exercises the real note page, ingestion and correction operations, and persisted graph in a temporary database with a fake LLM. It checks which note was processed, isolated entity membership, ownership of relinked edges and corrected relationships, downstream visibility, replacement, rejected stale and invalid edits, and unchanged source files. It does not exercise a live LLM or deployed data.
- Protected path: `tests/test_web.py`. SHA-256: `d7da1dc87f0555abaf48046a88ee7efd7cf4b544ea8161d2b823533212029272`.

**Red evidence**

- `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_extraction_workflow` failed at the intended assertion for a missing `data-note-status="not-processed"` on the existing HTTP 200 reader. Log: `work/note-reader/proof-red.log`.

**Supporting test plan**

- Keep focused storage coverage for canonical merges and ingestion coverage for note ownership and replacement.

## Build

Candidate: `8bef4e5e2195348face75cf78d2419c8e1f612dd + 1f7fd3066e78a3cc4069e43a81b31d82f2927f8482687e655b2a12babb547a27 @ stock_ontology`. The worktree digest is SHA-256 of `(git diff --binary HEAD -- README.md docs/architecture src tests && git hash-object src/stock_ontology/web/static/note_reader.js)`.

### Files changed

- `src/stock_ontology/pipeline.py`, `config.py`, and `db/{schema,storage}.py` record one current entity membership per document, reuse the extraction transaction for single-note processing, and validate and apply edits to source-attributed graph records. Canonical merges carry current membership to the surviving entity.
- `src/stock_ontology/cli.py` composes the ingestion writer, and `web/app.py` delegates the three note actions. Reader queries stay read-only.
- `src/stock_ontology/web/catalog.py`, `web/templates/partials/note_reader.html`, `web/static/{library.css,note_reader.js}`, and the six locale catalogs show extraction status, graph results and correction forms above the original text.
- `tests/test_db.py` and `tests/test_pipeline.py` cover membership under merge and cleanup, overlapping processing, source changes before commit, collapsed relinks, and stale relationship forms. The independent `tests/test_web.py` witness is unchanged from Proof.
- `README.md` and `docs/architecture/{web,pipeline,storage}.md` record the source-hash, provenance and write-ownership rules.

### Unit evidence

- `.venv/bin/python -m pytest -q tests/test_db.py -k note_entity_membership` passed. Against an isolated baseline `src` archive selected via `-o pythonpath`, the same witness failed on missing membership support. RED log: `work/note-reader/storage-red.log`.
- `.venv/bin/python -m pytest -q tests/test_pipeline.py -k test_selected_note` passed 2 tests. Before the final source check, the source-changed case failed on missing rollback. RED log: `work/note-reader/lifecycle-red.log`.

- `.venv/bin/python -m pytest -q tests/test_pipeline.py -k test_note_correction_updates_only_current_note_edges` failed for both audit cases before repair and passed both after. Logs: `work/note-reader/revision-red.log` and `work/note-reader/revision-green.log`.

### Green evidence

- `.venv/bin/python -m pytest -q tests/test_web.py -k note_reader_extraction_workflow` passed with the Proof SHA-256 unchanged. Log: `work/note-reader/witness-green.log`.
- `.venv/bin/python -m pytest -q` passed 488 tests. Log: `work/note-reader/full-revision.log`.
- `node /private/tmp/stock-ontology-note-reader-browser.cjs` passed on Chromium with a loopback temporary app and fake LLM. Verified Process, both status colors, selecting an existing entity, creating a new entity, editing a relationship, and the raw source line. Log: `work/note-reader/browser-revision.log`.
- `git diff --check` and `node --check src/stock_ontology/web/static/note_reader.js` passed.

### Intervention record

- None. Verification used temporary data and offline LLM fixtures.

### Deviations

- None.

## Audit

Candidate: `8bef4e5e2195348face75cf78d2419c8e1f612dd + 1f7fd3066e78a3cc4069e43a81b31d82f2927f8482687e655b2a12babb547a27 @ stock_ontology`

Independence: fresh-context. I reviewed the prior candidate and did not author the implementation, repair, or protected witness.

Primary-claim verdict: PROVED. The unchanged protected web witness covers processing, entity relinking, relationship correction, and visibility in the shared graph. The new relink regression verifies that matching an entity already in the note removes the resulting self-loop, repoints the remaining note edges, and preserves peer evidence. Tests used temporary SQLite and fake extraction.

Guardrail verdicts:

- Source text and peer relationships: PROVED. The protected witness checks source bytes and peer relationships after correction and replacement. The relink regression also checks peer relationships during a collapsed match.
- Invalid or stale edits and failed processing: PROVED. The protected witness checks invalid and wrong-note edits, changed source, and failed processing. The new regression checks that a stale Reverse submission is rejected and leaves the corrected edge intact.

Scope and duty verdict: scope HELD, duties HELD. The repair stays within ingestion and its existing test suite. The candidate digest and protected witness checksum both match the ledger. The provenance and write-ownership rules are documented.

Test homes: `tests/test_web.py` covers the composed reader workflow. `tests/test_db.py` covers note membership. `tests/test_pipeline.py` covers ingestion races and both audit regressions.

Full gates: PASS. Independent reruns passed 488 tests, the focused protected web witness, and both repair regressions. `git diff --check` and the JavaScript syntax check passed. Logs: `work/note-reader/audit-r1-full.log`, `work/note-reader/audit-r1-witness.log`, and `work/note-reader/audit-r1-corrections.log`.

Residual risks:

- The local verification used temporary data and fake model calls. Live ingestion and deployment remain separate.
- The relationship editor validates existing facets against the selected relation and cannot supply a newly required facet. Such a change is rejected without changing the graph.

Recommendation: ACCEPT

Packet: Record the accepted audit and return the verified workspace candidate to the user.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->

### R1 · 2026-11-24 · Collapsed entity matches and stale relationship edits

- Verdict: REVISE. Relinking failed if an edge's endpoints collapsed into one entity, and a stale relationship action could reverse a corrected edge again.
- Changed: `src/stock_ontology/pipeline.py` now removes relationships collapsed by a note entity relink and replaces changed edge IDs so stale forms are rejected. `tests/test_pipeline.py` reproduced both issues before the repair and passes after it.
- Re-audit: ACCEPT. Both original failures now have passing regressions on candidate `1f7fd3066e78a3cc4069e43a81b31d82f2927f8482687e655b2a12babb547a27`.
