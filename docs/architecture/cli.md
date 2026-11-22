# CLI

The `stock-ontology` command (Typer), wired up as `stock_ontology.cli:app`. It
builds settings, the LLM client, and the DB, then hands off to the other
modules. It should hold no business logic of its own.

## Files

- `src/stock_ontology/cli.py`

## Commands

| Command | Module it drives | Writes to DB |
| --- | --- | --- |
| `ingest` | pipeline | yes |
| `watch` | pipeline | yes |
| `reembed` | pipeline | yes |
| `repair` | governance, then pipeline `reembed_nodes` | yes |
| `audit` | governance | no (may update the registry file) |
| `inspect` | storage | no |
| `ask`, `chat` | agent | no |
| `serve` | web app | no |

Most commands take `--lang` / `-l`.

## Depends on

Every other module. It's the composition root.

## Tests

CLI cases live in `tests/test_db.py`, `tests/test_registry_audit.py`,
`tests/test_i18n.py`, and `tests/test_relationships.py`.
