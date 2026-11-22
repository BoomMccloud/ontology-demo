---
proposal_id: "canonical-vocabulary"
state: ACCEPTED
witness: independent
candidate: "5aceabc + uncommitted working tree @ home-page-tables (main checkout)"
---

# Proposal: Canonical vocabulary for enums, relations and signal filters

## Proposal

### Intent

Clean up the ontology so each vocabulary has one official source and one rule,
applied when data is written, instead of readers patching values up on the way
out. Three cleanup items ship together:

- Item 7. Normalize enum facets on write, with a repair step for old rows.
  `entity_type`, `event_type`, `status` and `stance` are stored in whatever case
  the LLM returned. About 30 read sites re-lowercase them, and they don't all
  agree. Wanted: stored lowercase once, readers compare directly, and the
  template `| lower` filters go away.
- Item 8. One relation-name normalizer. `upsert_edge` and the registry use
  slightly different rules, `update_edge` uses none, and readers re-uppercase
  defensively. Wanted: one rule at the write boundary, and no read-side fixups.
- Item 9. One copy of the signal filter rules. The rumor, unclassified and
  category rules are written twice, in storage for the agent and in the view
  model for web search, so the two can drift. Wanted: one shared function, so
  the agent and web search always agree.

Anything outside the official vocabulary isn't considered canon.

### Tentative primary claim

Every enum value and relation name stored in the ontology is in its one
canonical form, and the agent and web search return the same items for the same
signal filter.

### Why now

None stated.

### Known constraints

- All three items go in one proposal.
- `ontology_registry.json` stays the data registry (relations, companies,
  themes, aliases, suggestions). The closed enum vocabularies live in code, not
  in that file.
- Old rows already in the DB get fixed by a repair step.

### Non-goals

- Coding best practices and general word definitions are not part of a
  registry.
- Making `/search` advanced search options match the ontology. That is its own
  proposal, `search-ontology`.

### Open choices

- What happens when the LLM returns a value that isn't in the vocabulary even
  after case and alias cleanup: reject the item, store a fallback value, or keep
  it and flag it in `audit`.
- Whether `view_type` and `sentiment` are covered along with the four enums
  item 7 names.

## Frame

Candidate: `5aceabc + uncommitted working tree @ home-page-tables (main checkout)`

### Verified reality
- `uv run pytest -q` before any change: 147 passed. Proves the suites judging this change start green; limit: run on the dirty working tree, not on clean `5aceabc`.
- `sqlite3 -readonly ontology.db` facet census — proves every stored `entity_type`, `event_type`, `status`, `view_type`, `stance`, `sentiment` (node and edge) and `stage` value is already lowercase, and 0 edges have a non-canonical relation name; limit: one local DB only. The repair step is a guarantee for other DBs and future drift, not a fix for live damage here.
- `models.py:158-245` — proves `entity_type`, `event_type`, `status`, `view_type`, `stance`, `support_strength` and `stage` are plain `str` fields whose vocabulary exists only in `Field(description=...)`. Only `Sentiment` (`models.py:12`, `VALID_SENTIMENTS`, `normalize_sentiment`) is a real closed type; limit: says nothing about write-path coercion.
- The same vocabularies are copied by hand into `llm/prompts.py:16-26`, the agent tool schema `agent.py:104-138`, `web/viewmodels.py:52-70` (`DEFAULT_SUBTYPES_BY_TYPE`, `CANONICAL_STANCES`), `partials/search_bar.html:58` and the `enum.<group>.<value>` keys in `locales/*.json`. Proves the drift item 7 describes; limit: copies were found by grep, not exhaustively.
- The copies already disagree. Consensus-view retirement writes `status: "stale"` in `pipeline.py:505` but `"superseded"` in `db/storage.py:384`, and only `superseded` has a locale key and a reader (`storage.py:1003`). `CANONICAL_STANCES` and the locales list 12 stances, including `outperform`, `overweight`, `underperform` and `underweight`, which the prompt never offers. The prompt offers 7.
- `grep -nE '\| ?lower'` over templates — 25 badge sites lowercase `stance`, `sentiment`, `stage` and `support_strength`. `i18n.py:256` lowercases every non-relation enum before lookup. Limit: the `| lower` filters cover four enums, not the four item 7 names, so removing them needs `sentiment`, `stage` and `support_strength` normalized too.
- `db/storage.py:216` (`upsert_edge`) normalizes with `strip().upper().replace(" ", "_")`, while `registry.py:22` `normalize_relation_name` also maps `-` and collapses `_+`. `storage.py:323` `update_edge` writes `relation` raw. Read-side `.upper()` appears at `storage.py:982,1006,1183,1383,1400,1671`, `viewmodels.py:419`, `catalog.py:629,707` and `i18n.py:326`. Proves item 8.
- `storage.py:1221` `query_entity_signals` (agent) and `viewmodels.py:614` `run_hybrid_search` (web) each re-implement filter-input parsing (`unknown`/`none` to `unclassified`, `SIGNAL_CATEGORY_ALIASES` from `db/schema.py:20`) and the rumor rule (view with `view_type == rumor`, or event with `status == rumored` or subtype `rumor`). Proves item 9; limit: the two also differ in scoping (agent excludes `AUTHORED_BY` links and non-active consensus views), which is per-surface behavior, not a filter rule.
- `viewmodels.py:507` `build_search_filter_options` — proves the `/search` advanced options are not driven by the ontology. They merge the hand-kept defaults with whatever values are observed in the DB (`_merge_ordered`), so any off-vocabulary stored value becomes a dropdown option. The `node_type` select is hardcoded in `search_bar.html:16-22`. The advanced form offers subtype, sentiment, stance, entity, date range, source file and mode, and no filter for `status`, `support_strength`, `conviction` or relation.
- `search_bar.html:36-50` and `viewmodels.py:469` `_node_subtype` — prove the subtype filter is one flat string across four groups. `consensus` exists both as a view type and as a theme stage, so choosing either "consensus" option matches consensus views and consensus-stage themes alike. Limit: inferred from code, not reproduced in the UI. Both search findings are handed to `search-ontology`; this proposal only keeps those readers working.
- `tests/test_architecture.py` `MODULE_OF`/`ALLOWED` — proves a new top-level module must be mapped to a layer, and that `ontology` (`models`, `registry`) is the layer both `storage` and `web` may import with no dependencies of its own.
- `repair.py:47` `repair_ontology` with `RepairReport` counters and `tests/test_repair.py:156` `test_repair_is_idempotent` — proves an existing writer and idempotence test a facet-normalization step can join.

