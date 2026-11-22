---
proposal_id: "event-view-separation"
state: BUILT
witness: builder
candidate: "8dbbc33 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/event-view-separation (branch proposal/event-view-separation)"
---

# Proposal: Event View: Separate Data from Presentation

## Proposal

Status: approved by the requester on 2026-11-22.

### Intent

The event view (the requester's example is `/catalog?file=MSFT/2026-11-21_news_and_views.md`) should have "the same kind of separation" between data and presentation as the company view, using the same technique.

### Tentative primary claim

The event view shows the same information as today, and its presentation is separated from the data it displays, the same way as the company view.

### Why now

None stated.

### Known constraints

- Use the same technique as the company view proposal (`company-view-separation`).

### Non-goals

None stated.

### Open choices

- What "event view" means. The example URL is the catalog's source-note page, which renders a raw note file with its matched company and authors. Ontology events today appear only as rows inside the company and theme pages, and there is no page for a single event. The choice is between separating the source-note page as it is, adding a dedicated event page, or both. Resolved: the requester chose "Source-note page as is". Separate the catalog's source-note page (`/catalog?file=...`) as it is today, with no dedicated event page.
- Whether the rest of the catalog views (company, author and all-notes lists) are in scope, since they share one context builder with the note page. Not answered by the requester. The answer "Source-note page as is" points to the note page only, so Frame scopes to the `?file=` note page and leaves the list views alone, unless Frame finds that impossible without them, in which case Frame records it under `Decisions required` and stops.
- Sequence relative to `company-view-separation` and `theme-view-separation`. Resolved: both landed first, in main at `9864691`.

## Frame

Candidate: `9864691 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/event-view-separation (branch proposal/event-view-separation)`, clean tree plus this ledger.

### Verified reality
- `uv sync` then `uv run pytest -q` at 9864691: 162 passed. The suites judging this change were green before it started. Limit: says nothing about which note page details those tests assert.
- `src/stock_ontology/web/app.py::catalog_page` (line 431) opens the DB through `_open_ro_db`, calls `build_catalog_context(db, settings.data_dir, ..., selected_file=file, note_format=format, lang=lang)`, maps `FileNotFoundError` to 404, adds `rail`, and renders `catalog.html`. Proves the route, the read-only open and that the context builder is the only data step. Limit: none beyond this route.
- `src/stock_ontology/web/catalog.py::build_catalog_context` (line 458) is one function for every catalog view. Its note step (lines 792 to 884) resolves `selected_file` through `resolve_safe_note_path`, reads the file, and builds `active_note` as a raw dict: the scanned note dict spread in (28 keys in all, among them `doc_id`, `status`, `size_bytes`, `header_authors`), plus `raw_text`, `raw_lines`, `rendered_html` from `render_markdown_safe`, `matched_company` (the shared `company_lookup` dict with `id`, `name`, `ticker`, `sector`, `consensus_stance`), `linked_authors` (new dicts with `id`, `name`, `role`, `organization`, `entity_href`, `reasons`), the alias `linked_people`, `prev_note`/`next_note` dicts, and `search_nodes_href`. A scratch run confirms the 28 keys. Proves where the note page leak is. Limit: `linked_people`, `search_nodes_href`, `raw_text` and most scan keys are read by no template.
- `src/stock_ontology/web/templates/catalog.html` lines 58 to 139 (the note reader section) read `active_note.*` 21 times and hold page logic inline: the company chip label with its optional ticker, the back link chosen from `view_mode` and `active_group` with `urlencode`d hrefs, the raw or rendered body chosen from `note_format`, and the prev and next hrefs built from `view_mode`, `active_note.folder` and `active_group.id`. The rendered body is `active_note.rendered_html | safe`; raw lines are autoescaped with `L<n>` anchors. No line reads `.facets`. Proves the template leaks on the note page. Limit: static reading only.
- The jumpbar (catalog.html lines 36 to 56) is shared by every catalog view, including the note page. It reads `company_groups | length`, `author_groups | length`, `total_notes`, `view_mode`, `active_group` and `selected_alpha`, and reads `active_note` only for truthiness. Proves the note page can be separated without touching the list views: the jumpbar stays as it is and the reader moves out. Limit: the full context on the note page still carries the list data, because the jumpbar counts need it.
- `src/stock_ontology/web/navigation.py::_catalog` (line 131) reads `note.get("subject_label")`, `note.get("folder")` and `note.get("title")` from `active_note`, and `group.get(...)` from `active_group`. `tests/test_web_navigation.py` lines 47 to 48 assert the note page breadcrumbs through rendered pages only. Proves the nav resolver depends on the dict shape and no nav test pins it. Limit: none.
- `build_catalog_context` also uses `active_note["title"]` for `page_context` and `active_note["rel_path"]` for `selected_file`. A grep of `src` and `tests` finds no other reader of `active_note` or its keys. Limit: none.
- `tests/test_web.py::test_web_catalog_screen_by_company_and_person_and_safety` (line 589) asserts the rendered note page (markdown table class, `<br>` kept, `<script>` escaped), the raw `<pre>` view and the 404s for traversal, hidden and backslash paths. `tests/test_web.py` around line 1919 asserts search results link to `?file=...&format=raw#L3` and that the raw page carries the anchor. Proves the XSS, raw-mode and safe-path behavior already has owners. Limit: no test asserts the note chips, back link or prev and next links.
- The technique: `tests/test_web.py::test_entity_page_templates_only_see_presentation_models` and `::test_theme_page_templates_only_see_presentation_models` with `_raw_facet_paths`, `_template_closure` and `RAW_FACET_TOKEN`, frozen dataclasses with mappers in `viewmodels.py`, and README `Web UI Constraints` (README.md:171). Because the note page holds no `facets`, `_raw_facet_paths` would pass today and cannot witness this change. Limit: the note page needs a stricter walk (no dicts or lists inside the model) and a static check on the template names it reads.
- `src/stock_ontology/web/viewmodels.py` imports `format_source_citation` from `catalog.py` (line 41). Proves note page models placed in `viewmodels.py` and imported by `catalog.py` would make an import cycle. Limit: none.

### Final primary claim
- Every catalog note page (`/catalog?file=...`, rendered and `format=raw`, in company, author and all views) renders the same output as at 9864691, while `build_catalog_context` hands the note reader only one frozen presentation model, built by a mapper from the note file and the DB lookups, with nested frozen models and tuples and no raw dict or list. The reader markup moves to a partial that reads only that model plus `t` and `t_enum`, so the back link, the prev and next hrefs, the company chip label and the raw or rendered choice are decided in the mapper, not in the template.

### Routing
- Witness: `builder`
- Why: the change rewires a read-only context builder and one Jinja section; it can break note page rendering, which is contained and reverts with the commit, and it crosses no service boundary and touches no stored data, auth or payment. The safe-path resolver and the markdown renderer are reused unchanged.
- Human-owned irreversible action: merging the candidate branch into `main`.

### Decisive witness
- Layer: web context builder plus template source, run offline through FastAPI `TestClient` and `build_catalog_context` on a seeded read-only DB.
- Permanent owner: `tests/test_web.py`.
- Witness: a new test, `test_note_page_templates_only_see_presentation_models`, reusing `_seed_web_db`, `TEMPLATES_DIR` and `RAW_FACET_TOKEN`, that (1) renders a note with siblings in company view (rendered), author view (raw) and all view, and asserts the title, company chip with ticker, author chip with link and reasons, the back link for each view, the prev and next hrefs, the escaped `<script>`, and the raw `L<n>` lines; (2) walks `active_note` from `build_catalog_context` for each view and asserts it is a frozen dataclass with no dict, list or mutable dataclass inside; (3) asserts `catalog.html` includes the note reader partial and reads no `active_note` attribute, and the partial's undeclared Jinja names are within `active_note`, `t` and `t_enum`.

### Guardrail claims
- Catalog list pages (company, author and all views, with and without `dir`, `author` and `alpha`) render unchanged.
- Note pages stay safe: paths resolve only through `resolve_safe_note_path` (traversal, hidden and backslash paths still 404), the rendered body is still `render_markdown_safe` output with `<script>` escaped, and raw lines are still autoescaped with their `L<n>` anchors.
- The web UI still opens `ontology.db` read-only; no write path is added.

### Supporting obligations
- Models live in `catalog.py` beside `build_catalog_context`, to avoid the import cycle: a note page model with its company chip, author chips, back link and prev and next links. Enum codes (`link_reason`) stay raw so `t_enum` stays in the template.
- One mapper builds the model from the resolved note metadata, the raw text, the format, the view mode, the active group, the sibling list and the DB-derived company and author lookups. Hrefs are built with `urllib.parse.quote`, which matches Jinja's `urlencode` on strings. Translated link labels use `translate(..., lang=lang)`, as `t()` does.
- The body field holds `render_markdown_safe` output only in rendered mode and the raw lines only in raw mode; the template still marks the body `| safe` and autoescapes raw lines.
- `navigation.py::_catalog` reads the model's attributes instead of `.get`; `active_group` handling stays as it is.
- Build compares rendered HTML of every `/catalog` page the web, search, navigation, relationship and i18n suites request against a 9864691 capture, plus a scratch edge seed (unmatched folder, company without ticker, header author without entity link, directory author, unassigned author group, file names with spaces and `&`, a `.txt` note, `zh`), and records the result.
- No separate unit tests unless the mapper grows branching beyond the template logic it replaces.

### Allowed scope
- Reuse: the presentation-model technique from `viewmodels.py` (frozen dataclasses built by mappers) applied inside `src/stock_ontology/web/catalog.py`, which already owns the note page data; `resolve_safe_note_path` and `render_markdown_safe` unchanged; the witness helpers and `_seed_web_db` in `tests/test_web.py`.
- Cheaper alternative: keep the reader inline in `catalog.html` and only swap the `active_note` dict for a dataclass. Rejected because the back link and sibling hrefs would still be built in the template from `view_mode`, `active_group` and `urlencode`, so logic stays in the template and no static check could confirm the reader reads only the model. Splitting the whole 450-line builder, or modeling the list views, is larger and outside the scope the requester's answer points to.
- Include: `src/stock_ontology/web/catalog.py` (note page dataclasses, mapper, `build_catalog_context` note step); `src/stock_ontology/web/templates/catalog.html` (replace the reader section with an include); new `src/stock_ontology/web/templates/partials/note_reader.html`; `src/stock_ontology/web/navigation.py::_catalog`; `tests/test_web.py` (new witness); `docs/architecture/web.md` one sentence naming the note page model; `README.md` extending the Web UI Constraints entry to the note reader.
- Exclude/protect: the catalog list views and their context keys, the jumpbar, `_scan_raw_notes`, `resolve_safe_note_path` and `render_markdown_safe`; everything under `src/stock_ontology/db/`; `app.py`; the entity and theme pages and their witnesses; existing tests; CSS and locale files; any dedicated event page; any visible change to page content or markup.

### Invariants changed
- None.

### Decisions required
- None.

## Proof

Candidate: `9864691 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/event-view-separation (branch proposal/event-view-separation)`

Route is `builder`. The decisive witness named in Frame is builder-owned and deferred to Build, which must author it in `tests/test_web.py` and observe it RED before implementation. No witness is protected by this ledger.

## Build

Candidate: `8dbbc33 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/event-view-separation (branch proposal/event-view-separation)`

Logs and scratch scripts live in the session scratchpad `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-FpkZNh/4fb6f79d-a7f6-4555-b469-2d18b87dd45e/scratchpad/event/` and may be cleared; every command below reruns offline.

### Files changed

- `src/stock_ontology/web/catalog.py`: adds frozen presentation models `NoteDetail`, `NoteCompanyChip`, `NoteAuthorChip` and `NoteLink`, and the mapper `_note_detail`. The mapper takes the resolved note metadata, the raw text, the format, the view mode, the active group, the sibling list, the matched company and the author groups, and decides the company chip label, the author chips, the back link, the prev and next links (hrefs built with `urllib.parse.quote`, as Jinja's `urlencode` does) and the body. The body is `render_markdown_safe` output in rendered mode and the raw lines in raw mode. The note step of `build_catalog_context` now sets `active_note` to this model; `page_context` and `selected_file` read its attributes. The unused `linked_people`, `search_nodes_href`, `raw_text` and scan keys are not carried over. Primary claim.
- `src/stock_ontology/web/templates/partials/note_reader.html`: new partial holding the note reader markup, reading only `active_note`, `t` and `t_enum`. Primary claim.
- `src/stock_ontology/web/templates/catalog.html`: the note reader section is replaced by `{% include "partials/note_reader.html" %}`; the jumpbar and every list view are untouched. Primary claim.
- `src/stock_ontology/web/navigation.py`: `_catalog` reads the note's `subject_label`, `folder` and `title` as attributes; `active_group` handling is unchanged. Primary claim.
- `tests/test_web.py`: new builder-owned witness `test_note_page_templates_only_see_presentation_models` with helper `_non_model_paths`, reusing `_seed_web_db`, `TEMPLATES_DIR` and `RAW_FACET_TOKEN`. Primary claim.
- `docs/architecture/web.md`: one sentence naming the note page models.
- `README.md`: the existing Web UI Constraints entry now covers `partials/note_reader.html` and names the new witness.

### Unit evidence

- Builder-owned decisive witness: `uv run pytest tests/test_web.py::test_note_page_templates_only_see_presentation_models -q`, run on a `git archive 9864691` copy with the candidate's `tests/test_web.py` dropped in: RED: 1 failed. The render assertions (part 1) passed, then the context walk failed because `active_note` is a dict; log: `logs/witness_red.log`.
- `uv run python scratchpad/event/red_detail.py` on the same 9864691 copy: RED detail: `active_note` is a dict with 28 keys, `catalog.html` has 21 `active_note` attribute reads, and the note reader partial does not exist; log: `logs/red_detail.log`.
- The witness was first written with indentation-exact render assertions and observed RED at 9864691 in the worktree. It was then changed to squash whitespace before matching, because one branch-free partial cannot reproduce the three differently laid-out back links of the old template. The RED above is from the revised witness.
- Mutation check: replacing the back link href in the partial with `/catalog?view={{ view_mode }}` fails the witness; restoring it passes.
- No separate unit tests: `_note_detail` carries no branching beyond the template logic it replaces, and the witness covers the company, author and all views.

### Green evidence

- Decisive witness and focused suites: `uv sync`, then `uv run pytest tests/test_web.py tests/test_search.py tests/test_web_navigation.py -v`: 68 passed; log: `logs/web_green.log`.
- Gate: `uv run pytest -v`: 163 passed (162 before plus the new witness); log: `logs/full_gate.log`.
- Same-output check: the scratch pytest plugin `scratchpad/event/plug/catsnap.py`, driven by `scratchpad/event/snap.sh`, captured every `/catalog` HTML page requested by `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_search.py`, `tests/test_relationships.py` and `tests/test_i18n.py`, twice at 9864691 (with the new witness, so its pages are included; the two base runs are byte-identical) and twice at the candidate. A scratch edge seed (`scratchpad/event/edge.py`: unmatched folder with `&` and spaces in the file name, company without ticker, header author without entity link, directory author, unassigned author group, `_general` note without heading, a `.txt` note, `zh`, and author, all and company views) rendered 84 pages on each tree. Results with `compare2.py` and `body_check.py`; log: `logs/render_compare.log`:
  - List pages: 37 of 37 byte-identical in both suite runs, and 7 of 7 in the edge seed.
  - Note pages: 14 of 14 in both suite runs and 77 of 77 in the edge seed are identical after collapsing whitespace runs and dropping whitespace before `>`. None are byte-identical, because the partial is indented two levels less and the company and author back links lose the line breaks inside their `<a>` tag.
  - Note bodies (the raw `<pre>` block and the rendered `note-rendered` block) are byte-identical on all 14 suite pages and all 77 edge pages, so raw line content, `L<n>` anchors and escaping are unchanged.
- Safety: `test_web_catalog_screen_by_company_and_person_and_safety` (traversal, hidden and backslash paths 404, `<script>` escaped) and the search raw-anchor test pass unchanged. `resolve_safe_note_path`, `render_markdown_safe`, `app.py` and `src/stock_ontology/db/` are not in the diff.
- `uv run ruff check src/stock_ontology/web/catalog.py src/stock_ontology/web/navigation.py tests/test_web.py`: 3 findings, all `raise-vanilla-args`, the same 3 as on the 9864691 copy (one in untouched `catalog.py` code, two in existing test fakes).

### Intervention record

- None: the change has no user-facing outcome to measure, since rendered pages carry the same content.

### Deviations

- None.

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
