# Architecture

The app is nine modules. Each has its own page.

| Module | Files | Page |
| --- | --- | --- |
| Ontology | `models.py`, `registry.py` | [ontology.md](ontology.md) |
| Storage | `db/schema.py`, `db/storage.py` | [storage.md](storage.md) |
| Data pipeline | `pipeline.py`, `llm/prompts.py` | [pipeline.md](pipeline.md) |
| LLM layer | `llm/` | [llm.md](llm.md) |
| Agent | `agent.py`, `llm/pydantic_ai_model.py` | [agent.md](agent.md) |
| Web app | `web/` | [web.md](web.md) |
| Governance | `audit.py`, `repair.py` | [governance.md](governance.md) |
| CLI | `cli.py` | [cli.md](cli.md) |
| Shared | `config.py`, `i18n.py`, `locales/` | [shared.md](shared.md) |

## Data flow

```text
data/**/*.md|.txt
      │  pipeline (writes)           repair (writes)
      ▼                                   │
  ontology.db  ◄──────────────────────────┘
      │  PRAGMA query_only = ON
      ▼
  agent, web app, audit, CLI inspect (read)
```

## Dependency layers

Each layer may import from layers above it, never below.

```text
1. shared         config, i18n
2. ontology       models, registry
3. storage, llm   db/, llm/          (independent of each other)
4. pipeline, agent, governance        (independent of each other)
5. web app
6. CLI            composition root, imports everything
```

## Isolation

Editing a module's internals should stay inside that module. Changing its
interface touches its callers, and that's expected.

`tests/test_architecture.py` enforces this offline:

- Every source file maps to one module above.
- Imports follow the layers. The web app may not import the pipeline, and
  storage may not import governance, for example.
- Only `stock_ontology.db` touches SQLite (`.conn`, `sqlite3`, `sqlite_vec`),
  so a schema change can't silently break another module.

If the test fails on a dependency you actually want, update `ALLOWED` in the
test and the layer list here together.

These couplings remain and the test does not catch them:

1. `LLMClient` has `extract_document` and `synthesize_consensus`, which are
   pipeline tasks, and `llm/` holds the pipeline's prompts and the agent's
   Pydantic AI adapter. So pipeline prompt changes and agent loop changes both
   land in `llm/`. A generic structured-output call would let the pipeline own
   its prompts and schemas.
2. `OntologyDB` is one wide class shared by the pipeline, agent, web app, and
   governance. The graph queries (`get_entity_overview`,
   `find_theme_companies`, `traverse_bfs`) serve both the agent and the web
   app, so tuning one for the UI changes the agent's tool output too.
