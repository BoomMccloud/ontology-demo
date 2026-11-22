# Shared: config and i18n

Plumbing used across modules.

## Config

- `src/stock_ontology/config.py`
- `Settings` reads `.env` and the environment: data directory, DB path,
  registry path, embedding size, provider keys and URLs, provider chains
  (`LLM_PROVIDER`, `LLM_PROVIDERS`, `LLM_FALLBACK_PROVIDERS`,
  `EMBEDDING_PROVIDERS`), cooldown, and `APP_LANGUAGE`.
- `SUPPORTED_EXTENSIONS` (`.md`, `.txt`) is shared by the pipeline and the
  web catalog.
- Used by the LLM router, the pipeline, the web app, and the CLI.

## i18n

- `src/stock_ontology/i18n.py` and `src/stock_ontology/locales/*.json`
- Six UI languages: `en`, `zh`, `ko`, `ja`, `es`, `fr`. Research text stays in
  its original language.
- `resolve_language` picks a language from the query string, cookie, or
  `Accept-Language`. `translate`, `translate_enum`, `translate_subtype`, and
  `format_relation_label` render UI strings.
- Used by the agent, web app, CLI, and config.

## Tests

`tests/test_i18n.py`.
