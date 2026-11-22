---
proposal_id: "company-view-separation"
state: ACCEPTED
witness: builder
candidate: "4d0e55c @ .claude/worktrees/agent-aff71a0ff67ea7b3b (branch worktree-agent-aff71a0ff67ea7b3b)"
---

# Proposal: Company View: Separate Data from Presentation

## Proposal

Status: approved by the requester on 2026-11-22.

### Intent

The company view (for example `/entity/ent_tsmc_4985c8`) is a template populated by ontology results. The requester wants "abstraction and separation between the data and the presentation" on that page, so the presentation does not depend on how the ontology data is shaped.

### Tentative primary claim

The company view shows the same company information as today, and its presentation is separated from the ontology data it displays.

### Why now

None stated.

### Known constraints

None stated.

### Non-goals

None stated.

### Open choices

- Whether this covers only company pages or every entity page that uses the same view (people, products, other entities).
- Sequence relative to the theme and event proposals (`theme-view-separation`, `event-view-separation`), since the company and theme pages share event and view sections.

## Frame

Candidate: `5aceabc @ .claude/worktrees/agent-aff71a0ff67ea7b3b (branch worktree-agent-aff71a0ff67ea7b3b)`, clean tree plus this ledger.

### Verified reality
- `uv run pytest -q` at 5aceabc: 145 passed. The suites judging this change were green before it started. Limit: says nothing about which entity page details those tests assert.
- `src/stock_ontology/web/app.py::entity_page` calls `build_entity_context(db, entity_id, data_dir=..., lang=...)` inside `_open_ro_db` and renders `entity.html` through `_render`. Proves the route, the read-only DB open, and that the view model is the only data step. Limit: none beyond this route.
- `src/stock_ontology/web/viewmodels.py::build_entity_context` wraps `OntologyDB.get_entity_overview` (`src/stock_ontology/db/storage.py:957`) and passes `entity`, `events`, `views`, `themes`, `related_entities`, `prior_consensuses` through as raw node dicts (with `facets`, `edge_facets`), plus `consensus` as the raw consensus dict spread with a few extracted keys, plus an unused `sentiment_summary`. Proves the data leak starts in the view model. Limit: `company_facets`, `person_facets`, `extra_facets` and `consensus.extra_facets` are already prepared `{key, label, value}` pairs.
- Templates included by `entity.html`, read directly: `partials/facet_header.html` reads `entity.facets.get("ticker")`; `partials/facet_consensus_card.html` reads `old.facets.get('stance'/'as_of')` for prior consensus rows; `partials/section_events.html` reads `ev.facets.get(...)` for `event_date`, `event_type`, `status`, `sentiment`, `source.author`, `source.kind` and decides the "entity impact" note inline; `partials/section_views.html` does the same for `stance`, `sentiment`, `support_strength`, `view_type`, `as_of`, `conviction`, `source.author`; `partials/section_themes.html` reads `thm.facets.get("stage")` and `thm.edge_facets.get("sentiment")`; `partials/section_related_entities.html` reads `rel.facets.get("entity_type")` and falls back from `rel.relationships` to the row itself. `facet_company_card.html`, `facet_person_card.html`, `facet_generic_table.html` only loop prepared pairs. Proves the full list of leaks on the entity page; the brief missed `section_themes.html` and `section_related_entities.html`. Limit: static reading only.
- `templates/theme.html` includes `partials/section_events.html` and `partials/section_views.html`; `build_theme_context` builds its `events` and `views` from `db.get_incident_edges` with the same keys (`facets`, `relation`, `effective_sentiment`, `sentiment_source`, source display fields). Proves the shared partials need the same row model on both pages. Limit: the rest of `theme.html` (first/second-order tables reading `row.company.facets`) is not touched by this change.
- `entity.html` is the only template for every entity type; `build_entity_context` branches on `entity_type` only to set `is_company`/`is_person`. Proves that separating the template covers companies, people, products and other entities at once, and that a company-only separation would need a second template. Limit: none.
- `src/stock_ontology/web/navigation.py::_entity` reads `(ctx.get("entity") or {}).get("name", "")`, and `tests/test_web_navigation.py::test_navigation_registry_lookup` passes `{"entity": {"name": "NVIDIA"}}`. Proves the nav resolver depends on the raw entity dict. Limit: `_theme` reads `ctx["theme"]` the same way and stays as is.
- Rendered HTML of every `/entity/` and `/theme/` request made by `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_relationships.py`, `tests/test_i18n.py` was captured twice at 5aceabc with a scratch pytest plugin (43 pages). The two runs match except `test_read_side_consolidation_and_natural_ux_labels` `/entity/ent_vrt` and `/theme/thm_power`, whose row order varies run to run. Proves a byte comparison baseline exists for "same information as today". Limit: covers only seeded fixtures, and those two pages compare only as sorted lines.

