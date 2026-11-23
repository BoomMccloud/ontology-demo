# Ontology

The domain model and its vocabulary: what a node, an edge, and a facet are,
which enum facet values and relation names are allowed. Everything else in the
app reads or writes these shapes. These files import no app module outside this
layer.

## Files

- `src/stock_ontology/models.py`: the shapes.
- `src/stock_ontology/vocab.py`: code's typed copy of the closed enum
  vocabularies and the facet schema, and the shared signal filter rules.
- `src/stock_ontology/registry.py` and `ontology_registry.json`: the official
  ontology (relations, companies, themes, aliases, official facet
  vocabularies, the facet schema, suggestions). The registry is the source and
  code is checked against it: `load_registry` fails when `facet_vocabularies`
  or `facet_schema` differs from `vocab.py`.

## Models (`models.py`)

- `Node` with `node_type` in `entity | event | view | theme`, plus `name`,
  `summary`, `aliases`, `facets`, and `source_doc_id`.
- `Edge` with `from_id`, `to_id`, `relation`, and `facets`.
- Official facets are typed: the registry's `facet_schema` gives each one a
  kind and a required flag, and `OntologyDB` enforces it on write (see
  Facet schema below). Facets the registry does not declare stay open.
- Sentiment helpers: `derive_sentiment_from_stance` and
  `resolve_item_sentiment` (edge, then node, then stance). `VALID_SENTIMENTS`
  and `normalize_sentiment` are re-exported from `vocab.py`.
- LLM structured-output shapes used by ingestion: `ExtractedEntity`,
  `ExtractedEvent`, `ExtractedView`, `ExtractedTheme`, `ExtractedEdge`,
  `ExtractionResult`, `ConsensusSynthesis`, and `FacetKV`. Their enum fields are
  typed with the vocab `Literal`s behind a before-validator, so an
  out-of-vocabulary value becomes the field's fallback (an unknown sentiment
  becomes missing). The required subtypes (`entity_type`, `event_type`,
  `view_type`, `stage`) are the exception: an out-of-vocabulary value becomes
  None, and the default applies only when the field is omitted.

## Vocabularies (`vocab.py`)

One `Vocabulary` per closed enum: `entity_type`, `event_type`, event `status`,
`view_type`, view `status`, `stance`, `sentiment`, `support_strength`,
`conviction`, and `stage`. Each lists its members with a one-line definition,
an alias map (for example `outperform` to `buy`, `rumour` to `rumor`, `stale`
to `superseded`), and an ingest fallback. `NODE_FACET_VOCABS` keys them by node
type.

- One normalization rule: strip, lowercase, spaces and hyphens to `_`, then
  aliases. `coerce_<enum>` returns the member or None.
- Ingest stores the member or the fallback (`coerce_or_fallback`) for an
  optional facet. A facet the registry requires gets no fallback: a missing
  or out-of-vocabulary value fails the write, and the pipeline regenerates
  the note's extraction, up to 2 regenerations (`MAX_EXTRACTION_ATTEMPTS = 3`
  calls in `pipeline.py`) before the note fails. An optional official facet
  whose value cannot be coerced to its kind is dropped before the write, in
  extraction and consensus synthesis, and the note is kept. Only under a
  registry that declares no `facet_schema` does a subtype keep its fallback.
  Repair
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
  `query_entity_signals` and web search (`search.SearchFilters.matches`) call.

## Facet schema (`facet_schema`)

`ontology_registry.json` declares, per node type and for edges, each official
facet's `kind` (`enum`, `number`, `date`, `text`, `list`) and `required` flag.
`NODE_FACET_SCHEMA` and `EDGE_FACET_SCHEMA` in `vocab.py` are code's copy, and
every `enum` facet has a vocabulary. Required today: entity `entity_type`,
event `event_type`, view `view_type`, theme `stage`, edge `basis`. Event
`event_date` and view `as_of` are dates, view `target_price` is a number; the
other vocabulary facets are optional enums.

- `OntologyRegistry.check_facets(node_type, facets)` (node_type None for an
  edge) returns the facets coerced to their kind, or raises
  `FacetSchemaError` (a `ValueError`). Coercion is lossless only
  (`coerce_facet_value`): a numeric string becomes a number, a date stays the
  ISO string it was, a required enum is stored as its member. An optional
  enum only has to be a string; audit still reports values outside the
  vocabulary.
- Facets the registry does not declare pass through unchanged.
- `drop_uncoercible_optional(node_type, facets)` is the ingest rule: it removes
  optional official facets that cannot be coerced and leaves required ones
  for `check_facets` to refuse.
- `create_minimal_registry()`, the built-in default, declares the shipped
  `facet_schema` and `facet_vocabularies`, so an `OntologyDB` opened without a
  registry enforces the same schema. A registry that declares no
  `facet_schema` enforces nothing. A registry without `facet_vocabularies` is
  refused; code's copy is never filled in.
- The registry `version` (now 2) is stamped into the DB; see
  [storage.md](storage.md).

## Registry (`registry.py`)

`normalize_relation_name` is the one relation-name rule; `OntologyDB.upsert_edge`
and `update_edge` apply it on write.

`OntologyRegistry` holds canonical relations (with aliases, inverses, and
domain and range rules), core companies, house themes, facet aliases, the
official facet vocabularies (`facet_vocabularies`: per node type and for
edges, each vocabulary's members with definitions, aliases and fallback), and a
queue of pending suggestions. Official edge facets are `sentiment` and `basis`
(`extracted | synthesized`, set by code at each edge write). Other edge facet
keys stay free-form, and `audit` reports them in `non_official_edge_facet_keys`. `canonicalize_edge` maps a raw relation and
direction to the canonical form. `create_minimal_registry()` is the built-in
default. `load_registry` and `save_registry` read and write the JSON file.

## Used by

Every other module. A change here ripples everywhere, so keep it small and
additive. Renaming a field on `Node` or `Edge` also means changing the row
mapping in `db/schema.py` (see [storage.md](storage.md)).

## Tests

`tests/test_registry_audit.py` covers the registry. `tests/test_vocab.py`
covers the vocabularies, the facet schema and its drift check, kind coercion,
and filter rules. `tests/test_official_facets.py` covers enforcement,
regeneration and versioned migration end to end. The models are covered
through `tests/test_db.py`, `tests/test_pipeline.py`, and
`tests/test_relationships.py`.