### Final primary claim
- After ingest or `repair`, every stored enum facet value is one canonical lowercase member of its vocabulary, and every stored relation name equals `normalize_relation_name` output. The agent's `query_entity_signals` and web `run_hybrid_search` return the same matching items for the same sentiment and category filter over the same candidate set. Out-of-vocabulary values are handled per decision 1: ingest stores the member's fallback, and `repair` leaves the lowercased raw value in place and `audit` reports it.

### Routing
- Witness: `independent`
- Why: write-path coercion and the new `repair` step rewrite stored ontology rows, and coercion can change or drop LLM-extracted values.
- Human-owned irreversible action: running `stock-ontology repair` against the real `ontology.db`, and merging the branch.

### Decisive witness
- Layer: offline integration tests through public write and read APIs with fake LLM clients.
- Permanent owner: `tests/test_pipeline.py` (ingest write path), `tests/test_repair.py` (old-row repair), and a parity test in `tests/test_agent.py` or `tests/test_web.py` that runs both filters over one fixture DB.
- Witness: ingest extraction returning mixed-case and alias values (`"Bullish"`, `"Rumour"`, `"competes-with"`), plus a DB seeded with legacy mixed-case rows and then repaired. Assert stored values equal the canonical form and that both filters return identical ids. Assert an out-of-vocabulary value at ingest is stored as that enum's fallback, and an out-of-vocabulary legacy row survives `repair` lowercased and shows up in `run_ontology_audit`.

### Guardrail claims
- Ingesting an extraction whose values are already canonical stores the same rows as today, and `repair` on an already-clean DB reports 0 facet changes (idempotent).
- Web badges, `t_enum` labels, search options and search results are unchanged for every value present in the current DB census.
- No reader still lowercases or uppercases an enum or relation it reads from the DB. Free-text user filter input (URL params, agent tool args) may still be normalized at the input boundary, once, by the shared function.

### Supporting obligations
- Add `src/stock_ontology/vocab.py` in the `ontology` layer. Map it in `tests/test_architecture.py` `MODULE_OF` and `docs/architecture/README.md`. It holds one closed set per enum, keyed by node type, with a one-line definition per member, an alias map, and `coerce_<enum>(raw)`. Unit-test each coercer.
- Type the `models.py` extraction fields with the vocab `Literal`s, using a `before` validator that coerces, so Pydantic rejects or replaces per decision 1.
- Generate the vocab text in `llm/prompts.py` and the `enum` lists in the `agent.py` tool schema from `vocab.py`. Add a test that every vocab member has a `locales/*.json` `enum.` key. Leave `/search` option generation (`build_search_filter_options`, `DEFAULT_SUBTYPES_BY_TYPE`, `CANONICAL_STANCES`) to `search-ontology`, apart from removing its read-side lowercasing.
- Retire consensus views with one status value. `superseded` is the cheaper choice because it already has a locale key and a reader. Change `pipeline.py:505` to it, and have repair map stored `stale` to it.
- `upsert_edge` and `update_edge` call `registry.normalize_relation_name`. Remove the read-side `.upper()` calls listed above.
- Move the rumor/category/sentiment predicate and the filter-input parsing into one ontology-layer function. `query_entity_signals` and `run_hybrid_search` both call it.
- `run_ontology_audit` reports stored enum values that are out of vocabulary, as an `AuditSummary` count and an `AuditReport` list (human-approved scope addition, 2026-11-22).
- Add a `repair` step that coerces enum facets and relation names on stored nodes and edges through `OntologyDB` methods, with a `RepairReport` counter. Remove the template `| lower` filters once stored data is guaranteed canonical. Keep the `i18n.py:256` lowercasing as input-boundary normalization, since it also receives raw URL filter values (human-approved 2026-11-22).

