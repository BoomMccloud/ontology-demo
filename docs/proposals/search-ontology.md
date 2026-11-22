---
proposal_id: "search-ontology"
state: FRAMED
witness: builder
candidate: "5aceabc @ worktree/claude/search-ontology-proposal-f78e10"
---

# Proposal: Search driven by the ontology

## Proposal

### Intent

"Our new ontology should also be used to power search:
http://127.0.0.1:8000/search, in particular the advanced search capabilities
should programmatically match our ontology."

### Tentative primary claim

The advanced search options on `/search` programmatically match the ontology,
so a user can filter by exactly the values the ontology defines.

### Why now

The ontology's vocabulary is being made canonical by the separate
`canonical-vocabulary` proposal, and the requester wants search to follow it.

### Known constraints

- This is its own proposal, separate from `canonical-vocabulary`.
- It builds on `canonical-vocabulary`, which is not yet built, and does not
  start Build until that proposal is merged.

### Non-goals

None stated.

### Open choices

- Which filters advanced search offers:
  (a) keep today's advanced filters (type, subtype, sentiment, stance, entity,
  dates, source file) with their options generated from the ontology, or
  (b) also add a filter for every other value set the ontology defines, such as
  status, support strength, conviction, and relation.

  Resolved by the human at approval (2026-11-22): (b), add every enum.

## Frame

Candidate: `5aceabc @ worktree/claude/search-ontology-proposal-f78e10`

### Verified reality
- `uv run pytest -q` before any change: 145 passed. Proves the suites judging this change start green; limit: measured on `5aceabc`, before `canonical-vocabulary` lands. Build must re-measure on the merged tree.
- `docs/proposals/canonical-vocabulary.md` (main checkout, `state: FRAMED`, three open decisions) — proves the dependency. That proposal adds `src/stock_ontology/vocab.py` in the `ontology` layer as the one closed set per enum, moves `SIGNAL_CATEGORY_ALIASES` there, replaces the filter predicate in `run_hybrid_search` with a shared function, and leaves `/search` option generation to this proposal. Limit: `vocab.py` does not exist yet, so its API is assumed, not inspected. Its decision 2 (which enums are covered) and decision 3 (7 or 12 stances) decide which values this proposal's options show.
- `web/viewmodels.py:507` `build_search_filter_options` — proves today's options are hand-kept defaults (`DEFAULT_SUBTYPES_BY_TYPE` and `CANONICAL_STANCES` at `viewmodels.py:52-70`, `VALID_SENTIMENTS`) merged by `_merge_ordered` with values observed in up to 5000 nodes. Any off-vocabulary stored value becomes an option. Entity options are DB instances, which is correct, since entities are data, not vocabulary.
- `web/templates/partials/search_bar.html:16-22` — proves the `node_type` select is hardcoded. `search_bar.html:31-50` proves the subtype select is one flat value across four optgroups.
- `viewmodels.py:469` `_node_subtype` and `viewmodels.py:660-675` — prove subtype matching compares a bare string, so `consensus` (a `view_type` and a theme `stage`) matches both groups. Limit: read from code, not reproduced in the UI.
- `viewmodels.py:614` `run_hybrid_search` and `web/app.py:307-429` `search_page` — prove the accepted filters are `node_type`, `subtype`, `sentiment`, `stance`, `entity_id`, `date_from`, `date_to`, `source_file`, `search_mode`. There is no `status`, `support_strength`, `conviction` or `relation` filter. `app.py:363-410` builds the active-filter chips, one per filter.
- `models.py:158-245` — proves the ontology's other enums and where they live: event `status` (occurred, upcoming, rumored), view `support_strength` (strong, moderate, weak), view `conviction` (high, medium, low). Consensus views also carry `status` (active, superseded). Limit: these are `Field` descriptions today; `canonical-vocabulary` makes them closed sets.
- `ontology_registry.json` `relations` (11 names: ABOUT, AUTHORED_BY, SUPPORTS, CONTRADICTS, SUPERSEDES, RELATES_TO, BUY, COMPETE, OWNS, WORKS_AT, EXPOSED_TO) and `web/app.py:136` `_load_optional_registry` — prove relations are defined in the registry, not in code, and that the web app can already load it but treats it as optional.
- `storage.py:1718` `get_entity_connected_nodes` — proves the entity filter walks incident edges and sees each edge's `relation`, but keeps only the best edge's facets per neighbor, not the relation.
- `sqlite3 -readonly ontology.db` census (main checkout) — event status: occurred 41, upcoming 1. View status: active 22, unset 34. View support_strength and conviction: only canonical values. Edge relations: only the 10 registry names in use (SUPERSEDES unused). Limit: one local DB.
- `locales/en.json` — has `enum.status.*`, `enum.support_strength.*`, `enum.conviction.*`, `enum.node_type.*` and `enum.relation.*` keys for every canonical value, so option labels need no new enum keys. New field labels (`search.status_label` and friends) are needed in all 6 locales.
- `tests/test_web.py:443` `test_web_nav_and_advanced_search_filters` and `catalog.py:906` — prove existing callers use bare values (`subtype=rumor`, `stance=cautious`, `source_file=...`). No test asserts the option lists.

