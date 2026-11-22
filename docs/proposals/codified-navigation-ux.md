---
proposal_id: "codified-navigation-ux"
state: BUILT
witness: builder
candidate: "df390f3 @ worktree .claude/worktrees/codified-navigation-ux-0ef91c, branch claude/codified-navigation-ux-0ef91c (parent 6d4b2d7)"
---

# Proposal: Codified Top/Left Navigation, Page Archetypes, and UX Lint

## Proposal

Status: approved by requester on 2026-11-22.

### Intent

Reorganize the Web UI so the top nav holds workflows and the left nav holds the selected workflow's details. Everything inside the main workspace is either a functional page (such as Search, Ask, Overview, or Ontology) or a functional template/component (such as company list, author list, company view, or notes view).

Fix the current navigation gaps: clicking a company (or other detail page) should keep its owning section highlighted in the left nav (such as Companies for a company), note authors should have a left-nav entry, and detail/drill-down views (such as a company page) should display breadcrumbs at the top to navigate back. Search and Ask are part of Research, not top-nav workflows, until global search and global ask exist. Ask should be "clippy", on the lower right. Codify this navigation and page-structure UX so violations are detected automatically: by lint where lint can check it, and by something else where it can't. CSS should be enforced for everything.

### Tentative primary claim

Navigating anywhere in the Web UI presents a top nav of workflows (Research, Ontology) and a left nav of the selected workflow's details where the owning section is always highlighted, detail and drill-down views (such as a company view) show top breadcrumbs to navigate back, Ask is available as a "clippy" in the lower right, every workspace screen follows either a functional page or a functional template/component pattern, and a screen or template that violates these UX rules is detected automatically.

### Why now

Clicking into a company currently clears all left-nav highlights and shows no top breadcrumbs to go back, and there is no left-nav entry for note authors; without codifying the navigation UX, pages drift into inconsistent patterns. The UX should be fixed first, before work touches the search and ontology modules specifically.

### Known constraints