### Allowed scope
- Reuse: `models.py` `VALID_SENTIMENTS`/`normalize_sentiment` (the existing closed-enum pattern, folded into `vocab.py`), `registry.normalize_relation_name`, `db/schema.py` `SIGNAL_CATEGORY_ALIASES` (moved into `vocab.py`), `run_hybrid_search` (its filter predicate replaced by the shared function), and `repair_ontology`/`RepairReport`.
- Cheaper alternative: lowercasing in `upsert_node`/`upsert_edge` only, with no vocab module. Rejected because it leaves the vocabulary in six hand-kept copies, so values like `stale` vs `superseded` still drift, and it doesn't fix item 9.
- Include: `vocab.py`, `models.py`, `pipeline.py`, `llm/prompts.py`, `agent.py`, `db/storage.py`, `db/schema.py`, `repair.py`, `audit.py` (out-of-vocabulary report and its read-side lowercasing only), `i18n.py`, `web/viewmodels.py`, `web/catalog.py`, the badge templates listed above, `locales/*.json` (key additions only), the tests named above, `tests/test_architecture.py`, `docs/architecture/{README,ontology,storage,governance}.md`.
- Exclude/protect: `ontology_registry.json` contents and schema. No change to agent vs web scoping rules (`AUTHORED_BY`, consensus inclusion). No change to sentiment precedence in `resolve_item_sentiment`. No change to `/search` options, the search form, hybrid ranking or vector search (owned by `search-ontology`). No CSS class renames. Don't run `repair` against the real `ontology.db`.

### Invariants changed
- `tests/test_pipeline.py:838,872,878` — today: ingest accepts `"Negative"`/`"Positive"` sentiment and later readers normalize it; after: the same input is stored as `negative`/`positive` at write time. The assertions may need updating to the stored form.
- `pipeline.py:505` — today: superseded consensus views are stored with `status: "stale"`; after: `status: "superseded"`. This is a code rule, not a README entry.

### Decisions required
- None. The human approved Frame's recommendation on all three on 2026-11-22:
  - 1. Out-of-vocabulary values: at ingest, store the field's existing model default as the fallback (`entity_type` `company`, `event_type` `fact`, event `status` `occurred`, `view_type` `analyst_report`, `stance` `neutral`, `support_strength` `moderate`, `stage` `accelerating`, `conviction` `medium`). An unknown `sentiment` is treated as missing, so today's precedence (`resolve_item_sentiment`, stance-derived) applies. `repair` lowercases legacy values but never maps an unknown value to a fallback, and `audit` reports remaining out-of-vocabulary values.
  - 2. Coverage: every enum, namely `entity_type`, `event_type`, `status` (event and view sets), `view_type`, `stance`, `sentiment`, `support_strength`, `stage`, `conviction`.
  - 3. Stances: canon is `buy`, `hold`, `sell`, `bullish`, `bearish`, `neutral`, `cautious`. Aliases: `outperform`/`overweight` to `buy`, `underperform`/`underweight` to `sell`, `unknown` to `neutral`.

## Proof

Candidate: `5aceabc + uncommitted working tree @ home-page-tables (main checkout)`, plus the new untracked `tests/test_canonical_vocabulary.py`. No production file or existing test file was touched.

**Protected witness**
- Ingest coerces mixed-case and alias enum values. Witness: `tests/test_canonical_vocabulary.py` / `test_ingest_stores_mixed_case_and_alias_enum_values_canonically`
  - Defect and boundary: `pipeline.py` stores `entity_type`, `event_type`, `status`, `sentiment`, `view_type`, `stance`, `support_strength`, `conviction` and `stage` exactly as the LLM returned them. Boundary: LLM extraction → `IngestionPipeline.run` → stored node facets.
  - Assertion: after ingest of `"Company"`, `"COMPANY"`, `"Person"`, `"News"`, `"Rumored"`, `"Negative"`, `"Rumour"`, `"Bullish"`, `"Strong"`, `"HIGH"`, `"Analyst_Report"`, `"Outperform"` and `"Emerging"`, the stored facets are `company`, `company`, `person`, `news`, `rumored`, `negative`, `rumor`, `bullish`, `strong`, `high`, `analyst_report`, `buy` (decision 3) and `emerging`. Note-derived edges (`source_doc_id IS NOT NULL`) have relations exactly `{ABOUT, COMPETE}`, with `"competes-with"` mapped to `COMPETE`. All stored relations are exactly `{ABOUT, COMPETE, SUPPORTS}`, where `SUPPORTS` and an extra `ABOUT` come from Acme's consensus view.
  - Proves: the ingest half of the primary claim. Limit: `"competes-with"` already passes today because `registry.canonicalize_edge` normalizes. The RED comes from the enum assertions. The test does not check prompt or tool-schema generation from vocab.
- Out-of-vocabulary values at ingest are replaced per decision 1. Witness: `tests/test_canonical_vocabulary.py` / `test_ingest_stores_field_fallback_for_out_of_vocabulary_values`
  - Defect and boundary: unknown values are stored raw. Same boundary as above.
  - Assertion: `Spaceship`/`Gossip`/`Maybe`/`Hunch`/`Moonshot`/`Huge`/`Total`/`Zombie` are stored as `company`/`fact`/`occurred`/`analyst_report`/`neutral`/`moderate`/`medium`/`accelerating`. Unknown sentiment `Ecstatic` is treated as missing: the event gets `neutral`, and a `bearish` view gets the stance-derived `negative`.
  - Proves: decision 1 at ingest. Limit: it does not check whether a Pydantic validator or the pipeline does the coercion. The sentiment-precedence assertions already pass today, so they guard `resolve_item_sentiment` precedence and are not RED.
