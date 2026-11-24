---
proposal_id: "library-information-architecture"
state: ACCEPTED
witness: builder
candidate: "a237730f027bc7647ad8c80c6bea43822a090ca0 @ main shared workspace, in-scope SHA-256 e162c148e4cb77e37508d884040fa641c9e7e0da08539b8fa27026d18e9e2f51"
---

# Proposal: Stock Research Library Information Architecture

## Proposal

### Intent

Implement the approved app map as the structure for the Stock Research Library. Give each function a clear home across all three workflows before designing individual screens. [Approved interactive mockup](../../work/information-architecture/structure.html) · [Page inventory and navigation rules](../../work/information-architecture/architecture.md)

Make Modern the default. Show the brand and primary destinations in a single top navigation row, as in the requester’s screenshot. Give users a theme control to switch between Modern and Classic at any time. The control applies the corresponding CSS theme to the shared app shell. [Modern visual reference](../../work/information-architecture/index.html)

| Area | What belongs there |
| --- | --- |
| Research | Overview, Companies, Themes, and Other Entities. Company, theme, and entity records own their details, connections, and links to source evidence. |
| Notes | The source library owns All Notes, By Company, and By Author. Each note opens in a dedicated reader with Source and Extraction. Company and author links live in the note header. |
| Ontology | Graph Explorer owns the model guide and browsing by entity, event, view, theme, or relationship. Governance owns Registry and Audit. |
| Shared tools | Search, Paste a note, and Language are available from the shared header. Search can scope results to Notes. Ask Clippy stays available with the current page as context. |

### Tentative primary claim

A user who enters the Library in its default Modern theme sees the primary destinations alongside the brand in one top row, can follow that navigation to the NVIDIA note, switch to Classic while reading it, and use the same visible return link to recover their origin.

### Why now

The NVIDIA screen puts the Research Notes heading, catalog grouping controls, breadcrumb, and a separate Back button above the note. This mixes list controls, navigation, and record content. Set the app-wide structure first so individual page designs have a consistent place to build from.

### Known constraints

- Modern presents Overview, Companies, Themes, Other Entities, and Notes directly in the same top row as the brand. Keep Ontology and the shared tools reachable within the Modern header.
- Classic presents the approved Research, Notes, and Ontology workflow tabs with its burgundy masthead, serif typography, and left rail. Both themes share the same page hierarchy, URLs, and content.
- Use CSS for theme differences such as colors, typography, spacing, borders, and visual layout. Users can switch themes without leaving their current page or losing the selected section, filters, or return context.
- Use the approved mockup as the reference for navigation and which page owns each function. The page bodies shown in it are placeholders for later design work.
- Keep the note reader’s return link contextual and preserve access to notes from research records and search citations.

### Non-goals

- Changes to page ownership or evidence links beyond the approved app map.
- Detailed layouts and content design for individual pages. That work follows the app-wide structure.

### Open choices

The location of the theme switch and the order in which individual pages will be designed are deferred to the next pass.

## Frame

Candidate: `a237730f027bc7647ad8c80c6bea43822a090ca0 @ main, in-scope working-tree SHA-256 5481db325552589494b63b819fdb35de8ea5d7c9eb2c4fd2ea7e02f4604614e2 (first implementation, before single-row amendment)`.

### Verified reality

- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_web_navigation.py tests/test_web.py tests/test_i18n.py tests/test_search_ontology_options.py` passed 125 tests. `.venv/bin/python -m pytest -q -p no:cacheprovider` passed 509 tests. These establish the offline baseline and do not exercise browser CSS.
- `web/navigation.py::WORKFLOWS`, `LEFT_NAV`, and `NAV_ROUTES`, `web/app.py::_render`, and `web/templates/base.html` already centralize the three workflows, section ownership, breadcrumbs, layout, global language links, and Clippy. The present rail repeats Notes group modes and Search, and the Other Entities list and records use Companies ownership.
- `web/templates/catalog.html`, `web/catalog.py::build_catalog_context` and `_note_detail`, and `web/templates/partials/note_reader.html` already distinguish list states and render from a frozen reader model. The note case still renders navigation from both a breadcrumb and a separate Back link. The reader supplies `format=raw` and source line IDs through the current route and already supplies job state and note action markup.
- `web/viewmodels.py::build_entity_context` and `build_theme_context` map existing evidence and source citations from the read-only graph. `web/catalog.py::build_catalog_context` already groups notes by author and has working legacy author aliases. These structures support record sections and evidence links without new graph storage calls or attribution rules.
- `web/app.py::search_page`, `web/viewmodels.py::build_search_results`, and `web/templates/search.html` use one shared results pipeline with raw note line links. `in=notes` presently carries shell context and does not itself scope the results.
- `web/templates/ontology.html` already has all graph, registry, and audit content behind `tab` query variants and the `structure-explorer` anchor. Registry and Audit currently appear both on the rail and inside the explorer’s tab bar.
- `web/static/library.css` supplies the existing Classic stylesheet and `base.html` is the common markup. The approved app map and Dedicated reader visual reference provide the navigation and modern target respectively. This supports a CSS overlay switched on the shared document without theme-specific HTML or application state.
- The first implementation passed 512 offline tests. Inspecting `web/templates/base.html` and `web/static/library-modern.css` at this candidate shows a separate masthead, workflow row, and visible left rail in Modern. The current registry already carries every requested primary link and its owner, including the Notes default and separate Other Entities view.

### Final primary claim

- Starting in Modern on desktop, a Library user sees the S mark and Stock Ontology brand in the same top row as Overview, Companies, Themes, Other Entities, and Notes. They can use that row to reach the same note from its approved paths, switch to Classic in place, then use the reader’s one parent link to recover the origin.

### Routing

- Witness: `builder`.
- Why: The change is confined to the existing web presentation boundary and a browser-local visual preference. Existing read, write-job, and assistant contracts are reused.
- Human-owned irreversible action: Any merge or deployment.

### Decisive witness

- Layer: Offline FastAPI HTML integration and a local seeded browser smoke test.
- Permanent owner: `tests/test_web_navigation.py` for rendered workflow, route and reader contracts, supplemented by existing note and source tests in `tests/test_web.py`. Run the browser check against the real seeded app in Chrome and record the result without introducing a browser dependency.
- Witness: Author and observe proposal-specific RED before source changes. Then check that the Notes rail exposes one library section and the selected grouping is local to the list. Open a seeded note from a filtered list, a company or theme evidence link, and a note-scoped Search citation. Verify the same title and source identity, independent Source and Extraction selection, one contextual return link, and preservation of raw source line anchors. In Chrome verify computed Modern styles by default, switch to Classic and back with the user control, verify changed computed styles and stable route, query, hash and selected state, and verify the contextual return. Recheck the switch after navigation and at desktop and mobile widths.
- Before changing the shell, observe RED from a new permanent render assertion for the ordered five registry-backed destinations inside the Modern header and from seeded desktop Chrome for the brand and those five links sharing a row with the Modern rail absent. Afterward verify the exact order, active owner, all five destinations, reachable Ontology and shared tools by keyboard, and Classic workflow tabs and left rail restored in place. Verify those conditions at desktop and a contained, keyboard-reachable responsive layout without horizontal document overflow at narrow widths. Record exact browser command and result without adding a browser dependency.

### Guardrail claims

- Legacy catalog, company, entity, theme, search and ontology URLs still open their relevant content. Raw citations still reach the original line, and note list filters and record-section origins survive the return.
- Note Process, extraction status and corrections retain their existing note-scoped behavior. Paste and Clippy keep their existing behavior and endpoints. Research reads remain read-only.
- Both themes share one route and content model. Classic keeps the burgundy masthead, workflow tabs and left rail. Modern has direct header navigation and no visible left rail. Both keep shared tools and Governance reachable with keyboard and translated labels.

### Supporting obligations

- Implement the approved ownership in the existing navigation registry. Research owns Overview, Companies, Themes and Other Entities. Notes owns one catalog rail section and the reader, with grouping controls inside the list. Ontology owns Graph Explorer on the rail and Registry and Audit under Governance. Keep each graph subtype or relationship view local to Graph Explorer. Search, Paste, language and theme belong in the shared shell and Clippy keeps its dock.
- Make the primary Notes link start in All Notes via the existing query form. The bare `/catalog` URL may retain its legacy company default. Keep existing authored and unassigned groups and alphabet filters.
- Use record-local navigation to expose the approved company, theme and other entity sections. Reuse current read models and available cited evidence. Use existing author grouping when exposing authored research. Keep relationship and exposure semantics intact and emit only typed presentation values to entity, theme and note templates.
- Give the note one page heading. Place browse controls in the listing. Map existing origin links into a single reader parent from the navigation resolver, preserving accepted query context with safe internal destinations and a deterministic fallback. Keep raw and rendered source under Source, and the existing action and status markup under Extraction. For URL-driven panes, the inactive section can remain in the response with `hidden` where that preserves existing action and source contracts.
- Use one optional Notes scope on existing Search and keep the legacy `in=notes` URL useful. Expose matching note passages through the existing search result data rather than implementing new search. Retain direct `format=raw#L…` citations and include enough origin context to return to filtered search.
- Apply Modern through CSS over the shared markup, with Classic retaining existing style rules. Use a labeled shell theme control and a browser-local preference. Check active indicators, focus, translated labels, and theme restoration across navigation. Keep the existing no-inline-style and responsive layout invariants.
- Required gates after the candidate stabilizes: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_web_navigation.py tests/test_web.py tests/test_i18n.py tests/test_search_ontology_options.py`, `.venv/bin/python -m pytest -q -p no:cacheprovider`, and the seeded browser witness.
- Use the current navigation registry items and NavState ownership to render the Modern primary links in the shared base template. Show the S mark and Stock Ontology wordmark in Modern, and use theme-scoped CSS to expose the Modern links and hide the Classic rail or the reverse. Keep Graph Explorer, Registry, Audit, Search, Paste, Language, the theme switch and Clippy available from their approved locations. A compact, keyboard-operable header disclosure is available for secondary links when needed. Keep one app shell and one theme control, with no theme-specific routes or page bodies.

### Allowed scope

- Reuse: `web/navigation.py`, `web/app.py::_render` and existing reader, search and ontology page handlers, `web/catalog.py::NoteDetail` and catalog grouping, `web/viewmodels.py` record and search presentation models, the existing shared layout, partials and stylesheet, and `tests/test_web_navigation.py`.
- Cheaper alternative: A stylesheet overlay alone would change appearance but leave repeated navigation and broken section ownership. Editing the note header alone would leave the same duplication in Search and Ontology. Existing URLs and view models can support the complete ownership change without a migration or a second app shell.
- Include: `src/stock_ontology/web/{navigation,app,catalog,viewmodels}.py`, existing or narrowly extracted web templates and partials for the listed surfaces, `src/stock_ontology/web/static/library.css` and narrowly scoped theme CSS and JS, `src/stock_ontology/locales/*.json`, `tests/test_web_navigation.py`, the narrow compatibility assertions in `tests/test_web.py` identified below, and the related README and `docs/architecture/web.md` navigation documentation.
- Exclude/protect: Database, service and worker write paths, extraction and note job semantics, search ranking and shared graph/search implementation, authentication, unrelated user changes, mockup source, separate theme templates, and detailed page-by-page design.
- For the amendment, limit source changes to the shell, navigation registry and render context, theme CSS, labels if needed, and the permanent navigation test and related docs. This extends the first implementation without additional IA or page changes.

### Invariants changed

- `README.md:198–200` and `docs/architecture/web.md:30–33,77–81`. Today, the registry owns workflow, section, archetype and breadcrumb, with a class owner in `library.css`. After, the same registry owns navigation, detail breadcrumbs can be a single contextual parent link, and any new visual theme is CSS on the same shared markup. Retain registered routes, one active owner, frame width and no inline styles.
- `tests/test_web_navigation.py:34–63,169–199` (`VARIANTS` and `test_page_marks_workflow_section_breadcrumb_and_dock`). Today, Other Entities marks Companies, Notes modes and note intake/search own separate rail entries, and graph tabs each own a rail entry. Note breadcrumbs end in the repeated title. After, assert the approved owners, one contextual note parent, Graph Explorer ownership for graph views, and Registry and Audit ownership on the Ontology rail. Retain route coverage, one current workflow and section, existing detailed breadcrumb checks where applicable, and Clippy.
- `tests/test_web.py:545–556` (`test_web_nav_and_advanced_search_filters`). Today, Overview requires `rail-q`. After, assert the single shared Search entry in the header and retain the existing search results and filter assertions.
- `tests/test_web.py:745–755,2121–2148` (catalog render and `test_note_page_templates_only_see_presentation_models`). Today, the note body repeats the note H1, the dedicated Back toolbar repeats the parent destination, and there is no reader section control. After, assert one note H1, one contextual breadcrumb parent, and the reader-local Source and Extraction choices. Retain list grouping and aliases, safe Markdown and raw line rendering, appropriate sibling behavior, and frozen presentation model coverage.
- `tests/test_web.py:1922–1932` (`test_web_search_note_links_jump_to_the_matching_line`). Today, exact citation URLs omit origin context. After, allow the validated return context in the link while requiring the same note path, raw source mode, and exact line fragment.
- `tests/test_web.py:1152–1158` (`test_web_ontology_view_connected_to_registry_and_audit`). Today, default Graph/Entity requires the combined Registry and live Audit overview. After, governance content is asserted at Registry or Audit. Keep graph blueprint and graph status or relationship checks with Graph Explorer and keep the existing Registry, Audit and missing-registry checks.
- `README.md:198–200`, `docs/architecture/web.md:30–39,89–92`, and `tests/test_web_navigation.py::test_page_marks_workflow_section_breadcrumb_and_dock` and `::test_library_has_one_workspace_per_workflow_and_one_shared_theme_control`. Classic keeps the existing active workflow and rail checks. Modern has a visible registry-derived primary navigation with the relevant active owner and no visible rail. Preserve one shared theme control and CSS-only projection. The fixed Classic frame width and existing base breakpoint test remain in force.

### Decisions required

- None. The screenshot fixes the desktop primary order. The exact presentation of secondary header links and the narrow-width adaptation are reversible shell choices.

## Proof

Builder-owned decisive witness deferred to Build.

## Build

Candidate: `a237730f027bc7647ad8c80c6bea43822a090ca0 @ main shared workspace, in-scope SHA-256 e162c148e4cb77e37508d884040fa641c9e7e0da08539b8fa27026d18e9e2f51`.

### Files changed

- `src/stock_ontology/web/{navigation,app,catalog,viewmodels}.py` and the corresponding templates implement workflow ownership, reader panes, contextual returns, evidence links, Notes-scoped Search, and separate Graph Explorer and Governance views. Existing routes, raw citation anchors, and note job endpoints remain available.
- `src/stock_ontology/web/templates/base.html`, the Library stylesheets, and `library-theme.js` render the registry-backed, single-row Modern desktop header and restore the Classic masthead, workflows, and rail when selected. The shared theme control stores its choice in the browser. `src/stock_ontology/locales/*.json` supplies labels in all six locales.
- The R1 repair touches `src/stock_ontology/web/static/library.css` and `src/stock_ontology/web/templates/partials/note_reader.html`. Table cells wrap at mobile widths in both themes. The existing job status renders in the shared note header, where it remains visible on Source after Paste. Process and correction controls remain in Extraction.
- `tests/test_web_navigation.py` owns the decisive HTTP checks. `tests/test_web.py` covers compatibility, raw source safety, and note job contracts. `README.md` and `docs/architecture/web.md` record shell, theme, navigation, and reader rules.

### Unit evidence

- Original navigation RED: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_web_navigation.py -k 'one_workspace or single_contextual or untrusted_return'` failed three expected checks before implementation. Log: `/private/tmp/stock-ia-red.log`.
- Amended desktop header RED: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_web_navigation.py -k modern_primary` failed because the direct navigation was absent. Log: `/private/tmp/stock-ia-modern-row-render-red.log`. The seeded browser also failed before that amendment because the Modern wordmark was absent. Log: `/private/tmp/stock-ia-modern-row-browser-red.log`.
- R1 overflow RED: `node /private/tmp/stock-ontology-ia-browser.cjs` failed the expanded 390px viewport check. Log: `/private/tmp/stock-ia-overflow-r1-red.log`.
- R1 paste RED: `STOCK_IA_FIXTURE_PORT=18853 node /private/tmp/stock-ontology-ia-browser.cjs --paste-red` failed because the queued job status was hidden when Source was selected. Log: `/private/tmp/stock-ia-paste-r1-red.log`.

### Green evidence

- Focused gate: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_web_navigation.py tests/test_web.py tests/test_i18n.py tests/test_search_ontology_options.py` passed 129 tests. Log: `/private/tmp/stock-ia-r1-focused.log`.
- Full gate: `.venv/bin/python -m pytest -q -p no:cacheprovider` passed 513 tests. Log: `/private/tmp/stock-ia-r1-full.log`.
- Seeded Chrome witness: `node /private/tmp/stock-ontology-ia-browser.cjs` passed the desktop header, theme switching, contextual returns, raw citation anchors, 48 mobile route/theme/locale combinations at 390px, and the real Paste flow against a temporary data directory. Source remained selected and the queued status was visible. Log: `/private/tmp/stock-ia-r1-browser-green.log`.
- `node --check src/stock_ontology/web/static/library-theme.js` and `git diff --check` passed.

### Intervention record

- None. Verification used a local seeded app and temporary data.

### Deviations

- None. The Overview entry is part of the shared navigation. Its recent-notes preview remains deferred to individual page design.

## Audit

Candidate: `a237730f027bc7647ad8c80c6bea43822a090ca0 @ main shared workspace, in-scope SHA-256 e162c148e4cb77e37508d884040fa641c9e7e0da08539b8fa27026d18e9e2f51`

Independence: fresh-context. The audit context reviewed the previous candidate and reproduced its failures. It did not author the implementation, repair, or expanded witness.

Primary-claim verdict: PROVED. Evidence: `tests/test_web_navigation.py` verifies the five ordered Modern destinations, active ownership, and the NVIDIA reader’s contextual returns. The seeded Chrome rerun verified the desktop row geometry, note entry from Notes, company evidence, and Search, and in-place theme switching with reader and return state preserved. The original navigation and desktop amendment RED logs record the expected pre-change failures. Limit: desktop geometry was checked at 1360px with seeded content.

Guardrail verdicts:

- Legacy URLs, raw citations, and return context: PROVED. Evidence: `tests/test_web_navigation.py`, `tests/test_web.py`, and the Chrome rerun covered legacy route variants, exact raw source lines, list filters, record section anchors, and scoped Search returns. Limit: the fixtures cover representative records and queries.
- Note Process, extraction status, corrections, Paste, Clippy, and read-only research: PROVED. Evidence: `tests/test_web.py` passed the lifecycle, correction, Paste, Clippy, and read-only checks. The expanded Chrome witness submitted a note through `/notes/new` and verified that the reader opened with Source selected and the queued job status visible. The R1 Paste RED log records the prior failure, and `partials/note_reader.html` keeps Process and corrections in Extraction. Limit: the browser exercised a queued job against a temporary data directory.
- Shared route and content model, theme navigation, and keyboard access: PROVED. Evidence: `base.html`, the stylesheets, `tests/test_web_navigation.py`, and the Chrome witness verify one shell and theme control, the Classic masthead and rail, Modern’s direct navigation, and keyboard access to Governance and shared tools. The mobile witness checked both themes in all six supported locales. Limit: browser verification used seeded content in Chrome.

Scope and duty verdict: scope HELD. Duties HELD. Evidence: R1’s `library.css` rules wrap mobile table cells at the existing breakpoint, and `partials/note_reader.html` moves the existing job state into the shared reader header without changing job semantics. The expanded Chrome witness closed both recorded R1 findings and passed all 48 combinations of Overview, Companies, Graph Explorer, and Audit at 390px across themes and locales. The changes stay within the approved paths, and `README.md` records the shared-shell and reader rules with existing test references. Limit: the mobile matrix measures the seeded pages at 390px.

Test homes: `tests/test_web_navigation.py` owns permanent shell, navigation, and reader coverage. `tests/test_web.py` retains compatibility and note-job coverage in the web integration suite.

Full gates: PASS. The required focused pytest command passed 129 tests. `.venv/bin/python -m pytest -q -p no:cacheprovider` passed 513 tests. `node /private/tmp/stock-ontology-ia-browser.cjs`, `node --check src/stock_ontology/web/static/library-theme.js`, and `git diff --check` passed. Limit: Chrome ran against a local seeded app with temporary data and a fake LLM.

Residual risks:

- Narrower viewports and wider production table contents were outside the browser matrix.

Recommendation: ACCEPT

Packet: Record acceptance for the audited candidate in `docs/proposals/library-information-architecture.md`. Merge and deployment remain human-owned.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->

### R1 — 2026-11-24 — Narrow tables and visible Paste job state
- Verdict: REVISE. The Overview theme table caused page overflow at 390px, and a newly queued job appeared only in Extraction. Candidate `e3308b736f79613d26921b537e2c409620e164f734031845f987008cea0718ac`.
- Changed: `web/static/library.css` wraps tables on phones, and `web/templates/partials/note_reader.html` moves the existing job state into the reader header. Seeded Chrome covers both behaviors.
- Re-audit: ACCEPT. The seeded 390px matrix and Paste status verification passed on candidate `e162c148e4cb77e37508d884040fa641c9e7e0da08539b8fa27026d18e9e2f51`.
