---
proposal_id: "node-typeahead"
state: BUILT
witness: builder
candidate: "3fc4fb2 @ worktree/shared-editor-script-8b7869"
---

# Proposal: Typeahead instead of the whole graph in edit pages

## Proposal

### Intent

When note actions are on, the note reader loads every node (or every entity) and renders each one as a choice in the relationship and entity editors. The registry record edit page puts `db.list_all_nodes()` into its page JSON. Page size, query time and template work all grow with the graph on every view, even when the user never opens an editor.

Benefit: note and registry pages stay fast and small as the graph grows, and the editors search the whole graph instead of a preloaded list.

### Tentative primary claim

Choosing a node in the note reader or registry editors finds it by typing part of its name, and opening those pages does not load the whole graph.

### Why now

Found in the 2026-11-24 simplify review. The cost grows with every ingested note.

### Known constraints

The web app stays read-only.

### Non-goals

None stated.

### Open choices

- Whether a server-rendered fallback is needed for use without JavaScript.

## Frame

Candidate: `a6d6b58 @ worktree/shared-editor-script-8b7869` (branch claude/shared-editor-script-8b7869, which holds the unmerged, ACCEPTED `shared-editor-script` change this builds on)

### Verified reality
- `uv run pytest -q` on `29c4b47` (code-identical to `a6d6b58`, which changes only ledgers) — 554 passed, recorded by the `shared-editor-script` audit; proves the suites were green before this change; limit: no test runs browser JavaScript.
- `src/stock_ontology/web/notes/views.py` `_note_extraction` — with note actions on, calls `db.list_all_nodes()` (or `db.list_nodes(node_type="entity", limit=-1)`) on every extracted-note view, puts every entity into `NoteExtraction.choices` and every node into `relationship_editor_model`; limit: the catalog view in `build_catalog_context` (`list_nodes(node_type="entity", limit=1000)`) and `web/shared.py::build_rail_context` load up to 1000 entities for other purposes.
- `templates/partials/note_reader.html` lines 40 and 100-110 — the entity editor renders every entity as an `<option>`, plus `__new__` and edit-only options; `can_add_entity` compares `choices` with the note's entities; `can_add_relationship` needs more than one node.
- `src/stock_ontology/web/ontology/views.py` `build_registry_edit_context` — passes `db.list_all_nodes()` into `relationship_editor_model` for the record's page JSON.
- `src/stock_ontology/web/static/editor.js` `relationshipEditor.nodeChoices` — the one place a node is chosen; endpoint compatibility uses only node types (`matches`, `compatible`), the anchor, and `id` inequality.
- `src/stock_ontology/db/storage.py` `keyword_search` — substring match over name, aliases, summary, and facets with only a `node_type` filter and no subtype filter; `list_nodes`, `list_all_nodes`, `get_nodes`, `get_stats` (per-type node counts) exist; limit: no name-only search with entity-subtype filtering exists.
- `src/stock_ontology/web/app.py` — JSON routes such as `/api/jobs/{job_id}` sit on the app; every web DB handle is read-only.

### Final primary claim
- In the note reader's entity and relationship editors and the Ontology record's relationship editors, a node is chosen by typing part of its name or an alias and picking from matches the server returns, restricted to node types the relation (or entity editor) allows; rendering those pages no longer loads every node or every entity for the editors.

### Routing
- Witness: `builder`
- Why: adds one read-only JSON search route and changes browser editors and view models; no write path, job, payload shape, URL of an existing route, or stored data changes, and reverting the commit restores the old pages.
- Human-owned irreversible action: merging and deploying the branch (together with `shared-editor-script`, which it is stacked on).

### Decisive witness
- Layer: web view and route tests (FastAPI test client).
- Permanent owner: `tests/test_web_ontology.py` and `tests/test_web_notes.py`.
- Witness: (1) with `list_all_nodes` and unbounded `list_nodes` made to fail, the note reader (note actions on) and an Ontology record page still render their editors, and the embedded `#relationship-editor-model` holds only nodes the page already shows; (2) the node search route returns a node not on either page by part of its name or alias, honors `entity:<subtype>`/node-type filters, and excludes non-matching nodes.

