---
proposal_id: "theme-view-separation"
state: ACCEPTED
witness: builder
candidate: "2abd270 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-view-separation (branch proposal/theme-view-separation)"
---

# Proposal: Investment Theme View: Separate Data from Presentation

## Proposal

Status: approved by the requester on 2026-11-22. Sequence settled: `company-view-separation` landed first, in main at `27ffbcb`.

### Intent

The investment theme view (for example `/theme/thm_enterprise_ai_monetizati_a323a6`) should have "the same kind of separation" between data and presentation as the company view, using the same technique.

### Tentative primary claim

The investment theme view shows the same theme information as today, and its presentation is separated from the ontology data it displays, the same way as the company view.

### Why now

None stated.

### Known constraints

- Use the same technique as the company view proposal (`company-view-separation`).

### Non-goals

None stated.

### Open choices

- Sequence: whether this waits for `company-view-separation` to land so the technique is set there first, or ships together with it.

## Frame

Candidate: `27ffbcb @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-view-separation (branch proposal/theme-view-separation)`, clean tree plus this ledger.

### Verified reality
- `uv sync` then `uv run pytest -q` at 27ffbcb: 146 passed. The suites judging this change were green before it started. Limit: says nothing about which theme page details those tests assert.
- `src/stock_ontology/web/app.py::theme_page` builds its context with `build_theme_context(db, theme_id, data_dir=..., lang=...)` inside `_open_ro_db` and renders `theme.html` through `_render`. Proves the route, the read-only DB open, and that the view model is the only data step. Limit: none beyond this route.
- `src/stock_ontology/web/viewmodels.py::build_theme_context` (line 655) passes `theme` as the raw node dict from `OntologyDB.find_theme_companies` (with `facets`), and `first_order` and `second_order` as the raw rows from the same call, after writing `source_file`, `source_label` and `source_exists` into each first-order link in place. `events` and `views` already go through `_event_row` and `_view_row`, and `extra_facets` is already prepared pairs. Proves where the leak starts. Limit: `stage` is already a plain value.
- `src/stock_ontology/db/storage.py::find_theme_companies` (line 1373) builds first-order rows as `{company: <raw node dict>, consensus_stance, consensus_summary, links}`, where a direct link holds `via`, `relation`, `direction`, `facets`, `exposure_sentiment` and an indirect link holds `via`, `via_node_id`, `theme_relation`, `entity_relation`, `source`, `facets` (the event or view node facets); second-order rows are `{company, consensus_stance, paths}` with each path holding `facets` (merged edge facets). Proves every raw facets mapping the theme context carries today. Limit: `consensus_summary` and `via_node_id` are read by no template.
- `src/stock_ontology/web/templates/theme.html` reads `row.company.facets.get("ticker")` at lines 43 to 44 and 100 to 101, and resolves the direct link sentiment inline as `link.exposure_sentiment or (link.facets.get("sentiment") if link.facets is mapping else None)` at line 60. It includes `partials/facet_generic_table.html` (prepared pairs only), `partials/section_events.html` and `partials/section_views.html` (already on `EventRow` and `ViewRow`). Proves the full list of template leaks on the theme page. Limit: static reading only; `base.html` is extended, not included, and holds no `facets`.
- `src/stock_ontology/web/navigation.py::_theme` (line 124) reads `(ctx.get("theme") or {}).get("name", "")`. No test in `tests/test_web_navigation.py` passes a theme context dict directly; the theme breadcrumb is asserted only through the rendered `/theme/thm_power` page (line 53). Proves the nav resolver depends on the raw theme dict and no nav test pins that shape. Limit: none.
- `tests/test_web.py::test_entity_page_templates_only_see_presentation_models` with helpers `_raw_facet_paths`, `_template_closure`, `RAW_FACET_TOKEN` and seed `_seed_presentation_db` is the technique from `company-view-separation`. `/theme/thm_ai` on that seed renders a first-order TSMC row with ticker, buy consensus, one direct link with a positive badge and two indirect links (one cited source with a catalog link, one without a note on disk), plus a second-order ASML row with ticker and a path to TSMC. Proves the existing seed exercises every theme row shape. Limit: the seed theme has no aliases and no extra facets; those rest on the render comparison of other fixtures.
- README `Web UI Constraints` (README.md:168) limits the presentation-model rule to `entity.html` and its partials. Proves the rule does not yet cover `theme.html`. Limit: none.