- Top nav holds workflows: Research and Ontology. Research is the task (not "Browse" and not "Equities").
- Top nav right side: a Search quick link and the language selector. Search and Ask are not top-nav workflows until global search and global ask are implemented.
- Research left nav: Overview (today's Home), Companies, Themes, Authors, Other Entities, Notes (by company, by author, all), Search.
- Ontology left nav: Model (Entities, Events, Views, Themes, Edges) and Governance (Registry, Audit).
- Ask is a "clippy" on the lower right: an on-page agent, just like how it worked in MS Office, that interacts directly with our agent backend.
- Viewing a detail page highlights its owning section; viewing a company highlights Research in the top nav and Companies in the left nav.
- Show breadcrumbs at the top of detail views (such as a company page) to navigate back, using the commonly understood breadcrumb setup.
- One page width everywhere for mobile, and one for desktop.
- Structure everything inside the main workspace as either a functional page (e.g., search) or a functional template or component (e.g., company view, notes view, company list).
- Violations must be detected automatically: lint where lint can check it, something else where it can't.
- Enforce CSS for everything.
- Old tests (such as the Home link cap) can be ignored if they're not doing anything major.
- Ship everything together: the workflow/detail shell, author entry, breadcrumbs, Ask clippy, functional templates/components refactor, CSS enforcement, and automatic detection.

### Non-goals

- No visual language redesign. This is purely a navigation UX change.
- No changes to the search and ontology modules specifically in this pass; fix the UX first.
- Representing note authors as an entity (entity = author). The requester will fix that later; the Authors entry works from existing author information until then.
- Global search and global ask.

### Open choices

None stated.

## Frame

Candidate: `6d4b2d7 @ main working tree (dirty outside web/: db/ package split, agent.py, cli.py, pyproject.toml, uv.lock from other in-flight work; src/stock_ontology/web/ and tests/test_web.py clean)`

### Verified reality
- `uv run pytest -q -p no:cacheprovider` at the candidate: 83 passed. A first run minutes earlier failed collection with 11 `ImportError: cannot import name 'OntologyDB' from 'stock_ontology.db'` while another session was mid-way through the `db/` package split: proves the offline suite is green before this change once that split is in place; limit: the tree outside `web/` is moving under concurrent work, so Build must re-record the baseline.
- `uv run ruff check src/stock_ontology/web tests/test_web.py`: 2 pre-existing errors (`catalog.py:154` try-consider-else, `catalog.py:822` raise-vanilla-args); repo-wide `ruff check src tests` reports 39: proves ruff is not green before the change; limit: these are not caused by and need not be fixed by this proposal.
- `src/stock_ontology/web/templates/base.html`: one left rail (`portal-rail`) holds search box, Home, Companies, Themes, Research Notes, Ontology, Reference Desk (Ask), Advanced Search and the language selector; active state is `active_nav == '<key>'` rendered as `portal-rail-active` with `&rsaquo;`; there is no top nav; limit: says nothing about page bodies.
- `src/stock_ontology/web/viewmodels.py:391` (`build_entity_context`) and `:469` (`build_theme_context`) set `active_nav: ""`: proves detail pages clear every highlight, the reported bug.
- `rg breadcrumb src/stock_ontology/web/templates` returns nothing; `.breadcrumb` exists unused at `static/library.css:375`; `catalog.html:59` renders `catalog-path-bar` (`Dirs by author > <author>`), asserted by `tests/test_web.py:680-720`: proves one breadcrumb-like component exists only inside the catalog; limit: it is not linked to the workflow root.
- `src/stock_ontology/web/app.py:142` `_render`: the single render choke point for every HTML route; it already injects `clippy_i18n` and defaults `wide_layout: False`; `app.py:483` sets `wide_layout = True` only for `/ontology`; `library.css:56-65` gives `.portal-frame` 820px and `.portal-frame-wide` 1080px; `library.css:1032` is the only breakpoint (`max-width: 740px`): proves two desktop widths and one mobile breakpoint today.
- `src/stock_ontology/web/static/clippy.js:1-20,141-144,160,250`: the existing Clippy already supports an optional dock (`clippy-launcher`, `clippy-window`, open/minimize buttons, open state in `sessionStorage`), reads page context from `body[data-page-context]`, and POSTs to the existing `/api/chat` and `/api/chat/reset`; it is loaded only by `ask.html:65`; no `clippy-launcher`/`clippy-window` CSS exists in `library.css`: proves the on-page agent can reuse the current client and backend unchanged; limit: dock markup and dock CSS must be added.
- `tests/test_web.py:199` asserts `"clippy-dock" not in r_home.text`: proves an earlier decision removed the floating Clippy from pages.
- `src/stock_ontology/web/catalog.py:498` maps `view=author|authors|person|people` to the author view; `tests/test_web.py:688-695` shows it lists analysts and explicit note authors and excludes CEOs: proves an author directory already exists from existing author information, so Research › Authors needs no data change.
- `app.py:240` `/companies?kind=other` and `viewmodels.py:290-297` (`active_kind`): proves Other Entities already has a page.
- `rg -c 'style=' src/stock_ontology/web/templates`: 98 inline `style=` attributes across 12 templates (`ontology.html` 41, `catalog.html` 15, `facet_consensus_card.html` 9, `companies.html` 7, `search.html` 6, others ≤4); no `<style>` blocks: proves CSS is not enforced today.
- `tests/test_i18n.py:45-60`: every locale file must carry exactly the `en.json` key set: proves new nav labels must be added to all six locales.
- `tests/test_web.py:1218-1243` (`test_web_1997_home_minimal_link_cap`) counts every `<a>` on `/`, shell included, against `<= 25`.

### Final primary claim
- Every HTML page in the Web UI renders a top nav of workflows (Research, Ontology) with exactly one workflow marked current, a left nav of that workflow's sections with exactly the owning section marked current (a company page marks Research and Companies; a theme page marks Research and Themes; a non-company entity marks Research and Other Entities; a note marks Research and Notes; an Ontology tab marks Ontology and that tab), detail and drill-down views show a breadcrumb at the top from the workflow root to the current page, the Ask Clippy is available in the lower right of every page and talks to the existing agent backend, and a page or template that breaks these rules or uses inline styles fails an automated check.

### Routing
- Witness: `builder`
- Why: the change can break page rendering and navigation of the read-only Web UI, which is contained, offline-tested and reversible; the Clippy reuses the existing `/api/chat` contract unchanged, and no DB, ingestion, auth, payment or stored user data is touched.
- Human-owned irreversible action: None.

### Decisive witness
- Layer: in-process HTTP render tests (`fastapi.testclient.TestClient`) plus static template checks, both under pytest.
- Permanent owner: new `tests/test_web_navigation.py`, with the shared seed fixture from `tests/test_web.py`.
- Witness: for every GET route in `app.routes` that returns HTML, and for each seeded variant (`/`, `/companies`, `/companies?kind=other`, `/themes`, `/catalog?view=company|author|all`, a catalog author and company drill-down, a catalog note, `/search?q=…`, `/entity/<company>`, `/entity/<person>`, `/theme/<id>`, each `/ontology?tab=…`), the response has exactly one `aria-current="page"` in the top nav and exactly one in the left nav, matching the route's entry in the navigation registry; detail and drill-down variants render a breadcrumb whose first item is the workflow, whose middle items are links, and whose last item is the current page and not a link; every page includes the Clippy dock; a route not in the registry fails the test. A static pass over every template fails on any `style=` attribute, any `<style>` element, any page template that does not extend `base.html`, any `partials/` template that extends `base.html` or emits shell navigation, and any literal class token not defined in `library.css`.

### Guardrail claims
- The Clippy dock on any page sends the page's context to `/api/chat` and renders the reply, and reset still clears the session, with the existing `FakeWebLLM` path (`tests/test_web.py:175`) passing.
- Existing deep links keep working: `/catalog?view=person`, `/companies?kind=other`, `/entity/<id>`, `/theme/<id>`, `/ontology?tab=<tab>`, `/search?q=…`, and `/ask` (now a redirect to Overview with the Clippy opened, carrying `context`) return 200 or a redirect to a 200.
- At desktop width every page uses the same frame width, and below the mobile breakpoint every page uses the same full-width frame; no page sets `wide_layout`.

### Supporting obligations
- Add one navigation registry (a small module beside `viewmodels.py`) mapping each route and view variant to workflow, section, archetype (`page` or `component`), and breadcrumb parent; `_render` reads it so templates never hand-set `active_nav`. Unit-test candidate: registry lookup for each variant.
- Replace the rail in `base.html` with a top nav (Research, Ontology on the left; Search quick link and language selector on the right) and a per-workflow left nav: Research → Overview, Companies, Themes, Authors, Other Entities, Notes (by company, by author, all), Search; Ontology → Model (Entities, Events, Views, Themes, Edges) and Governance (Registry, Audit). Use `aria-current="page"` as the single current marker.
- Render one breadcrumb partial from the registry, reusing the `.breadcrumb` style; fold `catalog-path-bar` into it.
- Add the Clippy dock markup to `base.html`, load `clippy.js` on every page, add dock CSS to `library.css` in the existing visual language, and make "Ask about X" links open the dock with that context instead of navigating.
- Move all 98 inline styles into named classes in `library.css` without changing their computed look; drop `portal-frame-wide` and use one desktop width (1080px, the width Ontology already needs) and the existing 740px breakpoint for mobile.
- Add new nav labels to all six locale files.
- Implement the static template checks as a pytest module, since ruff does not parse Jinja.

### Allowed scope
- Reuse: `_render` (`app.py:142`) for nav context; `clippy.js` dock support and `/api/chat` as-is; `.breadcrumb` and `catalog-path-bar` for breadcrumbs; the catalog author view (`catalog.py:498`) for Authors; `/companies?kind=other` for Other Entities; `/ontology?tab=` values for Ontology sections; the `tests/test_web.py` seed for the new test module.
- Cheaper alternative: fixing only `active_nav` on entity and theme pages and adding an Authors link to the existing rail was rejected; the claim needs the workflow/section split, breadcrumbs, the on-page Clippy, CSS enforcement and automatic detection, which the approved Proposal requires in one pass.
- Include: `src/stock_ontology/web/templates/**`, `src/stock_ontology/web/static/library.css`, `src/stock_ontology/web/static/clippy.js` (dock wiring only), `src/stock_ontology/web/app.py` (render context, `/ask` redirect, drop `wide_layout`), `src/stock_ontology/web/viewmodels.py` and `src/stock_ontology/web/catalog.py` (nav and breadcrumb context only), a new navigation registry module in `src/stock_ontology/web/`, `src/stock_ontology/locales/*.json` (new labels), `tests/test_web.py` (assertions listed under Invariants changed), new `tests/test_web_navigation.py`, and the README Web UI lines.
- Exclude/protect: search ranking and query code and ontology data assembly in `viewmodels.py` (non-goal; `entity-first-search` and `ontology-search` own them); `/api/chat`, `/api/chat/reset` and `src/stock_ontology/agent.py`; `src/stock_ontology/db/**`, `cli.py`, `pyproject.toml`, `uv.lock` (other in-flight work); ingestion, the registry and any author-entity data change (non-goal); the read-only DB invariant; no visual language redesign beyond moving existing styles into classes and styling the dock in the current look.

### Invariants changed
- `tests/test_web.py:199`: today: no `clippy-dock` on Home ("no floating Clippy"); after: the Clippy dock renders on every page.
- `tests/test_web.py:191-196` and `:536`: today: rail labels `Research Notes`, `Ask`, `Search` and the active marker `&rsaquo; Home`; after: top nav `Research`, `Ontology`; left nav `Overview`, `Notes`, `Search`; Ask only as the Clippy; current marked by `aria-current="page"`.
- `tests/test_web.py:865` (`/ask` page renders the Clippy send button inline): today: `/ask` is a full page; after: `/ask` redirects to Overview with the Clippy opened and the context carried.
- `tests/test_web.py:1243` (`test_web_1997_home_minimal_link_cap`): today: at most 25 `<a>` on `/` including the shell; after: the count covers only the `<main>` workspace, per the Proposal's allowance to ignore old tests that do nothing major.
- `app.py:483` and `library.css:63-65`: today: `/ontology` uses a wider frame; after: one desktop width and one mobile width for every page.
- `README.md:42`: today: "masthead language selector"; after: top nav language selector.

### Decisions required
- None.

## Proof

Deferred to the builder witness (`witness: builder`). Build adds `tests/test_web_navigation.py` as the decisive witness named in Frame and must show it failing on the candidate before the change and passing after.

## Build

Candidate: `df390f3 @ worktree .claude/worktrees/codified-navigation-ux-0ef91c, branch claude/codified-navigation-ux-0ef91c (parent 6d4b2d7)`

### Files changed

- `src/stock_ontology/web/navigation.py` (new) — the one navigation registry: `NAV_ROUTES` maps each HTML route to a resolver giving workflow, owning section, archetype (`page`/`component`) and breadcrumb; `WORKFLOWS` and `LEFT_NAV` define the top and left navs. Satisfies the primary claim's single-source navigation and "a route not in the registry fails".
- `src/stock_ontology/web/app.py` — `_render` calls `resolve_nav` on the matched route path and injects `nav`, `nav_workflows`, `nav_groups`, `clippy_open`, `clippy_context`; `wide_layout` dropped; `/ask` is now a 303 redirect to `/?ask=1` carrying `context` and an explicit `lang`; `/search` no longer hand-sets `active_nav`. `/api/chat` and `/api/chat/reset` unchanged.
- `src/stock_ontology/web/viewmodels.py`, `src/stock_ontology/web/catalog.py` — removed the seven hand-set `active_nav` keys (nav context only). No search or ontology data assembly touched.
- `src/stock_ontology/web/templates/base.html` — top nav (`#top-nav`: Research, Ontology; Search quick link and language selector on the right), per-workflow left nav (`#side-nav`), single `aria-current="page"` marker per nav, breadcrumb include, `data-archetype` on `body`, the Clippy dock (`#clippy-dock`, launcher, window, chips, log, form) and `clippy.js` on every page. The `rail-q` search box stays at the top of the left rail.
- `src/stock_ontology/web/templates/partials/breadcrumb.html` (new) — `nav > ol` breadcrumb from the registry; links for every item but the last, which carries `aria-current="page"`; classes `breadcrumb catalog-path-bar` (folds the old catalog path bar).
- `src/stock_ontology/web/templates/catalog.html` — removed the three hand-built `catalog-path-bar` blocks (now the shared breadcrumb at the top of the workspace).
- `src/stock_ontology/web/templates/entity.html`, `theme.html` — "Ask about X" links carry `data-clippy-context` so the dock opens in place; `href` still points at `/ask?context=…` without JS.
- `src/stock_ontology/web/templates/ask.html` — deleted (`/ask` redirects).
- 12 templates (`catalog`, `companies`, `home`, `ontology`, `search`, `theme`, `themes`, `partials/facet_consensus_card`, `facet_generic_table`, `facet_header`, `section_events`, `section_views`) — all 98 `style=` attributes replaced by `u-*` utility classes; dropped the undefined `ontology-diagram-card` class token (it had no rule, so no visual effect).
- `src/stock_ontology/web/static/library.css` — `.portal-frame` max-width 1080px, `.portal-frame-wide` removed, 740px stays the only breakpoint; top nav, breadcrumb list and dock styles in the existing palette and fonts; one `!important` utility per former inline declaration so each keeps the precedence the inline style had (no computed-look change).
- `src/stock_ontology/web/static/clippy.js` — dock wiring only: context from `#clippy-window[data-context]`, open on `data-open="1"`, click on `[data-clippy-context]` opens the dock with that context.
- `src/stock_ontology/locales/{en,es,fr,ja,ko,zh}.json` — 25 new keys (`nav.*`, `clippy.open_btn`, `clippy.dock_title`, `clippy.minimize_btn`). The workflow label reuses `rail.ontology` because `nav.ontology` already exists as "Ontology View".
- `tests/test_web_navigation.py` (new) — decisive witness as framed, plus registry lookup unit test.
- `tests/test_web.py` — only the Frame's invariant changes: rail labels and `&rsaquo; Home` → `aria-current` Overview/Research and `Notes`; `clippy-dock` now present; `/ask` asserts redirect to `/?ask=1` with the dock open (dropped `<h1>Ask</h1>`); link cap counts `<main>` only; the `/search` `>Home<` check (line 553, same rail-label invariant) → `>Overview<`. The `:865` i18n `/ask` assertions pass unchanged through the redirect, so they were left as is.
- `README.md` — "masthead language selector" → "top nav language selector"; one `## Web UI Constraints` entry (register routes in the navigation registry, no inline styles), guarded by `tests/test_web_navigation.py`.

### Unit evidence

- Baseline: `uv run pytest -q -p no:cacheprovider` at `6d4b2d7` in this worktree — 80 passed (Frame recorded 83 against the dirty main tree; this worktree has none of the other session's `db/` work); log: `/Users/jasonbxu/Library/Application Support/Claude/side-session-notes/local_7dff6d00-d482-41f8-a5f5-8b914f37d425/codified-navigation-ux-build-logs/baseline.log`.
- Builder-owned decisive witness: `uv run pytest -q -p no:cacheprovider tests/test_web_navigation.py` before any source change — RED: 33 failed, 2 passed (missing `stock_ontology.web.navigation`, no `#top-nav`/`#side-nav`/`#clippy-dock`, `/ask` not a redirect, 98 inline styles, undefined `ontology-diagram-card`, `.portal-frame-wide` present). The 2 passes are guardrails: the `/api/chat` round trip and "partials do not extend base"; log: `/Users/jasonbxu/Library/Application Support/Claude/side-session-notes/local_7dff6d00-d482-41f8-a5f5-8b914f37d425/codified-navigation-ux-build-logs/witness_red.log`.
- Registry lookup unit test `tests/test_web_navigation.py::test_navigation_registry_lookup` — RED in the run above (ModuleNotFoundError), GREEN after; log: `/Users/jasonbxu/Library/Application Support/Claude/side-session-notes/local_7dff6d00-d482-41f8-a5f5-8b914f37d425/codified-navigation-ux-build-logs/witness_green.log`.

### Green evidence

- Decisive witness: `uv run pytest -q -p no:cacheprovider tests/test_web_navigation.py` — 35 passed; log: `/Users/jasonbxu/Library/Application Support/Claude/side-session-notes/local_7dff6d00-d482-41f8-a5f5-8b914f37d425/codified-navigation-ux-build-logs/witness_green.log`.
- Gate: `uv run pytest -q -p no:cacheprovider` — 115 passed; log: `/Users/jasonbxu/Library/Application Support/Claude/side-session-notes/local_7dff6d00-d482-41f8-a5f5-8b914f37d425/codified-navigation-ux-build-logs/full_green.log`.
- Gate: `uv run ruff check src/stock_ontology/web tests/test_web.py tests/test_web_navigation.py` — 2 errors, both pre-existing in `web/catalog.py` (154, 822); no new errors; log: `/Users/jasonbxu/Library/Application Support/Claude/side-session-notes/local_7dff6d00-d482-41f8-a5f5-8b914f37d425/codified-navigation-ux-build-logs/ruff.log`.
- Manual smoke (not a gate): served the test seed locally with `FakeWebLLM`; `/entity/ent_nvda` shows Research + Companies marked and `Research > Companies > NVIDIA`; "Ask about NVIDIA" opened the dock in place and a message returned the fake reply through `/api/chat`; at 375px width `/entity/ent_nvda` and `/ontology?tab=audit` had no horizontal overflow.

### Intervention record

- None: a read-only navigation UX change with no user-facing outcome metric defined in Frame.

### Deviations

- None. Judgment calls inside scope, for Audit to check: `/catalog?view=author` (and `view=person`) is owned by Research › Authors, so Notes › By author is marked only for a note opened from the author view; `/search` and Ontology tabs are pages without breadcrumbs; the Notes group heading is a label, and the Notes breadcrumb crumb links to `/catalog`.

## Audit

## Revisions
