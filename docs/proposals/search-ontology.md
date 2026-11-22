---
proposal_id: "search-ontology"
state: FRAMED
witness: independent
candidate: "11825e6 + ledger rebase @ worktree/claude/search-ontology-proposal-f78e10"
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

Candidate: `11825e6 + ledger rebase @ worktree/claude/search-ontology-proposal-f78e10`

### Verified reality
- `uv run pytest -q` on the rebased tree before any change: 226 passed. Proves the suites judging this change start green; limit: measured once, on this worktree.
- `canonical-vocabulary` (ACCEPTED) and `ontology-search` (ACCEPTED) are merged on `main` at `11825e6`. Proves the Proposal's Build constraint ("does not start Build until canonical-vocabulary is merged") is met, and that search now lives in `src/stock_ontology/search.py`. `run_hybrid_search` no longer exists.
- `src/stock_ontology/vocab.py` — proves every closed set this needs exists as a `Vocabulary`: `ENTITY_TYPE`, `EVENT_TYPE`, `EVENT_STATUS`, `VIEW_TYPE`, `VIEW_STATUS`, `STANCE` (7 members), `SENTIMENT`, `SUPPORT_STRENGTH`, `CONVICTION`, `STAGE`. Also `SUBTYPE_FACET`, `SIGNAL_CATEGORY_ALIASES`, `SENTIMENT_FILTER_VALUES`, `parse_category_filter`, `parse_sentiment_filter` and `matches_signal_filter`. Limit: node types live in `models.NodeType` and `search.NODE_TYPES`, not in `vocab.py`.
- `vocab.py:388` `matches_signal_filter` — proves the category rule compares the bare stored subtype, so `consensus` matches both a consensus view and a theme at stage `consensus`. The agent's `query_entity_signals` and web `SearchFilters.matches` share this rule, and `tests/test_canonical_vocabulary.py::test_agent_and_web_signal_filters_return_identical_items` guards their agreement. Limit: the ambiguity only shows on web search, because the agent's signal query collects events and views only.
- `search.py:303` `SearchFilters` (`from_raw`, `matches`) — proves the accepted filters are `node_type`, `subtype`, `sentiment`, `stance`, `entity_id`, `date_from`, `date_to`, `source_file` and keyword mode, with no `status`, `support_strength`, `conviction` or `relation`. `agent.py:341` builds `SearchFilters.from_raw(node_type=...)` for `search_nodes`, so new fields that default to None leave the agent unchanged.
- `web/app.py:309` `search_page` and `app.py:360` `active_filters` — prove the page takes the same params and builds one active-filter chip per filter.
- `web/viewmodels.py:795` `build_search_filter_options` — proves options are still hand-kept: `DEFAULT_SUBTYPES_BY_TYPE` (`viewmodels.py:63`) and `CANONICAL_STANCES` (`viewmodels.py:70`, 12 stances, while `vocab.STANCE` has 7), merged by `_merge_ordered` with values observed in up to 5000 nodes. Entity options are DB instances, which is correct.
- `web/templates/partials/search_bar.html:16-22` — proves the `node_type` select is hardcoded. `search_bar.html:34-50` proves the subtype select is one flat value across four optgroups.
- `ontology_registry.json` `relations` (11 names) and `web/app.py:137` `_load_optional_registry` — prove relations are defined in the registry and that the web app loads it as optional.
- `db/storage.py:1580` `get_entity_connected_nodes` — proves the entity filter keeps only the best edge's facets per neighbor, not the relation.
- `sqlite3 -readonly ontology.db` census from canonical-vocabulary's Frame, unchanged by its 0-change `repair` — every stored enum value is canonical, and edge relations use 10 of the 11 registry names. Limit: one local DB.
- `locales/en.json` — has `enum.*` keys for every vocab member (guarded by `tests/test_i18n.py::test_every_vocab_member_has_an_enum_key_in_every_locale`) and `enum.relation.*` keys. New field labels are needed in all 6 locales.
- `tests/test_web.py:445` `test_web_nav_and_advanced_search_filters`, `tests/test_search.py:171` `test_filters_narrow_results_but_expansion_still_seeds_from_entity`, and `catalog.py` links — prove existing callers use bare values (`subtype=rumor`, `stance=cautious`). No test asserts the option lists.

### Final primary claim
- Every advanced-search select on `/search` (node type, subtype, status, sentiment, stance, support strength, conviction, relation) lists exactly the values the ontology defines: the `vocab.py` sets and the registry's relation names. Choosing an option returns only items whose stored value is that value in that group. A value stored in the DB but outside the vocabulary is never offered.

