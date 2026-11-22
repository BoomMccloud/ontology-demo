---
proposal_id: "search-ontology"
state: BUILT
witness: independent
candidate: "6f7dbc3 @ worktree/claude/search-ontology-proposal-f78e10"
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

Candidate: `1b4bd7a` (branch `claude/search-ontology-proposal-f78e10`), plus `tests/test_search_ontology_options.py` with blob `2554d6126bf0a03883e296a289c4b6433837ca85`.

**Protected witness**
- Every advanced-search select lists exactly the ontology's values. Witness: `tests/test_search_ontology_options.py` / `test_search_select_lists_exactly_the_ontology_values[node_type|subtype|status|sentiment|stance|support_strength|conviction|relation]`
  - Defect and boundary: `build_search_filter_options` uses hand-kept lists merged with values observed in the DB. Subtype values are unqualified, and there are no status, support_strength, conviction or relation selects. Boundary: the web page building its options from search and storage.
  - Assertion: GET `/search` over a seeded temp DB that stores off-vocabulary values (event_type `webinar`, stance `outperform`, relation `FROBNICATES`). Each select's non-empty option values must equal the vocab set exactly: `node_type` = `search.NODE_TYPES`; `subtype` = `<nt>:<member>` for each `SUBTYPE_FACET` vocab; `status` = `event:*` and `view:*` from `EVENT_STATUS` and `VIEW_STATUS`; `sentiment` = `SENTIMENT_FILTER_VALUES`; `stance` = `STANCE.members`; `support_strength` = `SUPPORT_STRENGTH.members`; `conviction` = `CONVICTION.members`; `relation` = the relation names from `load_registry(ontology_registry.json)`.
  - Proves: the options come from the ontology, and DB values outside it are never offered. Limit: checks option values only, not labels, ordering or optgroup grouping. `[node_type]` and `[sentiment]` are already green, so they guard the claim but are not proof.
- Choosing a new filter returns exactly the matching items. Witness: `tests/test_search_ontology_options.py` / `test_new_ontology_filters_return_exactly_the_matching_items[status-event|status-view|support_strength|conviction|relation-any|relation-entity]`
  - Defect and boundary: `search_page` and `SearchFilters` silently ignore the `status`, `support_strength`, `conviction` and `relation` params. Boundary: URL → search → storage.
  - Assertion: exact `data-result-id` sets. `status=event:upcoming` → {evt_up}. `status=view:active` → {vw_cons}. `support_strength=weak` → {vw_weak}. `conviction=high` → {vw_strong}. `node_type=event&relation=ABOUT` → {evt_up, evt_occ}. `entity_id=ent_aapl&relation=ABOUT` → {evt_up, vw_weak}, which excludes evt_occ (ABOUT to QCOM, RELATES_TO to AAPL), so the relation is scoped to the selected entity.
  - Limit: filter-only searches (empty q), single-value filters, no combinations beyond those listed.
- A group-qualified subtype separates theme stage from view type. Witness: `tests/test_search_ontology_options.py` / `test_group_qualified_subtype_separates_theme_stage_from_view_type` (web) and `test_search_ontology_parses_group_qualified_subtype` (`search_ontology` plus `SearchFilters.from_raw`)
  - Defect and boundary: `from_raw` passes `theme:consensus` through as a literal category that matches nothing. This is shared search code that the web page uses and the agent's `search_nodes` reaches.
  - Assertion: on the web, `subtype=theme:consensus` → {thm_cons} and `subtype=view:consensus` → {vw_cons}. Through `search_ontology`, `from_raw(subtype="theme:consensus")` → {thm_cons}, `from_raw(subtype="view:rumor")` → {vw_weak} (excludes the rumored event), and `from_raw(subtype="event:news")` → {evt_occ, evt_rum}.
  - Proves: the qualified value restricts the node type and passes the bare value to the existing rule. Limit: malformed qualifiers such as `foo:bar` are not tested.
