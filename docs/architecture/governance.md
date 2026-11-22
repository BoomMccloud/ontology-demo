# Governance: audit and repair

Keeps the stored graph consistent with the registry (see
[ontology.md](ontology.md)). `audit` reports drift, and `repair` fixes the
cases with one right answer.

## Files

- `src/stock_ontology/audit.py`
- `src/stock_ontology/repair.py`

## Audit

`run_ontology_audit(db, registry, ...)` reads a read-only DB and returns an
`AuditReport`: unmapped relations, direction problems, ticker issues,
near-duplicate entities, suspicious aliases, facet alias hits, and
contradictory reciprocal edges. The `audit` command also adds unmapped items
to the registry file as `pending` suggestions for a human to review (on by
default, off with `--no-sync-suggestions`).

## Repair

`repair_ontology(db, registry)` writes to the DB. It deletes rows from notes
no longer in the ingestion log, renames registered alias and inverse relations,
and merges exact name or alias duplicates. Judgment calls are left to `audit`.
Merge survivors keep a stale embedding. `RepairReport.merged_survivor_ids`
lists them, and the CLI `repair` command passes them to the pipeline's
`reembed_nodes`.

`repair` is the second writer to `ontology.db` besides ingestion. It issues
no SQL itself. Its writes go through `OntologyDB` methods made for it:
`list_artifact_doc_ids`, `count_document_artifacts`, `update_edge`,
`merge_node_into`, and `delete_edges`.

## Depends on

[ontology.md](ontology.md) and [storage.md](storage.md).

## Used by

The CLI (`audit`, `repair`) and the web ontology page (audit results).

## Tests

`tests/test_registry_audit.py`, `tests/test_repair.py`,
`tests/test_relationships.py`.