- Consensus retirement writes the canonical status. Witness: `tests/test_canonical_vocabulary.py` / `test_retired_consensus_view_is_stored_as_superseded`
  - Defect and boundary: `pipeline.py:505` writes `status: "stale"`, a value outside the view status vocabulary. Boundary: deleting a note → pipeline re-run → stored consensus node.
  - Assertion: after a company's only note is deleted, the prior consensus node's `status == "superseded"`.
  - Proves: the code writes no non-member status. Limit: covers only the delete path, not the edit path, which already writes `superseded` through `storage.py:384`.
- Relation names are normalized at the `OntologyDB` write boundary. Witness: `tests/test_canonical_vocabulary.py` / `test_upsert_edge_and_update_edge_store_normalize_relation_name_output`
  - Defect and boundary: `upsert_edge` uses a weaker rule than `normalize_relation_name`, and `update_edge` writes the relation raw. Boundary: public `OntologyDB.upsert_edge` and `update_edge` → `edges.relation`.
  - Assertion: `upsert_edge(" supplies--to ")` stores `SUPPLIES_TO`. `update_edge(relation="works-at")` stores `WORKS_AT`. Both equal `normalize_relation_name` output.
  - Proves: item 8 at the write boundary. Limit: does not prove the read-side `.upper()` calls were removed. That is structural; see Supporting test plan.
- Repair canonicalizes legacy rows and is idempotent. Witness: `tests/test_canonical_vocabulary.py` / `test_repair_canonicalizes_legacy_enum_facets_and_is_idempotent`
  - Defect and boundary: `repair_ontology` has no facet-normalization step. Boundary: legacy rows written by SQL, then public `repair_ontology(db, registry)`, then stored rows and `RepairReport`.
  - Assertion: the first run reports `total_changes > 0`. Every legacy mixed-case node facet is stored lowercase: entity, event, view and theme, including edge facet sentiment `Negative` → `negative`. Stored consensus `status: "stale"` becomes `superseded`. A second run reports `total_changes == 0`.
  - Proves: the repair half of the primary claim and the idempotence guardrail. Limit: the new counter's name is not checked. The test only requires that the counter feeds `total_changes`. Relation repair already passes today because `_canonicalize_relations` uses `canonicalize_edge`, so this test does not cover it.
- Repair lowercases an out-of-vocabulary legacy value but keeps it, and audit reports it. Witness: `tests/test_canonical_vocabulary.py` / `test_repair_lowercases_but_keeps_out_of_vocabulary_value_and_audit_reports_it`
  - Defect and boundary: repair does not lowercase, and `run_ontology_audit` has no out-of-vocabulary report. Boundary: `repair_ontology`, then `run_ontology_audit(...).model_dump_json()`.
  - Assertion: stored stance `Moonshot` becomes `moonshot`, not `neutral`. The string `moonshot` appears in the audit report JSON. A probe confirmed it is absent from today's audit output.
  - Proves: decision 1 for repair and audit. Limit: the check is name-agnostic, so it does not fix the audit field name or count shape.
- Agent and web signal filters agree (guardrail only, not proof). Witness: `tests/test_canonical_vocabulary.py` / `test_agent_and_web_signal_filters_return_identical_items`
  - Defect and boundary: the rumor, unclassified and category rules are duplicated in `storage.query_entity_signals` and `viewmodels.run_hybrid_search`. Boundary: both public read APIs over one fixture DB.
  - Assertion: over 8 sentiment inputs × 12 category inputs, including `None`, `Unknown`, ` NONE `, `Rumors`, `Facts` and `Analyst Reports`, both return identical event and view id sets. The rumor category returns `{evt_rum, vw_rum}`.
  - Proves: the refactor onto one shared function keeps behavior. Limit: it passes today. The two copies currently agree on every input I found outside the excluded scoping rules (`AUTHORED_BY`, consensus inclusion), so item 9's "one copy" goal has no observable defect and no RED proof. The fixture has no `AUTHORED_BY` or consensus edges, by design.
- Protected paths: `tests/test_canonical_vocabulary.py`.
- Protected revision: untracked file. git blob `23c2a068a8c0a4c2f0c5c59e9c2306ced441abcf`, sha256 `7c5450bc3b645719001edbb90f490d8c6bced17e2db79a843505eeacf9d97ca6`. Superseded original: blob `886ba32037e5c2d2d9dca4542b27040ffe98b8e3`, sha256 `7966730c3f9ca9d9e2c26cd688e53ec5f4b131f887b2f2a4b3d6ef6eb98de285`.
- Owner note: the Frame named `tests/test_pipeline.py`, `tests/test_repair.py` and `tests/test_agent.py`/`tests/test_web.py` as permanent owners. The orchestrator required a new file so that no dirty file would be touched. Build may fold these tests into those owners later only as a separately approved, test-only move, with the assertions byte-identical. The witnesses do not import or reference `stock_ontology.vocab`.

**Rerun note (Build Deviation 1)**
- Changed: only the final relation assertion of `test_ingest_stores_mixed_case_and_alias_enum_values_canonically`. The old `relations == {"ABOUT", "COMPETE"}` over all edges is replaced by two assertions. Note-derived edges (`source_doc_id IS NOT NULL`) must be exactly `{ABOUT, COMPETE}`. All edges must be exactly `{ABOUT, COMPETE, SUPPORTS}`.
- Why: the fixture's fake `synthesize_consensus` returns `supporting_node_ids` = Acme's events, and `OntologyDB.upsert_consensus_view` writes a `SUPPORTS` edge per supporting id with `source_doc_id=None`. That predates the build: the `storage.py` diff has no `SUPPORTS` changes. The old expected set was wrong for correct behavior. It was hidden at RED because the first enum assertion failed earlier. No enum assertion and no other test was changed, and no other wrong assertion was found.
- Rerun result: `uv run pytest tests/test_canonical_vocabulary.py -q -rA` → `7 passed`, with the approved `audit.py` repair (Build Deviation 2) already in the working tree.