### Final primary claim
- Every theme page (`/theme/{id}`) renders the same information as at 27ffbcb, while `build_theme_context` hands the templates only typed presentation models (frozen dataclasses for the theme header, first-order rows with their exposure links, second-order rows with their paths, plus the existing `EventRow`, `ViewRow` and prepared label/value pairs), so no raw ontology node, `facets` or `edge_facets` reaches `theme.html` or any partial it includes, and none of those templates reads `.facets`.

### Routing
- Witness: `builder`
- Why: the change rewires a read-only view model and one Jinja template; it can break page rendering, which is contained and reverts with the commit, and it crosses no service boundary and touches no stored data, auth or payment.
- Human-owned irreversible action: merging the candidate branch into `main`.

### Decisive witness
- Layer: web view model plus template source, run offline through FastAPI `TestClient` and `build_theme_context` on a seeded read-only DB.
- Permanent owner: `tests/test_web.py`.
- Witness: a new test, reusing `_seed_presentation_db`, `_raw_facet_paths`, `_template_closure` and `RAW_FACET_TOKEN`, that (1) renders `/theme/thm_ai` and asserts the first-order row shows the company ticker, the consensus badge, the direct link relation with its sentiment badge and "(direct)" note, and the indirect links with their via path and source citation (linked when the note exists), and the second-order row shows its ticker and path; (2) walks the context from `build_theme_context` and asserts no raw facets mapping is reachable and `theme` and each `first_order`, `second_order`, `events` and `views` item is a dataclass; (3) asserts no template in the `theme.html` include closure matches `RAW_FACET_TOKEN`.

### Guardrail claims
- Entity pages (`/entity/{id}`) render unchanged, and `test_entity_page_templates_only_see_presentation_models` still passes.
- The web UI still opens `ontology.db` read-only; no write path is added.

### Supporting obligations
- Mappers in `viewmodels.py` own the logic the template had: the ticker comes from the company facets, and the direct link sentiment is `exposure_sentiment`, then the link facets `sentiment`. Reuse `_entity_header` for the company cell and `_source_citation` for indirect link sources.
- Enum fields keep raw codes (`stage`, `consensus_stance`, relations, sentiment) so `t_enum`, `format_relation` and the badge CSS classes stay in the template and output stays the same.
- `navigation.py::_theme` reads the header model's `name`, as `_entity` does.
- Build compares rendered HTML of every `/entity/` and `/theme/` page the web suites request against a 27ffbcb capture and records the result.
- No separate unit tests unless a mapper grows branching beyond the template logic it replaces.

### Allowed scope
- Reuse: `src/stock_ontology/web/viewmodels.py` presentation-model layer (`EntityHeader`/`_entity_header`, `SourceCitation`/`_source_citation`, `_event_row`, `_view_row`, `_format_facet_pairs`) and the witness helpers in `tests/test_web.py`.
- Cheaper alternative: adding `ticker` and `sentiment` keys to the raw rows and editing the three template spots. Rejected because the raw `company`, link and path dicts would still carry `facets` into the template, so the context walk could not pass and nothing would stop the template reading them again; the company run rejected the same shortcut.
- Include: `src/stock_ontology/web/viewmodels.py` (new theme dataclasses and mappers, `build_theme_context`); `src/stock_ontology/web/templates/theme.html`; `src/stock_ontology/web/navigation.py::_theme`; `tests/test_web.py` (new witness); `docs/architecture/web.md` one sentence extending the presentation-model note to the theme page; `README.md` extending the existing Web UI Constraints entry to `theme.html`.
- Exclude/protect: everything under `src/stock_ontology/db/` (`find_theme_companies` keeps its shape); the entity page templates and partials; `_seed_presentation_db` and the existing entity witness; event pages (left to `event-view-separation`); CSS and locale files; any visible change to page content or markup.

### Invariants changed
- None.

### Decisions required
- None.

## Proof

Candidate: `27ffbcb @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-view-separation (branch proposal/theme-view-separation)`

Route is `builder`. The decisive witness named in Frame is builder-owned and deferred to Build, which must author it in `tests/test_web.py` and observe it RED before implementation. No witness is protected by this ledger.

## Build

Candidate: `2abd270 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-view-separation (branch proposal/theme-view-separation)`

Logs and scratch scripts live in the session scratchpad `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-FpkZNh/4fb6f79d-a7f6-4555-b469-2d18b87dd45e/scratchpad/theme/` and may be cleared; every command below reruns offline.

### Files changed

