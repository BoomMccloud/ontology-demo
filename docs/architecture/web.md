# Web app

A FastAPI app with a 1990s library-style UI over the graph and a Clippy chat
that talks to the agent. It never writes to `ontology.db`.

## Files

- `src/stock_ontology/web/app.py`: `create_app(settings, llm=None)` and routes.
- `src/stock_ontology/web/viewmodels.py`: turns `OntologyDB` results into
  template contexts. `build_search_results` shapes the shared search
  ([search.md](search.md)) into the search page's best-match card and sections.
  The entity page context holds only frozen presentation models
  (`EntityHeader`, `ConsensusSummary`, `EventRow`, `ViewRow`, `ThemeLinkRow`,
  `RelatedEntityRow`, and so on) and prepared label/value pairs, so its
  templates never read `facets`. The theme page context does the same with
  `ThemeHeader`, `FirstOrderRow` (with its `ExposureLink`s), `SecondOrderRow`
  (with its `SecondOrderPath`s), `EventRow` and `ViewRow`.
- `src/stock_ontology/web/catalog.py`: the raw notes browser, XSS-safe Markdown
  rendering, and source citations. Note paths go through the search module's
  `resolve_safe_note_path`.
- `src/stock_ontology/web/navigation.py`: the navigation registry. Every HTML
  route maps to a workflow (top nav: Research, Ontology), an owning section
  (left nav), an archetype (`page` or `component`), and a breadcrumb trail.
  `_render` resolves it for every page, so templates never set navigation
  state themselves.
- `src/stock_ontology/web/templates/` and `src/stock_ontology/web/static/`.

## Routes

Pages: `/`, `/companies`, `/themes`, `/entity/{id}`, `/theme/{id}`, `/search`,
`/catalog`, `/ontology`. `/ask` redirects to `/` with the Clippy dock open and
the page context carried. The Clippy dock is on every page.

`/search` shows the functional results first: a best-match card, then
sections for entities and themes, items connected through relationships,
events and views, and note passages, each labeled with why it matched. Beside
them, a pinned agent column holds the Clippy chat window. `clippy.js` moves the
dock's window into the column, sends the search word to `/api/chat` once per
word, and shows a failed state if the run fails. Detach turns the column into
a floating window. The column, the floating window, and the dock on other
pages share one chat session.

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
request. `tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat`
enforces this.

## Depends on

[storage.md](storage.md) (read-only), [search.md](search.md), [agent.md](agent.md), [llm.md](llm.md),
[ontology.md](ontology.md) (models and registry), [governance.md](governance.md)
(audit results for the ontology page), and config and i18n from
[shared.md](shared.md). It may not import the pipeline.

## Used by

The CLI `serve` command.

## Tests

`tests/test_web.py` and `tests/test_web_navigation.py`, plus web cases in
`tests/test_i18n.py` and `tests/test_relationships.py`.
