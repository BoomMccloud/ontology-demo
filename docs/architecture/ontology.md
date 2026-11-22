# Ontology

The domain model and its vocabulary: what a node, an edge, and a facet are,
and which relation names are allowed. Everything else in the app reads or
writes these shapes. Neither file imports any other app module.

## Files

- `src/stock_ontology/models.py`: the shapes.
- `src/stock_ontology/registry.py` and `ontology_registry.json`: the vocabulary.

## Models (`models.py`)

- `Node` with `node_type` in `entity | event | view | theme`, plus `name`,
  `summary`, `aliases`, open `facets`, and `source_doc_id`.
- `Edge` with `from_id`, `to_id`, `relation`, and open `facets`.
- Sentiment vocabulary: `VALID_SENTIMENTS`, `normalize_sentiment`,
  `derive_sentiment_from_stance`, `resolve_item_sentiment`.
- LLM structured-output shapes used by ingestion: `ExtractedEntity`,
  `ExtractedEvent`, `ExtractedView`, `ExtractedTheme`, `ExtractedEdge`,
  `ExtractionResult`, `ConsensusSynthesis`, and `FacetKV`.

## Registry (`registry.py`)

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

`tests/test_registry_audit.py` covers the registry. The models are covered
through `tests/test_db.py`, `tests/test_pipeline.py`, and
`tests/test_relationships.py`.