**Red evidence**
- `uv run pytest tests/test_canonical_vocabulary.py -q` → `6 failed, 1 passed` on the original blob `886ba320…`. Log: scratchpad `red.log` (session-local, not durable).
  - `test_ingest_stores_mixed_case_and_alias_enum_values_canonically` → `'Company' == 'company'` fails. Raw case is stored. The rerun's relation correction comes after this assertion and does not change this RED.
  - `test_ingest_stores_field_fallback_for_out_of_vocabulary_values` → `'Spaceship' == 'company'` fails. There is no fallback.
  - `test_retired_consensus_view_is_stored_as_superseded` → `'stale' == 'superseded'` fails.
  - `test_upsert_edge_and_update_edge_store_normalize_relation_name_output` → `'SUPPLIES--TO' == 'SUPPLIES_TO'` fails. `update_edge` also stores `works-at` raw, confirmed by probe.
  - `test_repair_canonicalizes_legacy_enum_facets_and_is_idempotent` → `assert 0 > 0` on `RepairReport.total_changes` fails. There is no facet repair step.
  - `test_repair_lowercases_but_keeps_out_of_vocabulary_value_and_audit_reports_it` → `'Moonshot' == 'moonshot'` fails. A probe showed `moonshot` is also absent from today's audit JSON.
  - `test_agent_and_web_signal_filters_return_identical_items` → passed. This is the guardrail baseline, not RED.
- `uv run pytest -q --ignore=tests/test_canonical_vocabulary.py` → `147 passed`, the same as Frame's baseline.
- All RED failures come from missing behavior. None comes from an import or setup error.
- Item 9 ("one shared filter function") has no product proof. Audit must verify it structurally.
- The guardrail "canonical ingest stores the same rows as today" has no new witness. It rests on the existing 147-test suite staying green, apart from the `test_pipeline.py:838,872,878` updates allowed by Frame's Invariants changed.

**Supporting test plan**
- Each `coerce_<enum>` in `vocab.py`: exact member, case variant, alias (`rumour`→`rumor`, `outperform`/`overweight`→`buy`, `underperform`/`underweight`→`sell`, `unknown`→`neutral`) and unknown→None. Build owner: a new `tests/test_vocab.py`. Catches alias-map gaps.
- `vocab.py` mapped in `tests/test_architecture.py` `MODULE_OF` under the `ontology` layer. Build owner: `tests/test_architecture.py`. Catches layer violations.
- Every vocab member has an `enum.<group>.<value>` key in every `locales/*.json`. Build owner: `tests/test_i18n.py`. Catches missing badge labels after `| lower` and the `i18n.py:256` lowercasing are removed.
- The prompt text in `llm/prompts.py` and the `agent.py` tool-schema `enum` lists are generated from vocab. Build owner: `tests/test_agent.py` or a prompts test. Catches stance drift, such as the prompt's 7 stances vs the locales' 12.
- No read-side `.upper()` or `.lower()` remains on stored enum or relation values, and no `| lower` remains in badge templates. Owner: Audit grep over the files listed in Frame's Verified reality. This is structural and has no behavior test.
- `query_entity_signals` and `run_hybrid_search` both call the single ontology-layer filter function. Owner: Audit code review. The parity witness above guards behavior only.

## Build

Candidate: `5aceabc + uncommitted working tree @ home-page-tables (main checkout)`, with the build edits listed below on top of the earlier unrelated dirty changes, including the approved repair pass, plus untracked `tests/test_canonical_vocabulary.py` (blob `23c2a068a8c0a4c2f0c5c59e9c2306ced441abcf` after the Proof rerun; Build never edited it) and new untracked `src/stock_ontology/vocab.py` and `tests/test_vocab.py`. Nothing was committed, stashed or reverted.

### Files changed

