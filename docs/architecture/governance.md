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
contradictory reciprocal edges. Unmapped relations combine stored `edges`
with `pending_edges` rows whose relation is still unmapped (counts, endpoint
signatures and samples; `AuditSummary.pending_edges` counts the pending ones),
so an extracted relation the registry does not know still becomes a
suggestion. The `audit` command also adds unmapped items
to the registry file as `pending` suggestions for a human to review (on by
default, off with `--no-sync-suggestions`). Near-duplicate company and theme
pairs become `suggestions.merges` entries; a reviewer sets each to `approved`
or `rejected`, decisions survive later syncs, and a pending pair that audit no
longer reports is dropped.

## Repair

`repair_ontology(db, registry)` writes to the DB. It deletes rows from notes
no longer in the ingestion log, canonicalizes stored enum facets on nodes and
edges through `vocab.py` (case and aliases, so legacy `stale` becomes
`superseded`; an unknown optional enum is dropped, the ingest rule
(`drop_uncoercible_optional` limited to enums), and an unknown required
subtype is lowercased and kept, never replaced; both are counted in
`RepairReport.facets_canonicalized`), renames registered alias and
inverse relations, promotes each pending edge whose relation the registry
now maps into `edges` through `canonicalize_edge` and `upsert_edge` (alias,
inverse direction and alias facets as at ingest), deletes it from
`pending_edges`, and counts it in `RepairReport.pending_edges_promoted`;
still-unmapped pending rows stay. Repair never moves a legacy unmapped edge
out of `edges`, and since `update_edge` refuses unmapped relations, a run that
must rewrite one stops with `FacetSchemaError` and rolls back. It then
merges the pairs of `approved` merge suggestions (never pending or rejected
ones), and merges exact name or alias duplicates. It backfills edge `basis`
first, because every edge rewrite must carry that required facet. Last, it
runs the same facet migration a writable open runs
(`OntologyDB.migrate_facets(registry)`): official facets are coerced to their
registry kind where lossless, counted in `RepairReport.facets_migrated`, and
the DB is stamped with the registry's schema stamp. Repair's own writes go through the
DB's checks, so a legacy node whose required facet is missing or outside the
vocabulary stops the run with `FacetSchemaError`. Judgment calls are left to
`audit`.
Merge survivors keep a stale embedding. `RepairReport.merged_survivor_ids`
lists them, and the CLI `repair` command passes them to the pipeline's
`reembed_nodes`.

Repair rewrites stored `money` facets as amount plus currency. When a value
names no currency, it reads the one currency the source note writes next to
that amount (`$` and `US$` are USD, `NT$` is TWD, `HK$` is HKD). A value it
cannot resolve stays as stored and is counted in `money_facets_unresolved`.
This covers node facets and relation facets such as `OWNS.transaction_value`.
Pending edges are promoted only when their relation is mapped and their
endpoints are allowed.

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