### Final primary claim
- Every entity page (`/entity/{id}`) renders the same information as at 5aceabc, while `build_entity_context` hands the templates only typed presentation models (frozen dataclasses such as `EntityHeader`, `ConsensusSummary`, `PriorConsensusRow`, `EventRow`, `ViewRow`, `ThemeLinkRow`, `RelatedEntityRow`, `SourceCitation`) and prepared label/value pairs, so no raw ontology node, `facets` or `edge_facets` reaches `entity.html` or any partial it includes, and none of those templates mentions `facets`.

### Routing
- Witness: `builder`
- Why: the change rewires a read-only view model and Jinja templates; it can break page rendering, which is contained and reverts with the commit, and it crosses no service boundary and touches no stored data, auth or payment.
- Human-owned irreversible action: merging the candidate branch into `main`.

### Decisive witness
- Layer: web view model plus template source, run offline through FastAPI `TestClient` and `build_entity_context` on a seeded read-only DB.
- Permanent owner: `tests/test_web.py`.
- Witness: a new test that (1) walks the context returned by `build_entity_context` for a company, a person, and an entity with events, views, prior consensus, themes and peers, and asserts no value at any depth is a mapping holding `facets` or `edge_facets` and that `entity`, `consensus`, each `events`/`views`/`themes`/`related_entities`/`prior_consensuses` item is a presentation dataclass; (2) reads `entity.html` and every partial it includes (followed transitively through `{% include %}`) and asserts none contains `facets`; (3) renders the entity and theme pages and asserts the event and view rows still show date, type, status, sentiment badges, entity impact note, stance, support strength and source author. Parts (1) and (2) are the technique the sibling proposals extend to their own pages.

### Guardrail claims
- The theme page (`/theme/{id}`) still renders its events and views sections with the same content, because `build_theme_context` builds the same `EventRow`/`ViewRow` models for the shared partials.
- The web UI still opens `ontology.db` read-only; no write path is added.

### Supporting obligations
- One mapping function per row type in `viewmodels.py` (`_event_row`, `_view_row`, `_source_citation`, and so on) so `build_entity_context` and `build_theme_context` share them. Unit coverage comes from the decisive witness and the existing page tests; no separate unit test unless a mapper grows branching beyond the template logic it replaces.
- `EventRow`/`ViewRow` carry the displayed sentiment (edge override, then node, as the template did) and an `impact_note` value (`None`, `entity`, or `entity_overall` with `overall_sentiment`) so the template only switches on a prepared field.
- Fields keep raw enum codes where the template translates them with `t_enum` and lowercases them for badge CSS classes, so translation and styling stay in the template and output stays byte-identical.
- Build compares rendered HTML of all 43 captured pages against the 5aceabc capture and records the result.

