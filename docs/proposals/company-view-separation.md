---
proposal_id: "company-view-separation"
state: FRAMED
witness: builder
candidate: "unassigned"
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
- `tests/test_web_navigation.py:299` (`test_navigation_registry_lookup`) — today: the nav resolver is called with the entity as a raw dict, `{"entity": {"name": "NVIDIA"}, "is_company": True}`; after: it is called with the `EntityHeader` presentation model the view model now supplies, and still expects `("research", "companies", "component")`.

### Decisions required
- None.

Scope across entity types and sequencing were the Proposal's open choices. Neither is material under the pipeline rule: the route is `builder` and both options give the user identical pages. Covering every entity page is the cheapest option, since they share one template. This proposal goes first and the shared event and view partials move to the row models here, which is what the theme and event proposals then extend.

## Proof

Candidate: `5aceabc @ .claude/worktrees/agent-aff71a0ff67ea7b3b (branch worktree-agent-aff71a0ff67ea7b3b)`

Route is `builder`. The decisive witness named in Frame is builder-owned and deferred to Build, which must author it in `tests/test_web.py` and observe it RED before implementation. No witness is protected by this ledger.

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
