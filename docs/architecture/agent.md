# Agent

The read-only portfolio manager (PM) query agent. It answers questions by
calling tools over the graph.

## Files

- `src/stock_ontology/agent.py`
- `src/stock_ontology/llm/pydantic_ai_model.py` adapts the app's `LLMClient`
  to a Pydantic AI `Model`, so the agent loop runs on Pydantic AI while
  provider fallback stays in the LLM layer.

## How it works

`OntologyAgent(db, llm, language)` refuses to start unless `db.read_only` is
true. `ask(message, max_rounds=8)` runs a tool-calling loop and keeps chat
history until `reset()`.

Tools exposed to the model (`TOOL_SCHEMAS`):

- `search_nodes`: vector and keyword search.
- `get_entity_overview`: one company with its consensus, themes, and links.
- `query_entity_signals`: events and views for a company, filtered by category.
- `find_theme_companies`: companies exposed to a theme.
- `get_node_details`: one node by id.
- `traverse_graph`: breadth-first walk from a node.
- `list_catalog`: counts and top nodes, for orientation.

Each tool is a thin wrapper over an `OntologyDB` query. Every call is recorded
in a tool trace that the web chat shows.

`build_agent_system_prompt(language)` adds a reply-language instruction. The
graph's own text stays in its original language.

## Depends on

[storage.md](storage.md) (read-only), [ontology.md](ontology.md),
[llm.md](llm.md), and i18n from [shared.md](shared.md).

## Used by

The CLI (`ask`, `chat`) and the web app (`/api/chat`).

## Tests

`tests/test_agent.py`, `tests/test_i18n.py`, and parts of
`tests/test_gemini.py` and `tests/test_dashscope.py`.