- `src/stock_ontology/vocab.py` (new, ontology layer). It holds one `Vocabulary` per enum: entity_type, event_type, event status, view_type, view status, stance, sentiment, support_strength, conviction and stage. Each has a `Literal`, a one-line definition per member, an alias map, the decision 1 fallback, and `coerce_<enum>`. It also has `NODE_FACET_VOCABS`, `canonicalize_node_facets` and `canonicalize_edge_facets` (the repair rule), `out_of_vocabulary_node_facets`, and `SIGNAL_CATEGORY_ALIASES` (moved here). The one shared filter is `matches_signal_filter`, with `parse_sentiment_filter`, `parse_category_filter` and `parse_filter_values`. Stance canon and aliases follow decision 3.
- `src/stock_ontology/models.py`. The extraction and `ConsensusSynthesis` enum fields are typed with the vocab `Literal`s behind a `BeforeValidator`, so an unknown value becomes the fallback and an unknown sentiment becomes None. Field descriptions are generated from vocab. `VALID_SENTIMENTS` and `normalize_sentiment` now come from vocab. `resolve_item_sentiment` and `STANCE_TO_SENTIMENT` are unchanged.
- `src/stock_ontology/pipeline.py`. Consensus retirement writes `superseded`. Entity_type and stage from facet lists are coerced. The redundant `or default` and `.lower()` reads are gone, and the consensus to pm_view mapping uses the coerced value.
- `src/stock_ontology/db/storage.py`. `upsert_edge` and `update_edge` use `normalize_relation_name`. The read-side `.upper()` and `.lower()` calls are removed, including the two SQL `lower(...)` entity_type comparisons. `query_entity_signals` uses the vocab parse and filter functions. Scoping (`AUTHORED_BY`, consensus inclusion) is unchanged.
- `src/stock_ontology/db/schema.py`. `SIGNAL_CATEGORY_ALIASES` is re-exported from vocab, so `db/__init__.py` stays untouched. The lowercasing in `node_meta` is removed.
- `src/stock_ontology/repair.py`. New `_canonicalize_facets` step runs before merges and relations, writes through `upsert_node` and `update_edge`, and adds a `facets_canonicalized` counter to `total_changes`. `_merge_key` no longer casefolds.
- `src/stock_ontology/audit.py` (repair pass, Deviation 2). New `OutOfVocabularyValue` model, `AuditSummary.out_of_vocabulary_value_count` and `AuditReport.out_of_vocabulary_values`, computed with `vocab.out_of_vocabulary_node_facets` over the nodes audit already scans. The read-side entity_type lowercasing at the former lines 302 and 580 is removed. `cli.py` is unchanged, since no existing test needed the new count printed.
- `src/stock_ontology/web/viewmodels.py`. `run_hybrid_search` uses the vocab parse functions and `matches_signal_filter`. `_node_subtype` delegates to `vocab.node_subtype`. Read-side lowercasing is removed, including the observed-stance read in `build_search_filter_options`. Option lists and the form are unchanged.
- `src/stock_ontology/web/catalog.py`. Read-side `.upper()` on relations and `.lower()` on entity_type are removed.
- `src/stock_ontology/i18n.py`. The `.upper()` in `format_relation_label` is removed. Line 256 is kept (see Deviations).
- `src/stock_ontology/llm/prompts.py`. The enum lists in `EXTRACTION_SYSTEM_PROMPT` are generated from vocab. The output is byte-identical to the previous prompt (checked against a saved copy).
- `src/stock_ontology/agent.py`. The `query_entity_signals` tool schema takes its sentiment enum, category list and status list from vocab.
- Templates: all 25 `| lower` badge filters are removed in `themes.html`, `home.html`, `catalog.html`, `ontology.html`, `companies.html`, `search.html`, `theme.html`, `partials/section_events.html`, `partials/section_themes.html`, `partials/section_views.html` and `partials/facet_consensus_card.html`.
- `tests/test_vocab.py` (new). Coercers cover exact, case, alias and unknown values. It also covers the fallback vs repair rules, facet canonicalization, model coercion and schema enum, filter parsing, and the rumor and unclassified rule, plus the audit out-of-vocabulary count and list (repair pass).
- `tests/test_architecture.py`. `"vocab": "ontology"` added to `MODULE_OF`.
- `tests/test_i18n.py`. Added `test_every_vocab_member_has_an_enum_key_in_every_locale`.
- `tests/test_agent.py`. Added `test_prompt_and_tool_schema_vocab_lists_come_from_vocab`.
- `docs/architecture/README.md`, `ontology.md`, `storage.md`, `governance.md`. Documented vocab.py, the write-time rules, the shared filter and the repair facet step.
- `README.md` (rule 8 constraint entry, under Ingestion Constraints). It says to coerce enum facets through `vocab` on write and compare stored values directly. Guarded by `tests/test_canonical_vocabulary.py` and `tests/test_vocab.py`.
- `tests/test_pipeline.py:838,872,878` needed no change. Those assertions still pass.
- `src/stock_ontology/locales/*.json` needed no key additions. Every member already has a key.

### Unit evidence

- `tests/test_vocab.py` was written after `vocab.py`, so no RED was observed for it. Treat it as a guardrail, not test-first evidence.
- `uv run pytest tests/test_vocab.py tests/test_architecture.py tests/test_i18n.py tests/test_agent.py -q` — GREEN: 73 passed (first pass). `uv run pytest tests/test_vocab.py -q` — GREEN: 53 passed after the repair pass.
- The locale coverage test and the prompt/schema test passed on first run. The keys already existed and the prompt output is byte-identical.

### Green evidence

- Decisive witness: `uv run pytest tests/test_canonical_vocabulary.py -q` — 7 passed, against blob `23c2a068a8c0a4c2f0c5c59e9c2306ced441abcf`.
- Gate: `uv run pytest -q` — 209 passed, 0 failed.
- `uv run ruff check src/stock_ontology/audit.py`: all checks passed.
- `uv run ruff check` on the touched modules: all checks passed. Three ruff findings in agent.py and catalog.py are in lines this build didn't touch.
- `grep -rnE '\| ?lower' src/stock_ontology/web/templates` finds 0 matches.
- Remaining read-side `.lower()`/`.upper()` on enum and relation keys, each left for a reason: `models.py:57` (`derive_sentiment_from_stance`, protected precedence chain); `i18n.py:256` (kept by human decision); `i18n.py:301`, `viewmodels.py:639`, `viewmodels.py:1029`, `storage.py:1256`, `storage.py:1573` and `agent.py` tool-arg validation (input boundaries); `registry.py:342-343` (outside Allowed scope). The remaining `.lower()` calls in `audit.py` act on names and alias text, not enum values.