### Guardrail claims
- Existing note-reader and Ontology correction action tests stay green unchanged, so payload shapes and URLs are unchanged.
- The note reader still offers "Add entity" and "Add relationship" exactly when the graph has a node that could be added (more entities than the note holds; more than one node).
- The search route is read-only and bounded: it returns at most a fixed number of nodes per call.

### Supporting obligations
- A storage method that matches name or alias substrings (case-insensitive, LIKE wildcards escaped) with optional node-type and entity-subtype filters and a limit, ordered prefix-first then by name; unit test in the DB tests.
- One shared node-to-editor-entry function in `web/shared.py`, used by `relationship_editor_model` and the search route, so labels match.
- `relationship_editor_model` receives only the nodes a page shows (note entities and edge endpoints on the note reader; the anchor and listed edge endpoints on the Ontology record).
- `editor.js`: `nodeChoices` becomes one `nodePicker` (search box feeding the existing `<select>`, debounced, keeps the current choice) used by both endpoint selects and the note reader's entity select; relation filtering uses the chosen node's type; with an anchor, a non-anchor `from` fixes `to` to the anchor.
- No server-rendered fallback for use without JavaScript (human decision, 2026-11-26).
- Manual browser check of the three editors, reported in Build.

### Allowed scope
- Reuse: the shared `editor.js`, `relationship_editor_model`, the existing `<select>` controls and their host payload code, `get_nodes` and `get_stats`, and the app-level JSON route pattern in `app.py`.
- Cheaper alternative: reuse `keyword_search` for the route; rejected because it matches summaries and facets (typing part of a name returns unrelated nodes) and cannot filter by entity subtype, which the relation-type restriction needs. Also rejected: a native `<datalist>`, which would replace the `<select>` value contract both page scripts and the Ontology review diff rely on.
- Include: `src/stock_ontology/db/storage.py` (one search method), `web/shared.py`, `web/app.py` (one GET route), `web/notes/views.py`, `web/ontology/views.py`, `static/editor.js`, `static/note_reader.js`, `static/ontology_edit.js` if the host needs changes, `static/library.css` for picker layout, `templates/partials/note_reader.html`, `templates/partials/ontology_edit_forms.html`, and the owning tests.
- Exclude/protect: `worker.py`, `pipeline.py`, `services/`, correction API URLs and request models, the catalog list and sidebar entity loads (`build_catalog_context`, `build_rail_context`), and existing action test assertions.

### Invariants changed
- `tests/test_web_ontology.py::test_note_reader_and_ontology_record_share_one_relationship_editor` (authored by `shared-editor-script`, protection ended at its ACCEPT) — today: the embedded model lists every node in the graph (`person` and `company`); after: it lists only the nodes the page shows (`person`), and the cross-page equality and label assertions stay. The README "Web UI Constraints" shared-editor rule still holds: node choice stays in `editor.js`.

### Decisions required
- None. The open choice was decided by the human on 2026-11-26: no server-rendered fallback for use without JavaScript.

## Proof

Builder route: the decisive witness is deferred to Build. The builder authors the tests named in Frame and must show them failing on `a6d6b58` before the change and passing after.

## Build

Candidate: `3fc4fb2 @ worktree/shared-editor-script-8b7869` (branch claude/shared-editor-script-8b7869; code in `2b51b29`, README entry in `3fc4fb2`)

