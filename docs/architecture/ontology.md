# Ontology

The domain model and its vocabulary: what a node, an edge, and a facet are,
which enum facet values and relation names are allowed. Everything else in the
app reads or writes these shapes. These files import no app module outside this
layer.

## Files

- `src/stock_ontology/models.py`: the shapes.
- `src/stock_ontology/vocab.py`: the closed enum vocabularies and the shared
  signal filter rules.
- `src/stock_ontology/registry.py` and `ontology_registry.json`: the data
  registry (relations, companies, themes, aliases, suggestions).

## Models (`models.py`)

- `Node` with `node_type` in `entity | event | view | theme`, plus `name`,
  `summary`, `aliases`, open `facets`, and `source_doc_id`.
- `Edge` with `from_id`, `to_id`, `relation`, and open `facets`.
- Sentiment helpers: `derive_sentiment_from_stance` and
  `resolve_item_sentiment` (edge, then node, then stance). `VALID_SENTIMENTS`
  and `normalize_sentiment` are re-exported from `vocab.py`.
- LLM structured-output shapes used by ingestion: `ExtractedEntity`,
  `ExtractedEvent`, `ExtractedView`, `ExtractedTheme`, `ExtractedEdge`,
  `ExtractionResult`, `ConsensusSynthesis`, and `FacetKV`. Their enum fields are
  typed with the vocab `Literal`s behind a before-validator, so an
  out-of-vocabulary value becomes the field's fallback (an unknown sentiment
  becomes missing).

## Vocabularies (`vocab.py`)

One `Vocabulary` per closed enum: `entity_type`, `event_type`, event `status`,
`view_type`, view `status`, `stance`, `sentiment`, `support_strength`,
`conviction`, and `stage`. Each lists its members with a one-line definition,
an alias map (for example `outperform` to `buy`, `rumour` to `rumor`, `stale`
to `superseded`), and an ingest fallback. `NODE_FACET_VOCABS` keys them by node
type.

- One normalization rule: strip, lowercase, spaces and hyphens to `_`, then
  aliases. `coerce_<enum>` returns the member or None.
- Ingest stores the member or the fallback (`coerce_or_fallback`). Repair
  stores the member or the lowercased raw value, never the fallback
  (`canonicalize_stored`). Values are stored canonical, so readers compare
  them directly and never re-lowercase.
- The extraction prompt (`llm/prompts.py`), the agent tool schema, and the
  extraction model descriptions are generated from these lists.
  `tests/test_i18n.py` checks every member has an `enum.<group>.<member>`
  locale key.
- Signal filters: `parse_sentiment_filter`, `parse_category_filter` and
  `SIGNAL_CATEGORY_ALIASES` parse user input once. `matches_signal_filter`
  holds the category, rumor and sentiment rule that both the agent's
  `query_entity_signals` and web `run_hybrid_search` call.

## Registry (`registry.py`)

`normalize_relation_name` is the one relation-name rule; `OntologyDB.upsert_edge`
and `update_edge` apply it on write.

`OntologyRegistry` holds canonical relations (with aliases, inverses, and
domain and range rules), core companies, house themes, facet aliases, and a
queue of pending suggestions. `canonicalize_edge` maps a raw relation and
direction to the canonical form. `create_minimal_registry()` is the built-in
default. `load_registry` and `save_registry` read and write the JSON file.

## Used by

Every other module. A change here ripples everywhere, so keep it small and
additive. Renaming a field on `Node` or `Edge` also means changing the row
mapping in `db/schema.py` (see [storage.md](storage.md)).

## Tests

`tests/test_registry_audit.py` covers the registry. `tests/test_vocab.py`
covers the vocabularies and filter rules. The models are covered
through `tests/test_db.py`, `tests/test_pipeline.py`, and
`tests/test_relationships.py`.
