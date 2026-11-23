# Ontology

The domain model and its vocabulary: what a node, an edge, and a facet are,
which enum facet values and relation names are allowed. Everything else in the
app reads or writes these shapes. These files import no app module outside this
layer.

## Files

- `src/stock_ontology/models.py`: the shapes.
- `src/stock_ontology/vocab.py`: code's typed copy of the closed enum
  vocabularies, the built-in registry's base facet schema, the facets code
  depends on, and the shared signal filter rules.
- `src/stock_ontology/registry.py` and `ontology_registry.json`: the official
  ontology (relations, companies, themes, aliases, official facet
  vocabularies, the facet schema, metadata limits, suggestions). The registry
  is the source. `load_registry` fails when `facet_vocabularies` differs from
  `vocab.py`, when `facet_schema` or `metadata_max_length` is missing, or when
  `facet_schema` lacks a facet code depends on. The per-type specs live only
  in the registry.

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
  the extraction run that owns the item and every later run, up to 2 regenerations (`MAX_EXTRACTION_ATTEMPTS = 3`
  calls in `pipeline.py`) before the note fails. A bad optional `date` or
  `money` value also regenerates; if it is still bad on the last attempt, only
  that facet is dropped and counted in `IngestReport.invalid_facets_dropped`.
  Other bad optional facets, and any bad consensus facet, are dropped at once. A required subtype
  never takes a fallback. The extraction catalog lists each entity type's
  required facets from the registry (`entity_type_required_facets`), and the
  prompt tells the LLM to omit an entity whose required facet it cannot determine.
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
It is a required registry field and the only copy of the per-type specs. An
entity type can add facets under `node["entity:<entity_type>"]`, layered on
`node["entity"]` (a layer key overrides the base); only entity subtypes are
layered, and a layer cannot redeclare `entity_type`. Adding such a
declaration is a registry edit with no code change. The shipped registry
declares `entity:person` requiring `role` and `organization`, and
`entity:company` requiring `sector`, all `text`; ingest regenerates an
extraction that omits them, as for any required facet.

Code checks only a minimum (`facet_schema_problems`): each spec is
`{kind, required}` with a known kind, node keys are a node type or
`entity:<member>`, and entity `entity_type`, event `event_type`, view
`view_type`, theme `stage` and edge `basis` are required enums. Every `enum`
facet must have a vocabulary in `facet_vocabularies`. `NODE_FACET_SCHEMA` and
`EDGE_FACET_SCHEMA` in `vocab.py` are only the built-in registry's base schema.
In the shipped registry, event `event_date` and view `as_of` are dates, view
`target_price` is `money`; the other vocabulary facets are optional enums. Entity types are
company, person, institution, sector and region. Products stay in event and
view text and are not entities. A
`money` value is `{amount, currency[, qualifier]}` with a 3-letter currency and
`qualifier: at_least` for a target like `NT$3100+`. Magnitudes parse exactly
(`USD 1.45B` is 1,450,000,000). A bare number or a plain
`$` names no currency and is refused.

`facet_schema.relation.<RELATION>` layers facets on the base `edge` spec, the
way `entity:<type>` layers on `entity`. `EXPOSED_TO` requires `sentiment`;
`WORKS_AT.role`, `BUY.confidence`, `BUY.product_type`, `COMPETE.area` and
`OWNS.transaction_value` (money) are optional. A layer must name a registry
relation and cannot redeclare `basis`. Consensus flags stay free-form.

`OntologyDB.upsert_edge` and `update_edge` refuse endpoints outside the
relation's `from_types` and `to_types`. Ingest holds such an edge in
`pending_edges`; `audit` reports it in `pending_endpoint_issues`, and `repair`
promotes it once the registry allows those endpoints.

`metadata_max_length` declares the max length of node `name` (200) and
`summary` (1,000); `check_metadata` refuses longer text on write.

- `OntologyRegistry.check_facets(node_type, facets)` (node_type None for an
  edge) returns the facets coerced to their kind, or raises
  `FacetSchemaError` (a `ValueError`). Coercion is lossless only
  (`coerce_facet_value`): a numeric string becomes a number, a date stays the
  ISO string it was, and an enum, required or optional, is stored as its
  vocabulary member or refused.
- Facets the registry does not declare pass through unchanged.
- `drop_uncoercible_optional(node_type, facets)` is the ingest rule: it removes
  optional official facets that cannot be coerced, including optional enums
  outside their vocabulary, and leaves required ones for `check_facets` to
  refuse.
- `check_relation(relation)` refuses a relation the registry does not map;
  `upsert_edge` and `update_edge` call it. The pipeline holds such an
  extracted edge in `pending_edges` instead (see [storage.md](storage.md)),
  where `audit` suggests the relation and `repair` promotes the edge once the
  registry maps it.
- `create_minimal_registry()`, the built-in default, declares a base
  `facet_schema`, the shipped `facet_vocabularies` and the same metadata
  limits, so an `OntologyDB` opened without a registry still enforces a
  schema. A registry without `facet_vocabularies`, `facet_schema` or
  `metadata_max_length` is refused; code's copy is never filled in.
- `schema_stamp()` hashes `facet_vocabularies`, `facet_schema` and
  `metadata_max_length`. The database also records the applied version and
  its full official definition hash. See [storage.md](storage.md).

## Registry (`registry.py`)

`normalize_relation_name` is the one relation-name rule; `OntologyDB.upsert_edge`
and `update_edge` apply it on write.

`OntologyRegistry` holds canonical relations (with aliases, inverses, and
domain and range rules), core companies, house themes, facet aliases, the
official facet vocabularies (`facet_vocabularies`: per node type and for
edges, each vocabulary's members with definitions, aliases and fallback).
Pending suggestions are stored in a separate queue. Official edge facets are `sentiment` and `basis`
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