### Changed paths
- `src/stock_ontology/db/storage.py` — `OntologyDB.search_nodes_by_name(query, *, types=(), limit=20)`: case-insensitive name-or-alias substring, LIKE wildcards escaped, `node_type` / `entity:<subtype>` filters, names starting with the query first, then by name.
- `src/stock_ontology/web/app.py` — `GET /api/nodes/search?q=&type=...` returns up to 20 `editor_node` entries from the read-only DB handle.
- `src/stock_ontology/web/shared.py` — `editor_node(node, lang)` (id, "name (type)" label, endpoint type) shared by the route and `relationship_editor_model`; the model gains a `search` placeholder.
- `src/stock_ontology/web/notes/views.py` — `_note_extraction` no longer calls `list_all_nodes` or unbounded `list_nodes`; it passes the note's entities and edge endpoints (`get_nodes`) to the model and sets `can_add_entity` / `can_add_relationship` from `get_stats` counts. `NoteExtraction.choices` is gone.
- `src/stock_ontology/web/ontology/views.py` — the record's model holds the anchor and listed edge endpoints (`get_nodes`) instead of `list_all_nodes`.
- `src/stock_ontology/web/static/editor.js` — `nodeChoices` became `nodePicker`: a search box before the existing `<select>`, debounced 200 ms, stale responses dropped, first match selected and `change` dispatched, template options such as `__new__` kept. `relationshipEditor` filters relations by the chosen node's type; with an anchor, a non-anchor source fixes the target to the anchor.
- `src/stock_ontology/web/static/note_reader.js` — the entity select uses `nodePicker` (adding excludes the note's entities); editors focus the search box. `static/ontology_edit.js` — the review diff labels a searched node from its option text.
- `src/stock_ontology/web/templates/partials/note_reader.html` — no per-entity `<option>` loop; `data-note-entity-ids` and `data-search-label` added; add buttons use the new flags.
- `src/stock_ontology/locales/{en,fr,es,ja,ko,zh}.json` — `note_reader.search_node`.
- `README.md` "Web UI Constraints" — new entry for the rule, with Why and Guarded by.
- Tests: `tests/test_db.py::test_search_nodes_by_name_matches_names_and_aliases_within_types`, `tests/test_web_ontology.py::test_editors_find_nodes_by_search_instead_of_loading_the_graph` (new); `tests/test_web_ontology.py::test_note_reader_and_ontology_record_share_one_relationship_editor` (node-set assertion narrowed, as listed under Frame's Invariants changed).

### Protected witnesses
- None independently authored (builder route). Existing note-reader and Ontology action tests were not edited.

### Evidence
- RED: the new and changed tests copied onto a detached `2ce9522` worktree, `uv run pytest -q tests/test_db.py tests/test_web_ontology.py -k "search_nodes_by_name or search_instead or share_one"` — 3 failed.
- GREEN on `2b51b29`: `uv run pytest -q` — 556 passed; `uv run ruff check src tests` — clean. `3fc4fb2` changes only `README.md`.
- Manual browser check (built-in browser, scratch fixture app with a worker thread, minimal registry, three entities, one note, one edge):
  - Note reader relationship add: the model held only the note's two nodes. Typing "rob" found the person. Relations were offered by type. Typing "t" in the target found TSMC, and the source was excluded from its own target search. Submitting posted `/api/notes/relationship/add` and reloaded with the new row.
  - Note reader entity relink: typing "n" listed matches after the kept "create entity" option, and choosing it showed the new-entity fields.
  - Ontology people record: the add form defaulted the source to the anchor, and a target search found TSMC. A non-anchor source (NVIDIA) offered no relation and disabled the target search. An edge edit went through preview and confirm and reloaded with the change.
  - Not exercised in the browser: add-mode exclusion of the note's entities (the fixture note already held every entity), and the review diff label for a searched endpoint (checked by reading the code only).

### Deviations
- `src/stock_ontology/locales/*.json` (one new key in each of six catalogs) and `README.md` are outside Frame's Include list. The search box needs a translated label, and the README entry is the constraint-capture duty for the rule this change sets.
- Relations are now offered by endpoint type even when no node of the target type exists yet. Before, the full node list let the editor hide them. The target search then finds nothing.

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