### Routing
- Witness: `independent`
- Why: the change extends `search.SearchFilters`, which the agent's `search_nodes` tool also uses, plus a storage read method and the web page. It crosses the storage, search and web components, though it writes nothing.
- Human-owned irreversible action: merging the branch.

### Decisive witness
- Layer: offline web integration tests through `TestClient` over a seeded temp DB with `FakeWebLLM`, plus `search_ontology` calls for filter semantics.
- Permanent owner: `tests/test_web.py`, next to `test_web_nav_and_advanced_search_filters`, and `tests/test_search.py` for `SearchFilters`.
- Witness: render `/search`, collect each select's option values, and assert each equals its `vocab.py` set (relation equals the registry's names) with nothing added from the DB. Use a fixture that stores an off-vocabulary stance and relation. Then assert `status=event:upcoming`, `support_strength=weak`, `conviction=high` and `relation=ABOUT` each return exactly the seeded matches, and that `subtype=theme:consensus` and `subtype=view:consensus` return disjoint sets.

### Guardrail claims
- Every URL accepted today returns the same results, including bare `subtype=rumor` (the cross-type rumor rule and category aliases), `stance`, `sentiment`, `entity_id`, dates, `source_file` and keyword mode.
- The agent's `search_nodes` and `query_entity_signals` return the same results as today, and the agent and web signal-filter parity test stays green with `vocab.matches_signal_filter` unchanged.
- With no registry file, `/search` still renders and works, and only the relation filter is hidden.

### Supporting obligations
- `build_search_filter_options` builds every enum option list from `vocab.py`, and the relation list from the loaded registry. Delete `DEFAULT_SUBTYPES_BY_TYPE`, `CANONICAL_STANCES` and `_merge_ordered`, and drop the observed-value scan except for entity options.
- Render the `node_type` select from `search.NODE_TYPES` instead of hardcoded options.
- Group-qualify the values of the subtype and status selects as `<node_type>:<value>`. `SearchFilters.from_raw` parses a qualified value into a node-type restriction plus the bare value, and passes the bare value to `matches_signal_filter` unchanged. A bare value keeps today's behavior. Unit-test the parser in `tests/test_search.py`.
- Add `status`, `support_strength`, `conviction` and `relation` to `SearchFilters` (default None) and `search_page`, each with an active-filter chip. `support_strength` and `conviction` match view facets. Relation matches a result with at least one incident edge of that relation; with an entity selected, the edge must connect the result to that entity. Add a read method in `OntologyDB`, or a read-only extension of `get_entity_connected_nodes`, to return relations per neighbor.
- Add the new field labels to all 6 `locales/*.json`.

### Allowed scope
- Reuse: `search.SearchFilters` and `search_ontology` (extended, not replaced), `build_search_filter_options` (rewritten in place), `vocab.py`'s sets and parse functions, `registry.load_registry` via `_load_optional_registry`, the existing `enum.*` locale keys with `translate_enum`/`translate_subtype`, and the fixture patterns in `test_web_nav_and_advanced_search_filters` and `tests/test_search.py`.
- Cheaper alternative: option (a), generating today's filters from `vocab.py` and adding none. Rejected because the human chose (b) at approval. Within (b), Frame takes the cheapest semantics: relation matches any incident edge (scoped to the selected entity when one is set), and new filters are single-value selects with no multi-select.
- Include: `search.py`, `web/viewmodels.py`, `web/app.py`, `web/templates/partials/search_bar.html`, `db/storage.py` (one read method), `locales/*.json` (new `search.*` labels only), `tests/test_web.py`, `tests/test_search.py`, `docs/architecture/search.md` and `web.md` (where options come from).
- Exclude/protect: `vocab.py` contents including `matches_signal_filter`, `models.py`, ingestion, `repair`, `ontology_registry.json` contents and schema, the agent and its tool schema, search ranking, expansion, note grep and vector search, CSS class renames, the `/ontology` page.

### Invariants changed
- None. No README entry or test states today's option lists. `DEFAULT_SUBTYPES_BY_TYPE` and `CANONICAL_STANCES` are code rules this change removes. Removing `CANONICAL_STANCES` drops `outperform`, `overweight`, `underperform`, `underweight` and `unknown` from the stance select, as canonical-vocabulary decision 3 already set.

### Decisions required
- None. Nothing in the approved Proposal is contradicted by `main`. Its "Why now" and Build constraint referred to canonical-vocabulary being unbuilt. That is now met, and the Proposal text is left as approved.

## Proof

<!-- Replaced only by proposal-prove. Independent route: Proof must be authored in a
context that did not write this Frame, before Build. -->

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