### Allowed scope
- Reuse: `src/stock_ontology/web/viewmodels.py` is the existing view-model layer and already prepares facet pairs with `_format_facet_pairs` and source display with `_resolve_source_fields`; the presentation dataclasses and mappers go there. `tests/test_web.py` is the permanent owner of entity and theme page rendering.
- Cheaper alternative: only rewriting the four leaking spots the brief listed with Jinja macros or extra dict keys. Rejected because extra keys on raw dicts still pass `facets` through, nothing would stop a template from reading them again, and the sibling proposals would have no contract to extend. A company-only separation is not cheaper: all entity types share `entity.html`, so it would need a forked template.
- Include: `src/stock_ontology/web/viewmodels.py` (dataclasses, mappers, `build_entity_context`, and the events/views part of `build_theme_context`); `src/stock_ontology/web/templates/partials/facet_header.html`, `facet_consensus_card.html`, `section_events.html`, `section_views.html`, `section_themes.html`, `section_related_entities.html`; `entity.html` only if a field name changes; `src/stock_ontology/web/navigation.py::_entity` to read the header model's name; `tests/test_web.py` (new witness); `tests/test_web_navigation.py::test_navigation_registry_lookup` as listed under Invariants changed; `docs/architecture/web.md` one line describing the presentation-model contract.
- Exclude/protect: `OntologyDB` and everything under `src/stock_ontology/db/`; the rest of `theme.html` and `build_theme_context` beyond events/views (left to `theme-view-separation`); event pages (left to `event-view-separation`); CSS and locale files; any visible change to page content or markup.

### Invariants changed
- `tests/test_web_navigation.py:299` (`test_navigation_registry_lookup`): today: the nav resolver is called with the entity as a raw dict, `{"entity": {"name": "NVIDIA"}, "is_company": True}`; after: it is called with the `EntityHeader` presentation model the view model now supplies, and still expects `("research", "companies", "component")`.

### Decisions required
- None.

Scope across entity types and sequencing were the Proposal's open choices. Neither is material under the pipeline rule: the route is `builder` and both options give the user identical pages. Covering every entity page is the cheapest option, since they share one template. This proposal goes first and the shared event and view partials move to the row models here, which is what the theme and event proposals then extend.

## Proof

Candidate: `5aceabc @ .claude/worktrees/agent-aff71a0ff67ea7b3b (branch worktree-agent-aff71a0ff67ea7b3b)`

Route is `builder`. The decisive witness named in Frame is builder-owned and deferred to Build, which must author it in `tests/test_web.py` and observe it RED before implementation. No witness is protected by this ledger.

## Build

Candidate: `4d0e55c @ .claude/worktrees/agent-aff71a0ff67ea7b3b (branch worktree-agent-aff71a0ff67ea7b3b)`

Logs live in the session scratchpad `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-FpkZNh/4fb6f79d-a7f6-4555-b469-2d18b87dd45e/scratchpad/logs/` and may be cleared; every command below reruns offline.

### Files changed

- `src/stock_ontology/web/viewmodels.py`: adds frozen presentation models (`SourceCitation`, `EventRow`, `ViewRow`, `EntityHeader`, `ConsensusSummary`, `PriorConsensusRow`, `ThemeLinkRow`, `RelationLink`, `RelatedEntityRow`) and one mapper each; `build_entity_context` returns only these plus the existing prepared pairs, and drops the unused `sentiment_summary`; `build_theme_context` maps its events and views through the same `_event_row`/`_view_row`. The sentiment and "entity impact" decision moves from the templates into `_sentiment_display`. `_attach_source_display` is replaced by `_source_citation`. Satisfies the primary claim and the theme guardrail.
- `src/stock_ontology/web/templates/partials/facet_header.html`, `facet_consensus_card.html`, `section_events.html`, `section_views.html`, `section_themes.html`, `section_related_entities.html`: read model fields instead of `.facets`, `.edge_facets` and inline fallbacks. Primary claim.
- `src/stock_ontology/web/navigation.py`: `_entity` reads the breadcrumb name from the `EntityHeader` attribute. Primary claim.
- `tests/test_web.py`: new builder-owned witness `test_entity_page_templates_only_see_presentation_models` with its seed `_seed_presentation_db`. Primary claim and theme guardrail.
- `tests/test_web_navigation.py`: `test_navigation_registry_lookup` passes an `EntityHeader`, as listed under Frame's Invariants changed; same expected nav state.
- `docs/architecture/web.md`: one sentence on the presentation-model contract.
- `README.md`: one Web UI Constraints entry: entity page templates get only presentation models, guarded by the new witness.

### Unit evidence