- Guardrail, existing URLs unchanged. Witness: `tests/test_search_ontology_options.py` / `test_bare_subtype_and_existing_filters_keep_todays_results`
  - Assertion: through `from_raw`, bare `subtype=rumor` and `subtype=rumors` → {vw_weak, evt_rum}, and bare `consensus` → {vw_cons, thm_cons}. On the web, `subtype=rumor`, `stance=cautious`, `sentiment=negative` (→ {evt_occ, vw_weak}), node_type plus date range, `source_file=QCOM/` and keyword mode `q=Rumored` each return their exact current sets.
  - Limit: green today by design, since a guardrail cannot be RED. Agent and web parity stays guarded by `tests/test_canonical_vocabulary.py::test_agent_and_web_signal_filters_return_identical_items`.
- Guardrail, no-registry rendering. Witness: `tests/test_search_ontology_options.py` / `test_search_without_registry_hides_only_the_relation_filter`
  - Assertion: with `registry_path` pointing at a missing file, `/search` returns 200 with no `relation` select. The other seven selects equal their vocab sets, and `support_strength=weak` → {vw_weak}.
  - Limit: a malformed registry file is not covered.
- Protected paths: `tests/test_search_ontology_options.py`.
- Protected revision: blob `2554d6126bf0a03883e296a289c4b6433837ca85`, committed with this ledger update. `tests/test_web.py` and `tests/test_search.py` are not protected. Build may add supporting tests there but must not modify existing tests.
- The file reuses existing helpers via `from test_web import DIM, FakeWebLLM, _unit_vec`, as `tests/test_web_navigation.py` does.

**Red evidence**
- `uv run pytest tests/test_search_ontology_options.py -v` → 15 failed, 3 passed.
  - `[subtype]`: bare values such as `company` and `catalyst` are offered instead of `entity:company`.
  - `[status]`, `[support_strength]`, `[conviction]`, `[relation]`: select absent.
  - `[stance]`: extra `outperform`, `overweight`, `underperform`, `underweight` and `unknown`.
  - `[status-event]`, `[status-view]`, `[support_strength]`, `[conviction]` filters: `set()`, because the param is ignored and the page shows no results.
  - `[relation-any]`: extra evt_off and evt_rum. `[relation-entity]`: extra ent_aapl, evt_occ, vw_strong and thm_acc.
  - Group-qualified web and search tests: `set()` instead of {thm_cons}.
  - No-registry test: fails on the unqualified `subtype` options.
  - PASSED: `[node_type]` and `[sentiment]` option checks, and the existing-filters guardrail.
- During authoring, first attempts failed at setup (a `tests.` import path and a missing `Node.summary`), fixed in the test file only. One guardrail expectation was corrected to today's behavior: `sentiment=negative` already returns the cautious rumor view.
- `uv run pytest -q --deselect tests/test_search_ontology_options.py` → 226 passed. Full run: 15 failed, 229 passed.
- The primary claim has no proof until those 15 are GREEN after Build with the protected blob unchanged.

**Supporting test plan**
- Parser for qualified subtype and status values, bare-value passthrough, and an unknown node-type prefix → Build: `tests/test_search.py`. Catches `from_raw` mis-splitting values or dropping the node-type restriction.
- Storage read method returning relations per neighbor → Build: `tests/test_search.py` or `tests/test_db.py`. Catches relation loss when the best edge per neighbor is collapsed in `get_entity_connected_nodes`.
- Active-filter chips and labels for the 4 new filters in all 6 locales → Build: `tests/test_i18n.py` or `tests/test_web.py`. Catches missing `search.*` keys.

## Build

Candidate: commit `6f7dbc3` (tree `82439dd6357e906cd9b5ebf4e213d3e08b7c6e97`) on branch `claude/search-ontology-proposal-f78e10`, parent `8165fce`. The protected witness `tests/test_search_ontology_options.py` is unchanged (blob `2554d6126bf0a03883e296a289c4b6433837ca85`).

### Files changed

