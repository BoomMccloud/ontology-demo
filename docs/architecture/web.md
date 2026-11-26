# Web app

A FastAPI app with a 1990s library-style UI over the graph and a Clippy chat
that talks to the agent. Its database connections are read-only. It imports
services, never storage. It can add a pasted file under `ONTOLOGY_DATA_DIR`,
and it submits Process and corrections as worker jobs.

## Files

The web layer is a shell plus one package per user-facing module. Each module
package holds `routes.py` (a `build_router(shell)` factory returning an
`APIRouter`) and, where it builds pages, `views.py` (its view models). Modules
render through the shell and share helpers only through `web/shared.py`, never
by importing another module's private code. Research imports
`build_search_filter_options` from Search because its overview embeds the
search bar.

- `src/stock_ontology/web/app.py`: `create_app(settings, llm=None, *, note_actions=False)`.
  It builds the `WebShell`, includes the five module routers, and keeps the
  shell-level routes: `/set-language`, `POST /api/language`, and `/api/health`.
- `src/stock_ontology/web/shell.py`: `WebShell`, the per-app object every
  router receives. It resolves the request language, opens the read-only graph,
  loads the optional registry, and renders templates (`render` resolves
  navigation for every page). It also holds `HTTP_STATUS` for typed service errors.
- `src/stock_ontology/web/shared.py`: view helpers used by more than one module:
  `build_rail_context`, `format_facet_value`, `format_facet_pairs`,
  `resolve_result_href`, and `format_source_citation` (with the note title
  extraction it needs).
- `src/stock_ontology/web/research/`: `/`, `/companies`, `/themes`,
  `/entity/{id}`, `/theme/{id}`, `/thesis/{id}`, and `POST /api/claims`. `views.py` turns graph results into template
  contexts. The entity page context holds only frozen presentation models
  (`EntityHeader`, `ConsensusSummary`, `EventRow`, `ViewRow`, `ThemeLinkRow`,
  `RelatedEntityRow`, and so on) and prepared label/value pairs, so its
  templates never read `facets`. The theme page context does the same with
  `ThemeHeader`, `ThemeCompanyRow` (with its `ExposureNote`s and
  `ThemeEvidenceItem`s), `EventRow` and `ViewRow`. The theme page also lists
  the theme's theses (`ThesisLinkRow`) and titles its stated-exposure list
  "Mentioned in Notes"; a row no thesis covers is marked a suggested candidate
  (`ThemeCompanyRow.suggested`). The thesis page (`build_thesis_context`,
  `thesis.html`) holds `ThesisHeader`, `ThesisMembershipRow`s with their
  `CatalystRow`, and the membership form's `CompanyOption`s. The company page
  lists its memberships as `CompanyThesisRow`s.
- `src/stock_ontology/web/search/`: `/search`. `build_search_results` shapes the
  shared search ([search.md](search.md)) into the search page's best-match card
  and sections; `build_search_filter_options` builds the filter choices and
  `build_active_filters` the applied-filter chips.
- `src/stock_ontology/web/notes/`: `/catalog`, `/notes/new`, and the `/api/notes*`
  routes. Job status, `/api/jobs/{job_id}`, is a shell route in `app.py` that
  Notes and Ontology both poll. `views.py` is the raw notes browser and
  XSS-safe Markdown rendering. Note paths go through the search module's
  `resolve_safe_note_path`. The note page (`?file=`) hands its reader partial
  one frozen `NoteDetail` (with `NoteCompanyChip`, `NoteAuthorChip` and
  `NoteLink`s), built by `_note_detail`. The reader shows the current ontology
  extraction above the source. Changed notes and older notes with unrecorded
  entity attribution show **Not processed** and can be processed on demand.
  The reader also shows the state of the note's latest job (`data-job-state`).
  Note discovery and status come from `services.notes.scan_notes`.
- `src/stock_ontology/web/ontology/`: `/ontology` and its model, registry, and
  audit tabs.
- `src/stock_ontology/web/clippy/`: the chat dock's `POST /api/chat` and
  `/api/chat/reset`, and the `/ask` redirect. Chat history is kept per router,
  capped at 50 sessions.
- `src/stock_ontology/web/navigation.py`: the navigation registry. Every HTML
  route maps to a workflow (top nav: Research, Notes, Ontology), an owning section
  (left nav), an archetype (`page` or `component`), and a breadcrumb trail.
  `WebShell.render` resolves it for every page, so templates never set navigation
  state themselves.
- Pasted notes are saved by `services.notes.save_pasted_note` in `_general/`.
  It writes a hidden temp file and publishes it with a hard link, so a note is
  never partial or overwritten. The paste route then queues the note's
  processing job and returns 201 `{"file", "job_id"}`.