### Intervention record

- None. `repair` has not been run against the real `ontology.db`, which stays human-owned.

### Deviations

1. Handed to Proof. The witness's `relations == {"ABOUT", "COMPETE"}` at `tests/test_canonical_vocabulary.py:185` missed the consensus `SUPPORTS` edges. The Proof rerun corrected it (blob `23c2a068…`), and Build did not edit the file.
2. Resolved by human approval (2026-11-22). The `src/stock_ontology/audit.py` scope addition is implemented as described under Files changed.
3. Resolved by human approval (2026-11-22). The `i18n.py:256` lowercasing stays as input-boundary normalization.
4. Not a request. `registry.py:342-343` still lowercases endpoint entity types inside `canonicalize_edge`. It is outside scope and harmless now that stored values are canonical.
5. For Audit to check: `ExtractedEvent.sentiment` is now `Sentiment | None` with default `"neutral"`, which adds `null` to the event sentiment JSON schema sent to LLM providers. `ConsensusSynthesis.stance` now also offers `cautious`, from the single stance vocab.

## Audit

Candidate: `5aceabc + uncommitted working tree @ home-page-tables (main checkout)`, plus untracked `src/stock_ontology/vocab.py`, `tests/test_vocab.py` and `tests/test_canonical_vocabulary.py` (blob `23c2a068a8c0a4c2f0c5c59e9c2306ced441abcf`).

Independence: fresh-context. Before this audit, the auditing context had seen only the ledger, the candidate diff and the repository. It did not author the Frame, Proof or Build.

Primary-claim verdict: PROVED
- Evidence: `git hash-object tests/test_canonical_vocabulary.py` returns `23c2a068a8c0a4c2f0c5c59e9c2306ced441abcf`, which matches Proof's protected revision. `uv run pytest tests/test_canonical_vocabulary.py -q` gives 7 passed.
- Proof recorded RED on 6 of the 7 tests from missing behavior. The only post-RED edit to the witness is the Proof-owned relation-assertion correction (Rerun note). It comes after the first failing enum assertion, so it does not weaken RED.
- Ingest coercion goes through the `models.py` `BeforeValidator`s, built on `vocab.Vocabulary.coerce_or_fallback`. Pipeline facet-list overrides for `entity_type` and `stage` accept only members.
- `pipeline.py` retirement now writes `superseded`.
- `upsert_edge` and `update_edge` both call `normalize_relation_name`.
- `repair._canonicalize_facets` uses `canonicalize_stored`, which lowercases but never falls back. It feeds `total_changes`.
- `audit.py` reports `out_of_vocabulary_values` and `out_of_vocabulary_value_count`.
- Limit: these are offline fixtures only. Repair was never run against a real DB, which stays human-owned. The "same items" half of the claim rests on a parity witness that was green before the change, plus the structural check below.

Guardrail verdicts:
- Agent and web filters agree, and item 9 has one copy of the rule: PROVED.
  - Evidence: `test_agent_and_web_signal_filters_return_identical_items` passes (8 sentiments by 12 categories).
  - Structurally, `storage.py` `query_entity_signals` calls `parse_filter_values`/`parse_sentiment_filter`/`parse_category_filter` and `vocab.matches_signal_filter` twice, once for the category scope and once for sentiment. `viewmodels.py` `run_hybrid_search` calls `parse_category_filter`/`parse_sentiment_filter` and `matches_signal_filter`.
  - Grep shows no leftover `_matches_category`, rumor predicate, `unknown/none` parsing or `SIGNAL_CATEGORY_ALIASES` lookup in either file. `db/schema.py` only re-exports the alias map from `vocab`.
  - `storage.py:1325` keeps a `status == "rumored"` check, but it only feeds the `rumored_event_count` output counter and is not a filter rule.
  - Scoping (`AUTHORED_BY`, consensus inclusion in `_collect_entity_signal_items`) is unchanged apart from dropping read-side case folding.
  - Limit: item 9 has no RED, because both copies agreed before the refactor.
- Canonical ingest stores the same rows, and repair on a clean DB reports 0 changes: PROVED.
  - Evidence: the second-run `total_changes == 0` assertion in `test_repair_canonicalizes_legacy_enum_facets_and_is_idempotent`. The full suite stays green with `tests/test_pipeline.py` unmodified.
  - `EXTRACTION_SYSTEM_PROMPT` is byte-identical to the `HEAD` copy (Python string compare returned True).
  - Limit: there is no dedicated row-equality witness. This rests on the existing suite.
- Web badges, `t_enum` labels, search options and results are unchanged for the census values: PROVED within limit.
  - Evidence: all 25 removed `| lower` filters were on badge CSS class names over values the Frame census shows are already lowercase.
  - The None-valued badges in `search.html` and `ontology.html` are guarded by `{% if %}`, and no `badge-none` CSS exists.
  - `test_every_vocab_member_has_an_enum_key_in_every_locale` passes. `build_search_filter_options` only lost its `.strip().lower()` on observed stance.
  - Limit: not checked in a browser or against the live DB.