- `src/stock_ontology/search.py`: adds `split_qualified_value`. `SearchFilters` gains `subtype_node_type`, `status`, `status_node_type`, `support_strength`, `conviction` and `relation`, all defaulting to None. `from_raw` splits `<node_type>:<value>` into a node-type restriction plus the bare value. The bare subtype still goes through `parse_category_filter` and then the unchanged `matches_signal_filter`. An unknown prefix is kept whole, so it matches nothing. `narrows_nodes` includes the new filters. `matches` takes an optional `relation_ids`, and a relation filter without them matches nothing. `search_ontology` and `_filter_only` compute `relation_ids` once per search. Ranking, expansion, note grep and vector search are untouched.
- `src/stock_ontology/db/storage.py`: one new read method, `get_relation_node_ids(relation, *, entity_id=None)`, returning the IDs of nodes with an incident edge of that relation. With an entity, only neighbors joined to it by such an edge. `get_entity_connected_nodes` is unchanged.
- `src/stock_ontology/web/viewmodels.py`: `build_search_filter_options(db, registry=None)` rewritten in place. Node types from `NODE_TYPES`; subtypes, statuses, sentiments, stances, support strengths and convictions from `vocab.py`; relations from the registry, or `[]` without one. Only entity options still come from the DB. Deleted `DEFAULT_SUBTYPES_BY_TYPE`, `CANONICAL_STANCES`, `_merge_ordered`, the observed-value scan and the unused `VALID_SENTIMENTS` import.
- `src/stock_ontology/web/app.py`: `search_page` accepts `status`, `support_strength`, `conviction` and `relation`, passes the optional registry to the options builder, and adds an active-filter chip per new filter. The subtype chip translates qualified values.
- `src/stock_ontology/web/templates/partials/search_bar.html`: `node_type` select rendered from options. Qualified subtype values. New status (event and view optgroups), support strength and conviction selects, and a relation select shown only when relations exist. The sentiment fallback list is removed. No CSS classes added or renamed.
- `src/stock_ontology/locales/{en,es,fr,ja,ko,zh}.json`: 14 new `search.*` keys each. Additions only.
- `tests/test_search.py`: new `test_from_raw_parses_group_qualified_subtype_and_status_values` and `test_get_relation_node_ids_keeps_every_relation_per_neighbor`. Additions only.
- `tests/test_web.py`: new `test_search_new_filter_chips_and_labels_in_every_locale`, parametrized over 6 locales. Additions only.
- `docs/architecture/search.md`, `docs/architecture/web.md`: the new filters, qualified values, relation read, and where options come from.
- `README.md`: one Web UI Constraints entry (build `/search` enum options from `vocab.py` and the registry only, and qualify subtype and status values), with **Why:** and **Guarded by:** `tests/test_search_ontology_options.py`.

### Unit evidence

- Supporting tests run against `8165fce` in a temporary detached worktree: RED. `tests/test_search.py` fails at collection on the missing `split_qualified_value`, and `-k new_filter_chips` gives 6 failed, one per locale.
- The same selection on the candidate: GREEN, 8 passed.
- The supporting tests were written after the implementation, so RED comes from the baseline worktree, not a test-first sequence.

### Green evidence

- Decisive witness: `uv run pytest tests/test_search_ontology_options.py -v` → 18 passed. All 15 Proof REDs are GREEN.
- Gate: `uv run pytest -q` → 252 passed (orchestrator re-ran and confirmed). Includes `tests/test_canonical_vocabulary.py::test_agent_and_web_signal_filters_return_identical_items` and `tests/test_architecture.py`.
- `uv run ruff check src/stock_ontology/web/viewmodels.py src/stock_ontology/web/app.py src/stock_ontology/db/storage.py`: clean. `search.py`, `tests/test_search.py` and `tests/test_web.py` have 4 existing findings on untouched lines (`search.py:105` TRY300, `test_search.py:45`, `test_web.py:1891,1894` TRY003); the HEAD version of `search.py` reproduces its finding.
- `git hash-object tests/test_search_ontology_options.py` → `2554d6126bf0a03883e296a289c4b6433837ca85`, matching Proof. The orchestrator confirmed no diff since `8165fce` in that file, `vocab.py`, `agent.py`, `models.py` or `ontology_registry.json`.

### Intervention record

- None. Local offline build; no deploy or live data.

### Deviations

- None. Every modified path is on Frame's Include list, plus the `README.md` constraint entry the skill allows on every route.
- For Audit: bare legacy URLs such as `subtype=rumor` still filter as today, but no subtype option shows as selected for them, because options are now qualified.

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
