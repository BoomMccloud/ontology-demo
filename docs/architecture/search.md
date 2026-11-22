# Search

One entity-first search over the ontology and the raw research notes. The web
search page and the agent's `search_nodes` tool both call it, so they rank the
same way. It only reads.

## Files

- `src/stock_ontology/search.py`

## How it works

`search_ontology(db, llm, query, filters=..., data_dir=..., limit=...)` returns
`SearchResults`: a `best_match`, then `entities`, `related`, and `signals`
sections, then note `passages`. `ranked()` flattens them best first.

1. Entities first. An exact name or alias match (`find_by_name_or_alias`) is
   the best match, then `keyword_search`.
2. Expansion. From the best match and other name or alias matches, one hop
   through `get_incident_edges`. Relations are labeled with their registry
   canonical name. Edges are never results.
3. Semantic. `vector_search` on the query embedding, skipped in keyword mode
   or when the embedding provider fails. A hit with no positive cosine
   similarity is dropped.
4. Notes. `grep_notes` treats the words as a literal, case-insensitive string,
   walks only supported, non-hidden files under `data_dir` (never through a
   link that leaves it), and caps passages per file and in total. Each search
   reads at most `MAX_NOTE_FILES` files and `MAX_GREP_BYTES` bytes;
   `scan_notes` reports when that budget cut the walk short, and the search
   page and the agent's `search_notes` say so. A passage from the source note
   of a listed event or view becomes that item's `note_line` instead of a
   second entry. Both link to the raw note at that line
   (`/catalog?file=...&format=raw#L<n>`).

Each result has a `match_reason`: `name`, `alias`, `relationship`, `note`
(the word is in the item's extracted text or a note line), or `semantic`.
Filter-only listings, with no search word, use `filter`.

Ranking is a score per reason, plus a bounded recency term. `parse_period`
reads an explicit quarter, fiscal year, month, or year from the words, with no
LLM call. Items dated outside that period are dropped and items inside it are
boosted. Fiscal periods are read as calendar periods.

`SearchFilters.from_raw(...)` carries the advanced-search filters. Node filters
narrow what is shown, not which entity seeds the expansion. Any node filter
other than the source note leaves note passages out; a source-note filter
narrows them.

The filters are node type, subtype, status, sentiment, stance, support
strength, conviction, relation, connected entity, date range, source note, and
keyword mode. A subtype or status value may be group-qualified as
`<node_type>:<value>` (`theme:consensus`, `event:upcoming`); `from_raw` splits
it into a node-type restriction and the bare value, which goes to
`vocab.matches_signal_filter` unchanged. A bare value keeps the cross-type rule,
and an unknown prefix is kept whole, so it matches nothing. A relation filter
keeps items with at least one incident edge of that relation, read through
`OntologyDB.get_relation_node_ids`; with an entity selected, the edge must join
the item to that entity.

`resolve_safe_note_path` lives here so the web catalog and the grep share one
set of path rules.

## Depends on

[storage.md](storage.md) (read-only), [ontology.md](ontology.md),
[llm.md](llm.md) (embeddings), and config from [shared.md](shared.md).

## Used by

The agent (`search_nodes`, `search_notes`) and the web app (`/search`, the
notes catalog).

## Tests

`tests/test_search.py`, plus the search cases at the end of
`tests/test_web.py` and `tests/test_agent.py`.