- `src/stock_ontology/web/templates/` and `src/stock_ontology/web/static/`.

## Routes

Pages: `/`, `/companies`, `/themes`, `/entity/{id}`, `/theme/{id}`, `/thesis/{id}`, `/search`,
`/catalog`, `/notes/new`, `/ontology`. `/ask` redirects to `/` with the Clippy
dock open and the page context carried. The Clippy dock is on every page.

`/notes/new` posts JSON `{title, content}` to `POST /api/notes`, which returns
201 `{"file": "_general/<date>_<slug>.md", "job_id": ...}`. The reader uses
`POST /api/notes/process`, `/api/notes/relink`, and `/api/notes/relationship`.
The relationship table also uses `/api/notes/relationship/add` and
`/api/notes/relationship/delete` for confirmed note-scoped changes.
The entity list uses `/api/notes/entity/add` and `/api/notes/entity/delete`.
It attaches existing entities and removes membership and incident edges for the
selected note. The canonical entity stays in the ontology.
Each of these routes returns 202 `{"file", "job_id", "state"}` once the job is
submitted (404 for an unknown note, 503 without note actions); validation
happens in the job. `GET /api/jobs/{job_id}` reports the job, and the reader
polls it until the job succeeds, fails, or is waiting to retry. `serve` enables
these routes (`note_actions=True`). Corrections update the selected note's
links in the shared graph. These writes use the local demo's
shared account and require an access control layer before non-local hosting.

The theme and thesis pages add, edit, and remove theses and thesis
memberships. `claims.js` posts JSON `{kind, params}` to `POST /api/claims`,
which submits it through `ProcessingService.submit_claim` and returns 202
`{"job_id", "state"}` (422 for a refused write, 503 without note actions), then
polls `/api/jobs/{job_id}`. The forms render only when note actions are enabled.
A suggested candidate on the theme page links to each thesis page with the
company preselected (`/thesis/{id}?company=<id>`).

`/ontology` can review source-backed person or relationship edits when note
actions are enabled. Its correction endpoints bind the selected processed
note, graph values, and replacement fields to a short-lived review. Confirm
queues a worker correction. The worker checks the exact review and source
revision again within its transaction. Adding a relationship from a record
requires that the selected note already supports that record through extraction
membership, the node's source, or a sourced, non-synthesized incident edge.
The review binds the supporting association and the worker rechecks it.

Company and theme Registry editing requires `serve --registry-actions` on a
literal loopback address. The web process checks the loopback peer and exact
Host and Origin before every review or confirmation. Forwarded requests are
refused. Publication and application have separate confirmations. Application
can use only a completed worker preview for an outstanding browser record edit.
The existing CLI can review and confirm a full registry proposal or rollout.

`/search` shows the functional results first: a best-match card, then
sections for entities and themes, items connected through relationships,
events and views, and note passages, each labeled with why it matched. The
Clippy dock behaves as on every other page: it floats in the lower right and
can be minimized. `clippy.js` moves the search note into the dock, opens the
dock, sends the search word to `/api/chat` once per word, and shows a failed
state if the run fails. Every page shares one chat session.

The advanced-search options come from `build_search_filter_options`: node
types from `search.NODE_TYPES`, every enum from `vocab.py`, and relations from
the registry the app loads. No value observed in the DB is offered; only the
connected-entity options are DB instances. Subtype and status options are
`<node_type>:<value>`. Without a registry file the relation select is hidden.

A new HTML route must be added to `NAV_ROUTES` in `navigation.py`.
`tests/test_web_navigation.py` fails on an unregistered route, a page without
exactly one current workflow and section, a detail page without a breadcrumb,
an inline `style=` or `<style>`, or a class missing from `library.css`.

API: `/api/chat`, `/api/chat/reset`, `/api/health` (LLM chain diagnostics
without secrets), `/api/language`, and `/set-language`.

Chat sessions are kept in memory, capped at `MAX_CHAT_SESSIONS` (50).

`/api/chat` uses only `OntologyAgent(...)` and `chat()`, and passes
`data_dir` so the agent can grep notes. It stores each
session's `ChatTurn.history` without reading it and passes it back on the next
request. `tests/test_web_clippy.py::test_web_chat_endpoint_uses_only_agent_chat`
enforces this.

## Depends on

[storage.md](storage.md) (read-only), [search.md](search.md), [agent.md](agent.md), [llm.md](llm.md),
[ontology.md](ontology.md) (models and registry), [governance.md](governance.md)
(audit results for the ontology page), and config and i18n from
[shared.md](shared.md). It may not import the pipeline.

## Used by

The CLI `serve` command.

## Tests

`tests/test_web_*.py` (one file per module, shared fixtures in `tests/web_support.py`), plus web cases in
`tests/test_i18n.py` and `tests/test_relationships.py`.