### Final primary claim
- Every advanced-search select on `/search` (node type, subtype, status, sentiment, stance, support strength, conviction, relation) lists exactly the values the ontology defines: the enum sets in `vocab.py` and the relation names in the registry. Choosing an option returns only items whose stored value is that value in that group. A value stored in the DB but outside the vocabulary is never offered.

### Routing
- Witness: `builder`
- Why: a read-only web surface. It changes which options render and how query params filter, but writes nothing, crosses no service boundary, and is reversible by revert.
- Human-owned irreversible action: merging the branch.

### Decisive witness
- Layer: offline web integration tests through `TestClient` over a seeded temp DB with `FakeWebLLM`.
- Permanent owner: `tests/test_web.py`, next to `test_web_nav_and_advanced_search_filters`.
- Witness: render `/search`, collect each select's option values, and assert each equals its `vocab.py` set (relation equals the registry's names) with nothing added from the DB, using a fixture that stores an off-vocabulary stance and relation. Then assert `status=event:upcoming`, `support_strength=weak`, `conviction=high` and `relation=ABOUT` each return exactly the seeded matches, and that `subtype=theme:consensus` and `subtype=view:consensus` return disjoint sets.

### Guardrail claims
- Every URL accepted today returns the same results, including bare `subtype=rumor` (the cross-type rumor rule and category aliases), `stance`, `sentiment`, `entity_id`, dates, `source_file`, `search_mode`, and the `catalog.py:906` link.
- `/search` still opens the DB read-only and the agent's `query_entity_signals` behavior is unchanged.
- With no registry file, `/search` still renders and works; only the relation filter is hidden.

### Supporting obligations
- `build_search_filter_options` builds every enum option list from `vocab.py`, and the relation list from the loaded registry. Delete `DEFAULT_SUBTYPES_BY_TYPE`, `CANONICAL_STANCES` and `_merge_ordered`, and drop the observed-value scan except for entity options.
- Render the `node_type` select from the vocabulary's node types instead of hardcoded options.
- Group-qualify the values of the subtype and status selects as `<node_type>:<value>`. `run_hybrid_search` accepts a qualified value (match that node type and value) or a bare value (today's behavior). Unit-test the parser.
- Add `status`, `support_strength`, `conviction` and `relation` params to `search_page` and `run_hybrid_search`, each with an active-filter chip. `support_strength` and `conviction` match view facets. Relation matches a result with at least one incident edge of that relation; with an entity selected, the edge must connect the result to that entity. Extend `get_entity_connected_nodes` or add a read method in `OntologyDB` to return relations per neighbor.
- Add the new field labels to all 6 `locales/*.json`.
- Before Build, re-verify every citation above against the merged `canonical-vocabulary` tree. If `vocab.py` lacks a set this needs (for example `conviction`, if decision 2 excludes it), rerun Frame rather than adding the set here.

### Allowed scope
- Reuse: `build_search_filter_options` and `run_hybrid_search` (extended, not replaced), the shared signal-filter function and `vocab.py` from `canonical-vocabulary`, `registry.load_registry` via `_load_optional_registry`, existing `enum.*` locale keys and `translate_enum`/`translate_subtype`, and `test_web_nav_and_advanced_search_filters`'s fixture pattern.
- Cheaper alternative: option (a), generating today's filters from `vocab.py` and adding none. Rejected because the human chose (b) at approval. Within (b), Frame took the cheapest semantics on this `builder` route: relation matches any incident edge (scoped to the selected entity when one is set), and new filters are single-value selects with no multi-select.
- Include: `web/viewmodels.py`, `web/app.py`, `web/templates/partials/search_bar.html`, `db/storage.py` (one read method or a read-only extension of `get_entity_connected_nodes`), `locales/*.json` (new `search.*` labels only), `tests/test_web.py`, `docs/architecture/web.md` (one line on where options come from).
- Exclude/protect: `vocab.py` contents, `models.py`, ingestion, `repair`, `ontology_registry.json` contents and schema, the agent and its tool schema, the shared signal-filter function's rules, hybrid ranking and vector search, CSS class renames, the `/ontology` page.

### Invariants changed
- None. No README entry or test states today's option lists. `DEFAULT_SUBTYPES_BY_TYPE` and `CANONICAL_STANCES` are code rules this change removes.

### Decisions required
- None.

## Proof

Builder route. The witness is builder-owned and deferred to Build. Build does not
start until `canonical-vocabulary` is merged (Proposal constraint).

## Build

<!-- Replaced only by proposal-build. Reference changed paths, protected witnesses,
exact GREEN command(s), concise result, candidate identity, and deviations. -->

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