- `src/stock_ontology/web/viewmodels.py`: adds frozen presentation models `ThemeHeader`, `ExposureLink`, `FirstOrderRow`, `SecondOrderPath` and `SecondOrderRow`, with mappers `_theme_header`, `_exposure_link`, `_first_order_row` and `_second_order_row`. The company cell reuses `EntityHeader` through `_entity_header`, and indirect link sources reuse `SourceCitation` through `_source_citation`. The direct link sentiment fallback (`exposure_sentiment`, then the link facets `sentiment`) moves from the template into `_exposure_link`. `build_theme_context` returns only these models plus the existing `EventRow`, `ViewRow`, `stage` and prepared pairs, and no longer writes source fields into the raw link dicts. The unused `consensus_summary` and `via_node_id` are not carried over. Primary claim.
- `src/stock_ontology/web/templates/theme.html`: reads `row.company.ticker`, `link.sentiment`, `link.direction` and `link.source.*` instead of `row.company.facets`, `link.facets` and the inline fallback. Primary claim.
- `src/stock_ontology/web/navigation.py`: `_theme` reads the breadcrumb name from the `ThemeHeader` attribute, as `_entity` does. Primary claim.
- `tests/test_web.py`: new builder-owned witness `test_theme_page_templates_only_see_presentation_models`, reusing `_seed_presentation_db`, `_raw_facet_paths`, `_template_closure` and `RAW_FACET_TOKEN`; it writes one note to disk so a linked citation renders. Primary claim.
- `docs/architecture/web.md`: one sentence naming the theme page models.
- `README.md`: the existing Web UI Constraints entry now covers `theme.html` and names the new witness alongside the entity one.

### Unit evidence

- Builder-owned decisive witness: `uv run pytest tests/test_web.py::test_theme_page_templates_only_see_presentation_models -q` on 27ffbcb code: RED: 1 failed; the render assertions (part 1) passed, then the context walk failed at `ctx['theme']['facets']`; log: `logs/witness_red.log`.
- `uv run python scratchpad/theme/red_detail.py` on 27ffbcb code: RED detail: 7 raw facet paths (`theme`, both company cells, three first-order links, one second-order path), and the static scan flags `theme.html`; log: `logs/red_detail.log`. The same script on the candidate reports 0 paths and no offenders.
- No separate unit tests: the mappers carry no branching beyond the template logic they replace, and the witness plus the existing page tests cover them.

### Green evidence

- Decisive witness and focused web suites: `uv run pytest tests/test_web.py tests/test_web_navigation.py -v`: 54 passed; log: `logs/web_green.log`.
- Gate: `uv run pytest -v`: 147 passed (146 before plus the new witness); log: `logs/full_gate.log`.
- Same-information check: the scratch pytest plugin from the company run (`scratchpad/plug/snapplug.py`, driven by `scratchpad/theme/snap.sh`) captured every `/entity/` and `/theme/` page requested by `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_relationships.py` and `tests/test_i18n.py`, twice at 27ffbcb (with the new witness, so its pages are included) and twice at the candidate. `python3 scratchpad/theme/compare.py snap/before snap/after`: 46 pages, 42 identical and 4 the same as sorted lines, 0 different; against the second candidate run, 44 identical and 2 the same as sorted lines; log: `logs/render_compare.log`. Lines are stripped and blank lines dropped, since the removed `{% set %}` line only changes blank-line layout. Only pages from the two tests seeded by `_seed_read_consolidation_db` may compare as sorted lines, because their row order varies run to run; the two 27ffbcb runs happened to match exactly.
- `uv run ruff check src/stock_ontology/web tests/test_web.py`: 2 findings, both in `src/stock_ontology/web/catalog.py`, untouched and present before.

### Intervention record

- None: the change has no user-facing outcome to measure, since rendered pages are unchanged.

### Deviations

- None.

## Audit

Candidate: `2abd270 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-view-separation (branch proposal/theme-view-separation)`, base `27ffbcb`. The ledger-only commit `559e364` was read, not audited as code.

Independence: fresh-context. The auditing context had seen only the orchestrator's task brief, the repo, the ledger and the candidate diff. It did not build the candidate or see the builder's logs.