- No read-side `.upper()`/`.lower()` on stored enum or relation values: PROVED.
  - Evidence: `grep -rnE '\| ?lower' src/stock_ontology/web/templates` finds 0 matches.
  - A grep over `storage.py`, `viewmodels.py`, `catalog.py`, `i18n.py`, `pipeline.py`, `schema.py`, `repair.py`, `models.py`, `agent.py` and `audit.py` leaves only:
    - the Build-documented exceptions: `models.py:57` (stance precedence), `i18n.py:256` (human-approved), `i18n.py:301`, `viewmodels.py:639,1029`, `storage.py:1249,1256,1573`, and `agent.py:362,374` (tool and URL input boundaries);
    - `traverse_bfs`'s `normalize_relation_name` over tool-arg relations, which is an input boundary;
    - name, path and alias text folding unrelated to enums.
  - Limit: this is a grep audit, so a dynamic lowercasing path outside these files would not be caught.
- Build deviation 5 (event sentiment schema allows null, consensus stance offers `cautious`): PROVED to break no guardrail.
  - `ExtractedEvent.sentiment: Sentiment | None` widens the provider schema only to accept null. Null or unknown flows into `_resolve_sentiment`, which still resolves to `neutral` by the same precedence.
  - `ExtractedView.sentiment` already allowed null at `HEAD`, so providers already handle the shape.
  - `resolve_item_sentiment` and `STANCE_TO_SENTIMENT` are unchanged. `cautious` is canon by decision 3, maps to `negative` in `STANCE_TO_SENTIMENT`, and has locale key `enum.stance.cautious`.
  - Limit: provider acceptance of the changed JSON schema was not exercised live. `CONSENSUS_SYSTEM_PROMPT` still lists no stance set, so `cautious` is offered only through the schema.

Scope and duty verdict: scope HELD; duties HELD.
- Evidence: the canonical-vocabulary edits are confined to Allowed scope files.
- The edits to `ontology_registry.json`, `registry.py`, `library.css` and `partials/search_bar.html` come from the earlier unrelated work, not this candidate: `traversal_group` `second_order_entity`→`company`, the `.badge-reason` removal, and the `nav.workflow` hidden input. The same goes for second-order and theme changes in `storage.py`, `viewmodels.py`, `agent.py`, `cli.py`, `audit.py`, `locales/*.json`, `tests/test_agent.py`, `tests/test_db.py`, `tests/test_relationships.py`, `tests/test_web.py` and `tests/test_web_navigation.py`.
- No `/search` option list, form, hybrid ranking, CSS class, agent vs web scoping or `resolve_item_sentiment` precedence change is attributable to this candidate.
- Supporting obligations met:
  - `vocab.py` is in the ontology layer, mapped in `tests/test_architecture.py` `MODULE_OF` and in `docs/architecture/README.md`.
  - Coercer unit tests are in `tests/test_vocab.py`.
  - The prompt and tool schema are generated from vocab, guarded by `tests/test_agent.py::test_prompt_and_tool_schema_vocab_lists_come_from_vocab`.
  - Locale coverage is tested.
  - `stale`→`superseded` is handled both in ingest and through the repair alias.
  - The audit out-of-vocabulary report exists.
- The Frame Invariants changed entry for `test_pipeline.py:838,872,878` was permissive ("may need updating"), and leaving it unchanged violates nothing.
- Constraint capture: `README.md` Ingestion Constraints has a new entry with **Why:** and **Guarded by:**, naming `tests/test_canonical_vocabulary.py` and `tests/test_vocab.py`. Both exist.
- Limit: the dirty-tree changes were attributed by reading their content, because no clean pre-proposal snapshot exists.

Test homes:
- `tests/test_canonical_vocabulary.py`: a new file instead of Frame's named owners (`test_pipeline.py`, `test_repair.py`, `test_agent.py`/`test_web.py`). The orchestrator required it so dirty files stayed untouched, and Proof's owner note records that.
- `tests/test_vocab.py`: new, as Proof's Supporting test plan named.
- `tests/test_i18n.py`: the locale-coverage test, which is its planned owner.
- `tests/test_agent.py`: the prompt and schema test, which is its planned owner.
- `tests/test_architecture.py`: the `MODULE_OF` mapping, which is its planned owner.

Full gates: PASS
- `uv run pytest -q`: 209 passed.
- `uv run pytest tests/test_canonical_vocabulary.py -q`: 7 passed.
- `git hash-object tests/test_canonical_vocabulary.py`: `23c2a068a8c0a4c2f0c5c59e9c2306ced441abcf`, which matches.
- `uv run ruff check src/stock_ontology/vocab.py src/stock_ontology/models.py src/stock_ontology/repair.py src/stock_ontology/audit.py`: all checks passed.
- Limit: ruff was not run repo-wide. Build reports existing findings in untouched lines of `agent.py` and `catalog.py`.

Residual risks:
- Item 9 rests on a structural check plus a parity test that was green before the change. A future drift in scoping would not be caught by it.
- The provider-side acceptance of the nullable event sentiment schema and the 7-stance consensus schema has not been exercised against a live provider.
- `registry.py:342-343` still lowercases endpoint entity types inside `canonicalize_edge`. This is out of scope and harmless now that stored values are canonical.
- The witness tests live in a new file rather than Frame's permanent owners. Any later fold into those owners needs separate approval and byte-identical assertions.
- Running `stock-ontology repair` against the real `ontology.db` stays human-owned and untested here.

Recommendation: ACCEPT
Packet: no corrective action. Running repair on the real DB and merging the branch remain separate human-authorized steps. Neither is authorized by this verdict.

## Revisions