- Builder-owned decisive witness: `uv run pytest tests/test_web.py::test_entity_page_templates_only_see_presentation_models -q` on 5aceabc code: RED: 1 failed; the render assertions (part 1) passed, then the context walk failed with 20 raw facet paths starting at `ctx['entity']['facets']`; log: `logs/witness_red.log`.
- Static part of the witness applied to the 5aceabc templates with `uv run python scratchpad/static_red.py`: RED: offenders `facet_consensus_card.html`, `facet_header.html`, `section_events.html`, `section_related_entities.html`, `section_themes.html`, `section_views.html`; log: `logs/static_red.log`. The token regex was narrowed before implementation so translation keys like `'facets.col_value'` in `facet_generic_table.html` don't count; this RED run uses the narrowed regex.
- No separate unit tests: the mappers carry no branching beyond the template logic they replace, and the witness plus the existing page tests cover them.

### Green evidence

- Decisive witness and focused web suites: `uv run pytest tests/test_web.py tests/test_web_navigation.py -v`: 53 passed; log: `logs/web_green.log`.
- Gate: `uv run pytest -v`: 146 passed (145 before plus the new witness); log: `logs/full_gate.log`.
- Same-information check: a scratch pytest plugin (`scratchpad/plug/snapplug.py`, driven by `scratchpad/snap.sh`) captured every `/entity/` and `/theme/` page requested by `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_relationships.py` and `tests/test_i18n.py`, at 5aceabc (with the new witness's pages) and at the candidate. `python3 scratchpad/compare.py <scratchpad>`: 45 pages compared, 45 identical after stripping lines and dropping whitespace-only lines; log: `logs/render_compare.log`. The four pages seeded by `_seed_read_consolidation_db` compare as sorted lines because their row order already varies run to run at 5aceabc.
- `uv run ruff check src/stock_ontology/web tests/test_web.py tests/test_web_navigation.py`: 2 findings, both in `src/stock_ontology/web/catalog.py`, untouched and present before.

### Intervention record

- None: the change has no user-facing outcome to measure, since rendered pages are unchanged.

### Deviations

- None.

## Audit

Candidate: `4d0e55c @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/agent-aff71a0ff67ea7b3b (branch worktree-agent-aff71a0ff67ea7b3b)`, base `5aceabc`. `8549c7d` only touches `docs/proposals/company-view-separation.md`.

Independence: fresh-context. The auditing context had seen only the orchestrator's audit brief, the ledger, the repository and the diff. It did not build the candidate.

Primary-claim verdict: PROVED. Evidence:
- The witness `tests/test_web.py::test_entity_page_templates_only_see_presentation_models` passes on the candidate.
- In a scratch copy of 5aceabc with the candidate's `tests/test_web.py`, the witness is RED: 1 failed, 20 raw facet paths, starting at `ctx['entity']['facets']`. Its render assertions passed on the old code, so they pin the same output before and after the change.
- The witness's static regex, run over the `entity.html` include closure, flags `facet_consensus_card.html`, `facet_header.html`, `section_events.html`, `section_related_entities.html`, `section_themes.html` and `section_views.html` at 5aceabc, and none at the candidate.
- The context walk covers a company (`ent_tsmc`), a person (`ent_wei`) and a peer company (`ent_asml`). It requires dataclass rows for entity, consensus, events, views, themes, related entities and prior consensuses.
- An independent pytest plugin captured every `/entity/` and `/theme/` response requested by `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_relationships.py` and `tests/test_i18n.py`, at 5aceabc and at the candidate. Of 47 pages, 45 are identical after line-strip, and 2 match as sorted lines: `ent_vrt` and `thm_power` from `test_read_side_consolidation_and_natural_ux_labels`. Three reruns at 5aceabc showed those pages already reorder run to run.
- On the specific checks:
  - The sentiment fallback (edge, then node) and the entity-impact note now come from `_sentiment_display`. The witness asserts the "overall: mixed" note, and its absence on an event without an edge override.
  - Ticker, aliases, source author, kind and link, and prior-consensus stance and as_of are each asserted by the witness or matched in the render comparison.
  - `pillars` is now wrapped as a tuple, but `models.py` types pillars as `list[str]`, so output is unchanged.
  - The dropped `sentiment_summary` was read by no template.

Limit:
- The static regex is narrower than the Frame's literal wording ("mentions `facets`"). It allows prepared-pair names such as `company_facets` and translation keys such as `'facets.col_value'`, and it would miss forms like `.get('facets')` or `attr('facets')`. The context walk closes that gap for the entity route, because no raw facets reach the templates. Build recorded the narrowing.
- The render comparison covers seeded fixtures only.

Guardrail verdicts:
- Theme page events and views render unchanged: PROVED. Evidence: `build_theme_context` maps through the same `_event_row` and `_view_row`. The witness asserts the theme page's event name, sentiment badge and author, and the view name and stance. The render comparison matched every captured `/theme/` page, either identical or, for `thm_power`, as the same sorted lines. The rest of `theme.html` (`row.company.facets` and `link.facets`) is untouched, as Frame required. Limit: the witness does not assert the impact note on the theme page. That rests on the render comparison and the shared mapper.
- Web UI stays read-only: PROVED. Evidence: `git diff 5aceabc 4d0e55c -- src/stock_ontology/db src/stock_ontology/web/app.py` is empty. `entity_page` still builds its context inside `_open_ro_db`. `viewmodels.py` gains no write calls. The witness builds its context through `OntologyDB(..., read_only=True)`. The existing `tests/test_db.py::test_read_only_enforces_pragma_query_only` passes in the full gate. Limit: there is no new test of the read-only invariant. This rests on the unchanged code path.

Scope and duty verdict: scope HELD; duties HELD. Evidence:
- Every changed file is on Frame's Include list: `viewmodels.py`; the six named partials; `navigation.py::_entity`; `tests/test_web.py`; the listed `tests/test_web_navigation.py::test_navigation_registry_lookup`; and one sentence in `docs/architecture/web.md`.
- `README.md` gains a Web UI Constraints entry with a `**Why:**` and a `**Guarded by:**` that names the existing witness, as step 7's constraint-capture duty requires.
- `entity.html`, CSS, locales, `src/stock_ontology/db/` and event pages are untouched.
- The nav test change matches Frame's Invariants changed entry: it passes an `EntityHeader` and expects the same nav state.
- The supporting obligations are met: one mapper per row type shared by the entity and theme contexts, `impact_note` and `overall_sentiment` prepared, raw enum codes kept for `t_enum` and badge classes, and a 43-plus page render comparison done.

Limit: dropping the unused `sentiment_summary` key was not named explicitly in Frame. It sits inside the `build_entity_context` change Frame allowed and has no visible effect.

Test homes:
- `tests/test_web.py`: the new witness and its seed `_seed_presentation_db`. This is Frame's named permanent owner for entity and theme page rendering.
- `tests/test_web_navigation.py`: an amended `test_navigation_registry_lookup`. This is its existing owner, and the change is listed under Invariants changed.

Full gates: PASS.
- `uv sync`: ok.
- `uv run pytest tests/test_web.py tests/test_web_navigation.py -q`: 53 passed.
- `uv run pytest -q`: 146 passed.
- Every test runs offline with fake LLM clients (`FakeWebLLM`).
- `uv run ruff check src/stock_ontology/web tests/test_web.py tests/test_web_navigation.py`: 2 findings, both in `src/stock_ontology/web/catalog.py`, which the candidate leaves untouched. Ruff is not a required gate in `AGENTS.md`.

Limit: the suite runs only seeded fixtures, not a real `ontology.db`.

Residual risks:
- The static template guard is regex-based. A future template could read raw data through `.get('facets')` or `attr()`, but only if a raw node reaches the context again, which the context walk would catch for `build_entity_context`.
- `_entity` in `navigation.py` now uses `getattr`. A raw dict passed as `entity` would give an empty breadcrumb instead of failing loudly. Only `/entity/{entity_id}` uses it today, and that route always supplies an `EntityHeader`.
- `theme.html` outside the shared partials still reads raw facets. Frame left that to `theme-view-separation`.

Recommendation: ACCEPT
Packet: no rework needed. The next step is human-owned: decide whether to merge `worktree-agent-aff71a0ff67ea7b3b` into `main`. This audit authorizes no irreversible action.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