Primary-claim verdict: PROVED. Evidence:
- `uv run pytest tests/test_web.py tests/test_web_navigation.py -v`: 54 passed.
- On a `git archive 27ffbcb` copy with the candidate's `tests/test_web.py` dropped in, `test_theme_page_templates_only_see_presentation_models` is RED. The render part passes, then the context walk fails with 7 raw facet paths, starting at `ctx['theme']['facets']`. A static grep of the base `theme.html` shows `.facets` reads at lines 43, 44, 60, 100 and 101.
- On the candidate, `theme.html` has no `.facets` or `edge_facets` read. The only hit is the i18n key `theme.facets_heading`, which `RAW_FACET_TOKEN` correctly ignores.
- `build_theme_context` now returns `ThemeHeader`, `FirstOrderRow`/`ExposureLink`, `SecondOrderRow`/`SecondOrderPath`, `EventRow`, `ViewRow`, a plain `stage` string and prepared pairs. The company cell reuses `_entity_header` and indirect sources reuse `_source_citation`, as the Frame required.
- Mutation check on a scratch copy: adding `row.company.facets` back into `theme.html` fails part 3 with `['theme.html']`. Passing raw `second_order` rows fails part 1, because the ticker is lost. With both mutations reverted, the witness passes again. The witness does not pass trivially.
- Same-information evidence comes from an independent pytest plugin that captured every `/theme/` and `/entity/` page requested by `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_relationships.py` and `tests/test_i18n.py`, at base and at candidate, twice each. Run 1: 48 pages, 39 identical and 9 equal as sorted lines, 0 different. Run 2: 47 identical and 1 equal as sorted lines, 0 different. Base against base also gives 1 sorted-equal page, so the row-order variance is already present at 27ffbcb.
- A scratch edge-case seed on both trees covered theme aliases and extra facets in en and zh; a non-string ticker and a company with no ticker; an incoming direct link; unnormalizable and normalizable direct sentiment; an event link whose cited note is missing and a view link with no source; second-order owns, sells-to and competes paths; and three entity pages. The entity pages are byte-identical. The theme pages differ only by two blank lines from the removed `{% set %}` line, and are identical once blank lines are dropped.

Limit: the direct-link fallback to the link facets `sentiment` is preserved in `_exposure_link`, but storage (`_merge_exposure`) seems to make it unreachable. With an unnormalizable value, neither tree renders a badge, so that branch has equal behavior but no live path exercises it.

Guardrail verdicts:
- Entity pages render unchanged and the entity witness still passes: PROVED. Evidence: `uv run pytest tests/test_web.py -k presentation_models` gives 2 passed. Every `/entity/` capture in both runs matches the base, and the scratch entity pages are byte-identical. No entity template or partial changed in the diff. Limit: this covers only the entity pages the suites and the scratch seed request.
- The web UI opens `ontology.db` read-only and adds no write path: PROVED. Evidence: `git diff 27ffbcb 2abd270 -- src/stock_ontology/db` is empty. `app.py::theme_page` is unchanged and still uses `_open_ro_db`. The new witness opens the DB with `read_only=True` and uses `FakeWebLLM`, and nothing in the diff calls a live provider. `tests/test_relationships.py::test_guardrail_read_only_agent_web_inspect_and_audit` passes in the full gate.

Scope and duty verdict: scope HELD; duties HELD. Evidence:
- All six changed files are in Frame's Include list: `viewmodels.py`, `theme.html`, `navigation.py::_theme`, `tests/test_web.py`, one note in `docs/architecture/web.md`, and the Web UI Constraints entry in `README.md`.
- Nothing under `src/stock_ontology/db/`, CSS, locales, entity templates or event pages changed.
- `_seed_presentation_db` and the entity witness are unchanged. The test diff only adds lines.
- Supporting obligations are met: raw enum codes are kept, `_theme` reads the header's `name`, and no extra unit tests were added.
- The constraint-capture duty is met. The README entry names both witnesses, and both exist and pass.

Limit: Frame records `Invariants changed: None`, yet the README invariant was widened to cover `theme.html`. This is in scope because Frame's Include list names exactly this README edit, and the rule only gets stricter.

Test homes: `tests/test_web.py`, the permanent owner of web page and presentation-model witnesses, next to the entity witness and reusing its helpers.

Full gates: PASS.
- `uv sync`: resolved, no changes.
- `uv run pytest tests/test_web.py tests/test_web_navigation.py -v`: 54 passed.
- `uv run pytest -v`: 147 passed.
- `uv run ruff check` on the changed Python files: all checks passed.

Limit: the gates are offline only. No live DB under `ONTOLOGY_DATA_DIR` was rendered.

Residual risks:
- `_raw_facet_paths` walks only the `build_theme_context` output. `app.py` then adds `rail`, which today holds only counts, so a future raw field added there would not be caught.
- The candidate drops `consensus_summary` and `via_node_id`, which no template reads today. A later template need would require a model field.
- Mappers coerce some values with `str()`, for example `summary`. That matches how Jinja renders the same values today, but it hides type problems at the model boundary.

Recommendation: ACCEPT
Packet: no change is required. Merging `proposal/theme-view-separation` into `main` is the human-owned irreversible step.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
