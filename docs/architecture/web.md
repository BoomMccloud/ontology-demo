# Web app

A FastAPI app with a 1990s library-style UI over the graph and a Clippy chat
that talks to the agent. It never writes to `ontology.db`.

## Files

- `src/stock_ontology/web/app.py`: `create_app(settings, llm=None)` and routes.
- `src/stock_ontology/web/viewmodels.py`: turns `OntologyDB` results into
  template contexts, including `run_hybrid_search`. The entity page context holds
  only frozen presentation models (`EntityHeader`, `ConsensusSummary`,
  `EventRow`, `ViewRow`, `ThemeLinkRow`, `RelatedEntityRow`, and so on) and
  prepared label/value pairs, so its templates never read `facets`.
- `src/stock_ontology/web/catalog.py`: the raw notes browser, path-safe note
  lookup, XSS-safe Markdown rendering, and source citations.
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

A new HTML route must be added to `NAV_ROUTES` in `navigation.py`.
`tests/test_web_navigation.py` fails on an unregistered route, a page without
exactly one current workflow and section, a detail page without a breadcrumb,
an inline `style=` or `<style>`, or a class missing from `library.css`.

API: `/api/chat`, `/api/chat/reset`, `/api/health` (LLM chain diagnostics
without secrets), `/api/language`, and `/set-language`.

Chat sessions are kept in memory, capped at `MAX_CHAT_SESSIONS` (50).

`/api/chat` uses only `OntologyAgent(...)` and `chat()`. It stores each
session's `ChatTurn.history` without reading it and passes it back on the next
request. `tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat`
enforces this.

## Depends on

[storage.md](storage.md) (read-only), [agent.md](agent.md), [llm.md](llm.md),
[ontology.md](ontology.md) (models and registry), [governance.md](governance.md)
(audit results for the ontology page), and config and i18n from
[shared.md](shared.md). It may not import the pipeline.

## Used by

The CLI `serve` command.

## Tests

`tests/test_web.py` and `tests/test_web_navigation.py`, plus web cases in
`tests/test_i18n.py` and `tests/test_relationships.py`.
