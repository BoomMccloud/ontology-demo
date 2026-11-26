---
proposal_id: "theme-catalysts-phase-1"
state: ACCEPTED
witness: independent
candidate: "f86f8d5 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-catalysts-phase-1 (branch proposal/theme-catalysts-phase-1, uncommitted; tree 6ddff3f8)"
---

# Proposal: Theme Catalysts Phase 1, Establish the Claim Graph

## Proposal

Status: approved by the requester on 2026-11-26. Epic: [Theme Catalysts](epics/theme-catalysts.md), Phase 1.

### Intent

An analyst can record, on the theme page, an investment thesis and the companies the team considers in it or is watching for it. Watching a company means naming the event the team is waiting for, by when, and why it would move the company in. Data entry should be easy: the analyst answers a few questions about a thesis and a company, and the form creates the underlying claim records. A teammate can start from either the thesis or the company and reach the membership, its catalyst, its prediction, and what would resolve each.

The team's beliefs live in a claim graph kept separate from the ontology, so that scenario planning and the later feedback loop can adjust predictions without changing the facts.

User journey:

1. An analyst opens the data center rollout theme and adds the thesis "the rollout benefits optical module suppliers." The thesis shows their name as author.
2. They add Supplier A to the thesis as *in*, with the reason "already ships 1.6T modules in volume to two hyperscalers."
3. They add Supplier X as *watching*. The form asks what they are waiting for, by when, and why. They answer: qualification with a hyperscaler, by the end of Q2, because it unlocks volume orders tied to the rollout. Supplier X shows as a candidate with that catalyst.
4. On Supplier A, they choose *Add a risk*: its larger hyperscaler customer dual-sources 1.6T modules, within the next year, which would remove most of its rollout exposure.
5. A teammate opens Supplier X's company page. They see that it is a candidate for the data center rollout thesis and follow the link to the qualification catalyst, the expected effect, and what would count as the event happening.
6. A second analyst adds a competing thesis on the same theme, "the rollout favors co-packaged optics over pluggable modules." Both theses show on the theme page with their own authors and companies.
7. The theme page lists companies that sources link to the theme but no thesis covers. The analyst picks one and adds it to a thesis from there.

### Tentative primary claim

An analyst can add a thesis and add companies to it as *in* or *watching* through one form, and a teammate can then reach, from either the thesis or the company page, each company's status, its reason, its catalysts, their expected effect, and what would resolve each.

### Why now

The claim graph is the base for the feedback loop and for [Scenarios & Prediction](epics/scenarios-and-prediction.md).

### Known constraints

- The claim graph is separate from the ontology. Claim records point into the ontology by ID. The ontology never refers to a claim.
- Model: thesis, membership, catalyst, and prediction are separate records, as described in the epic. A catalyst can carry more than one prediction.
- A company belongs to a theme only through a thesis membership. Sources linking a company to a theme only suggest it as a candidate.
- Data entry hides the model. *Watching* creates a candidate membership, a catalyst, and an entry prediction in one save. *Add a risk* creates a catalyst and an exit prediction.
- A direct *in* decision requires a written reason.
- Membership is the analyst's recorded decision, not a probability.

### Non-goals

- Resolving catalysts or predictions, linking evidence, and status history. These are Phase 2.
- Probabilities, scenarios, automated diffs, and calibration. These belong to [Scenarios & Prediction](epics/scenarios-and-prediction.md).
- Changes to the live ontology.
- Linking one catalyst to a second thesis, and competing outcomes on one catalyst.
- Scoring whether a thesis was right for a company. The epic records this as a later phase with an open question.

### Open choices

None. The requester settled them on 2026-11-26, answering the Frame's decisions:

1. Author: "still testing phase, okay to have single author." Phase 1 records no author.
2. Editing: "okay to edit." Claims can be edited and removed.
3. Exposure list: "yes, mentioned in notes, suggested candidates." The theme page keeps the note-stated exposure list as "Mentioned in notes," and marks companies no thesis covers as suggested candidates, each with an add action.
4. Thesis page: "separate thesis page, since thesis is a node (each node need to have its own template display page)."
5. Timing: "just add real date now." A catalyst's timing is a date.
6. Sequence: "yes, risks later." *Add a risk* (journey step 4) moves to a later proposal. Competing theses and suggested candidates ship in Phase 1.
7. Storage: "yes." Claims are new tables in `ontology.db`, written only by the worker.

## Frame

Candidate: `f86f8d5 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-catalysts-phase-1 (branch proposal/theme-catalysts-phase-1)`, plus uncommitted edits to `docs/proposals/epics/theme-catalysts.md` and this ledger. No source changes.

### Verified reality
- `uv run pytest -q` before the change: `552 passed in 20.75s`. Proves the suites judging this change start green; limit: it doesn't cover the deployed server's database.
- `docs/architecture/README.md` "Data flow" and `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` prove that the web app and CLI submit writes as spooled jobs and only `worker.py` opens `ontology.db` for writing. Limit: they say nothing about a second database file. No claim store exists today.
- `src/stock_ontology/services/processing.py:32` `CORRECTION_KINDS` and `src/stock_ontology/worker.py:494` `_run_correction` prove that reader-initiated writes run as priority-0 job kinds executed by the worker. This is the path a claim write would extend. Limit: every existing correction kind is bound to a note file (`job.target` resolves through `NotesService`). A claim write has no note, so it needs its own executor branch.
- `src/stock_ontology/pipeline.py:88` and `:916` prove that node IDs are random (`uuid4`). Limit: IDs are stable across reprocessing only while a node keeps resolving by exact name or alias. A deleted and rebuilt `ontology.db` gets new IDs, so claims that point to theme and company IDs would not survive a from-scratch rebuild, wherever they are stored.
- `src/stock_ontology/db/storage.py:554` `merge_node_into` proves that `repair` merges a loser node into a survivor and deletes the loser. Limit: it repoints `edges` and `pending_edges` only. A claim pointing at the loser would dangle unless the merge also repoints it.
- `src/stock_ontology/web/research/routes.py:66` `theme_page` and `build_theme_context` in `src/stock_ontology/web/research/views.py:674` prove that the theme page is a read-only render built from presentation models. `tests/test_web_research.py::test_theme_page_templates_only_see_presentation_models` is its permanent test owner. Limit: neither has any form or write action today.
- `src/stock_ontology/web/research/views.py:577` `_theme_company_rows` and `tests/test_web_research.py::test_theme_page_separates_stated_exposure_from_evidence_mentions` prove that the theme page lists companies from `EXPOSED_TO` edges, labeled as stated exposure. Limit: they don't establish what the Proposal wants that list to become.
- `README.md:29` describes the ontology `theme` node as "Secular narratives / investment theses". Limit: nothing in the code treats a theme as a thesis. The text is description only.
- `rg -n "auth|login|current_user" src/stock_ontology/web src/stock_ontology/config.py` returned no identity or login code. The project memory records that the deployed site at a public URL had no login as of 2026-11-24. Together they prove the app has no notion of who an analyst is. Limit: the Proposal's "shows their name as author" has no existing source.

### Final primary claim
- On a theme page an analyst adds a thesis, which gets its own thesis page. On the thesis page they add a company as *in* (with a required reason) or *watching* (with the event, a by-date, and why it would move the company in), and can edit or remove each. After the worker applies the job, the thesis page shows each company's status, reason, catalyst, by-date and expected effect. The theme page lists its theses and marks companies mentioned in notes that no thesis covers as suggested candidates. The company page lists the company's thesis memberships with links to each thesis page.

### Routing
- Witness: `independent`
- Why: it introduces new stored user data that nothing can regenerate from notes. It also adds a new write path from the web form through the spool and the worker into the database, and changes `repair`'s merge, which can strand or corrupt that data.
- Human-owned irreversible action: deploying to the server and running the schema upgrade on the deployed `ontology.db`. Merging to `main` and pushing.

### Decisive witness
- Layer: a service-level test that submits through `ProcessingService`, drains with `Worker.run_once`, and reads through the read-only thesis, theme and entity page contexts (or the rendered pages through the FastAPI test client, as `tests/web_support.py` does).
- Permanent owner: a new `tests/test_claims.py`.
- Witness: for a seeded theme and company, a submitted thesis and then a *watching* job, after worker passes, appear on the thesis page with status candidate, the catalyst's event and by-date, and the entry prediction's reason. They appear on the company page as a membership linking to that thesis, and on the theme page as a thesis link. An *in* job without a reason, and a *watching* job without a valid date, are refused and write nothing. An edit job changes the shown values, and a remove job removes them.

### Guardrail claims
- The ontology stays unchanged by claim writes. Claim jobs add or change no `nodes`, `edges`, or `pending_edges` rows, and no ontology reader or ingestion path reads claim records.
- When `repair` merges a company or theme, its claims move to the survivor. A claim never points at a missing node.
- Web and CLI processes still never open the database for writing, so `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` stays green unchanged.

### Supporting obligations
- Schema for thesis, membership, catalyst, and prediction, with one membership per company and thesis and one or more predictions per catalyst. Unit candidate: schema round trip on a fresh and on an upgraded database.
- New claim job kinds submitted through `ProcessingService` and executed by the worker in one transaction, refusing writes whose referenced theme or company doesn't exist. Unit candidate: one job per form action.
- *Watching* writes the membership, catalyst, and entry prediction atomically. Unit candidate: a failure after the membership leaves no rows.
- Merge repointing for claim references in `merge_node_into`. Unit candidate: merge a company that has a thesis membership.
- A thesis page (route, presentation model, template) holding the membership form. The theme page gains a thesis list, an add-thesis form, and suggested-candidate marks on the retitled "Mentioned in notes" list. The company page gains a thesis-membership section. Locale keys go into all six locale files (`tests/test_i18n.py`).

### Allowed scope
- Reuse: extend the spooled job path (`ProcessingService` submission, `CORRECTION_KINDS`-style priority, the worker's executor), `OntologyDB`'s transaction and schema upgrade (`init_schema`, idempotent on open), and the theme and entity presentation models and templates. No new process or server.
- Cheaper alternative: storing claims as Markdown files under `ONTOLOGY_DATA_DIR`, written directly by the web app. Rejected because ingestion scans that directory as notes and would extract them as research. It would also need a second writer outside the worker and its own parser for the theme and company pages.
- Include: claim schema and storage methods. Claim job kinds (add, edit and remove for thesis and membership) and their worker executor. Merge repointing. Thesis page. Theme page thesis list, add-thesis form, and suggested candidates. Company page thesis-membership section. Locale strings. Tests.
- Exclude/protect: Phase 2 resolution, evidence links, and status history. Probabilities and scenarios. Any write to `nodes` or `edges`. Changes to ingestion, the extraction prompts, or the `EXPOSED_TO` edge. Login, identity, or author fields. *Add a risk* and exit predictions in the UI. `tests/test_architecture.py` rules.

### Invariants changed
- `README.md:29`. Today: theme is "Secular narratives / investment theses". After: a theme is a topic, and theses are claim records anchored to a theme, outside the ontology.
- `docs/architecture/storage.md` "Schema layer", the list of tables. Today: ontology and job tables only. After: also the claim tables, described as outside the ontology and written only by claim jobs.
- `tests/test_web_research.py::test_theme_page_separates_stated_exposure_from_evidence_mentions`. Today: the list is labeled as stated exposure. After: the same list, labeled "Mentioned in notes," with suggested-candidate marks. Its separation assertions stay; only the label assertions change if it checks the label text.

### Decisions required
- None. The requester settled all seven on 2026-11-26. See the Proposal's Open choices.

## Proof

Candidate: `f86f8d5 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-catalysts-phase-1 (branch proposal/theme-catalysts-phase-1)`, plus uncommitted edits to `docs/proposals/epics/theme-catalysts.md` and this ledger, plus the new uncommitted witness `tests/test_claims.py`. No source changes.

**Protected witness**
- Primary claim (an analyst adds a thesis and *in* or *watching* memberships, then can edit and remove them, and teammates reach them from the thesis, theme and company pages) — `tests/test_claims.py` / `test_analyst_builds_a_thesis_and_teammates_reach_it_from_theme_and_company`
  - Defect and boundary: no claim store, claim job kinds, or thesis page exist. The write crosses from `ProcessingService` through the spool and `Worker.run_once` into `ontology.db`, and the read crosses into the read-only theme, entity and thesis page contexts and the rendered pages.
  - Assertion: on the `seed_web_db` graph, after worker passes:
    - A thesis on `thm_power` plus an *in* membership (TSMC, with a reason) and a *watching* membership (NVIDIA, with an event, `2027-06-30` and an expected effect) show on the thesis context with statuses `in` and `candidate`. The *in* membership has no catalyst. The *watching* one shows the catalyst event, by-date and expected effect.
    - A second, competing thesis shows on the theme context alongside the first.
    - The company context lists NVIDIA's membership as `candidate`.
    - NVIDIA's stated-exposure row has `suggested is False` while it is covered by a membership and `True` once that membership is removed.
    - `GET /thesis/{id}` returns 200 with the statement, the event and both company names. The theme and company pages contain `href="/thesis/{id}"`.
    - Three writes are each refused and change no shown membership: *in* with an empty reason, *watching* with `catalyst_by="end of Q2"`, and *watching* with no `catalyst_by`. A refusal is either `ServiceError(code="invalid")` at submit or a failed job with `error_code == "invalid"`.
    - `claim.thesis.edit` and `claim.membership.edit` change the shown statement, by-date and expected effect. The edited statement also shows on the theme page.
    - `claim.membership.remove` takes the membership off the thesis and company pages, and the company page loses the link. `claim.thesis.remove` takes the rival thesis off the theme context, and `GET /thesis/{rival}` returns 404.
    - Proves the primary claim end to end through the job path.
    - Limit: it doesn't prove locale coverage, the HTML form markup, or the web POST routes (the test submits through the service, not HTTP). It doesn't prove a watching row's `reason` value, which is left unconstrained, or atomicity on a mid-write failure.
- Guardrail, the ontology stays unchanged — same test, final assertion.
  - Defect and boundary: claim executors could write `nodes`, `edges` or `pending_edges`. The boundary is the worker's write to the shared database.
  - Assertion: full row snapshots of `nodes`, `edges` and `pending_edges` are identical before and after every claim job, refusals included. Proves claim writes don't touch ontology rows. Limit: it doesn't prove that no ontology reader or ingestion path reads claim tables.
- Guardrail, a merge moves claims to the survivor — `tests/test_claims.py` / `test_merging_a_company_moves_its_thesis_membership_to_the_survivor`
  - Defect and boundary: `merge_node_into` repoints only `edges` and `pending_edges`, so a membership on the loser would dangle. The boundary is between repair's merge and the claim records.
  - Assertion: after a *watching* membership on `ent_nvda`, `db.merge_node_into("ent_nvda", "ent_nvda_corp")` leaves the same membership id with `company.id == "ent_nvda_corp"` on the thesis context. The survivor's company context lists the thesis. Proves merge repointing for company references. Limit: it doesn't cover a theme merge, or a collision where the survivor already has a membership on that thesis.
- Guardrail, web and CLI stay read-only — the existing `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` stays green unchanged (observed: `4 passed`). No new witness was added for this.
- Interface the builder must match. These names were picked here because nothing exists yet.
  - `ProcessingService.submit_claim(kind, params) -> JobRef`. The job result carries `thesis_id` or `membership_id`. The kinds and their params:
    - `claim.thesis.add`: `{theme_id, statement}`
    - `claim.thesis.edit`: `{thesis_id, statement}`
    - `claim.thesis.remove`: `{thesis_id}`
    - `claim.membership.add`: `{thesis_id, company_id, status: "in"|"watching", reason, catalyst_event, catalyst_by: "YYYY-MM-DD", expected_effect}`
    - `claim.membership.edit`: `{membership_id, <partial fields>}`
    - `claim.membership.remove`: `{membership_id}`
  - `stock_ontology.web.research.views.build_thesis_context(db, thesis_id, lang=...)` raises `KeyError` when the thesis is missing. It returns:
    - `ctx["thesis"]`, with `.id`, `.statement` and `.theme_id`.
    - `ctx["memberships"]`, rows with `.id`, `.company.id`, `.company.name`, `.status` (`"in"` or `"candidate"`), `.reason` and `.catalyst`. `.catalyst` is `None` or has `.event`, `.by_date` (ISO string) and `.expected_effect`.
  - `build_theme_context(...)["theses"]` holds rows with `.id` and `.statement`. `ThemeCompanyRow` gains `.suggested`.
  - `build_entity_context(...)["thesis_memberships"]` holds rows with `.thesis_id`, `.statement` and `.status`.
  - Route `GET /thesis/{thesis_id}`, with a 404 for a missing thesis. Theme and company pages link to it with `href="/thesis/{thesis_id}"`.
- Protected paths: `tests/test_claims.py`. Also `tests/test_architecture.py` (Frame: rules unchanged).
- Protected revision: `tests/test_claims.py` sha256 `6a6fd626dc1726c8b23d2835bfc8822d346b511c393c2cd32f2f93bf783ff17b` (uncommitted, on top of `f86f8d5`).

**Red evidence**
- `uv run pytest tests/test_claims.py -v` → `2 failed in 1.38s`. Both fail with `AttributeError: 'ProcessingService' object has no attribute 'submit_claim'` at `tests/test_claims.py:61`, the first claim submission. Seeding and the pre-write ontology snapshot ran clean first. `ruff check tests/test_claims.py` passes. The orchestrator re-observed `2 failed` and the same sha256.
- RED was observed only at the first missing interface. The later assertions haven't run, so the builder may hit a test bug downstream. Fixing one needs a separately approved test-only correction.

**Supporting test plan**
- Claim schema round trip on a fresh and an upgraded database, one membership per company and thesis, one or more predictions per catalyst → Build: `tests/test_db.py`.
- A claim job referencing a missing theme, company or thesis is refused → Build: new tests in `tests/test_worker.py` or `tests/test_claims.py`, leaving the protected tests unchanged.
- *Watching* writes membership, catalyst and entry prediction atomically → Build: `tests/test_db.py`.
- Theme-node merge repoints thesis `theme_id`, and survivor collisions on a membership are handled → Build: `tests/test_db.py` next to `test_merge_node_into_*`.
- Locale keys for the thesis page, thesis list, forms and suggested marks in all six locales → Build: `tests/test_i18n.py`.
- The theme page relabels stated exposure as "Mentioned in notes" → Build: amend label assertions only in `tests/test_web_research.py::test_theme_page_separates_stated_exposure_from_evidence_mentions`, per Frame.

## Build

Candidate: `f86f8d5 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-catalysts-phase-1 (branch proposal/theme-catalysts-phase-1), plus uncommitted changes; working-tree git tree 6ddff3f86e986039a30976ab8f1ac40da3b327b0 (all tracked and untracked files, via a temporary index)`. Nothing committed, pushed, merged or deployed. The builder did not edit the ledger or `docs/proposals/epics/theme-catalysts.md`.

### Files changed

- `src/stock_ontology/db/schema.py`: four new tables, `claim_theses`, `claim_memberships` (UNIQUE on thesis and company, status `in` or `candidate`), `claim_catalysts` and `claim_predictions` (direction `entry` or `exit`, one or more per catalyst). Deletes cascade inside the claim graph. Theme and company references are foreign keys to `nodes(id)` with no delete action, so a node a claim points at can't be deleted. Tables are created idempotently in `init_schema`.
- `src/stock_ontology/db/claims.py` (new): `ClaimStore` reads and writes the claim rows and modifies no other table. Reads return empty on read-only or older databases that lack the tables. A watching membership and its catalyst and prediction commit in one transaction. `repoint_node` handles merge collisions: the survivor keeps its own membership and takes the loser's catalysts.
- `src/stock_ontology/db/storage.py`: new `OntologyDB.claims` property. `merge_node_into` now calls `claims.repoint_node` first.
- `src/stock_ontology/db/__init__.py`: exports `ClaimStore`.
- `src/stock_ontology/services/processing.py`: `CLAIM_KINDS` at priority 0, plus `check_claim`, `check_membership` and `claim_date`. `ProcessingService.submit_claim(kind, params) -> JobRef` refuses bad input with `ServiceError("invalid")`. *In* needs a reason. *Watching* needs an event, a real `YYYY-MM-DD` date and an expected effect. Edits can't change thesis or company.
- `src/stock_ontology/worker.py`: `_run_claim` writes the claim and finishes the job in one IMMEDIATE transaction. Error codes: `invalid` for a missing theme, company (must be a company entity) or thesis; `conflict` for a duplicate membership; `not_found` for a thesis or membership to edit or remove that doesn't exist. An edit is merged with the stored membership and checked again as a whole.
- `src/stock_ontology/web/research/views.py`: `build_thesis_context` (raises `KeyError` for a missing thesis), new presentation models (`ThesisHeader`, `ThesisMembershipRow`, `CatalystRow`, `ThesisLinkRow`, `CompanyThesisRow`, `CompanyOption`), `ThemeCompanyRow.suggested`, theme `theses`, and entity `thesis_memberships`.
- `src/stock_ontology/web/research/routes.py`: `GET /thesis/{thesis_id}` (404 when missing, `?company=` preselects a company) and `POST /api/claims` (202, 422 for a refused write, 503 without note actions). The forms submit through `ProcessingService`, as note corrections do.
- `src/stock_ontology/web/navigation.py`: adds `/thesis/{thesis_id}` with the breadcrumb Research > Themes > theme > statement.
- `src/stock_ontology/web/templates/thesis.html` (new), `partials/section_theses.html` (new), `theme.html`, `entity.html`, `src/stock_ontology/web/static/claims.js` (new): the thesis page holds the membership add, edit and remove forms and the thesis edit and remove forms. The theme page gains the thesis list, the add-thesis form, and suggested-candidate marks with "add to a thesis" links on the stated-exposure list. The company page gains a thesis-membership section. Forms render only when note actions are enabled.
- `src/stock_ontology/locales/{en,zh,ko,ja,es,fr}.json`: 48 new keys in each. `theme.exposed_companies` is now "Mentioned in notes", translated in each locale.
- `README.md:29`: a theme is a topic, and theses are claim records anchored to it, outside the ontology.
- `docs/architecture/storage.md`: the claim tables, `ClaimStore`, and merge repointing.
- `docs/architecture/web.md` and `docs/architecture/README.md`: the new route, job kinds and priority, plus one durable-constraint entry: repoint claims before deleting or merging a node, with Why and Guarded-by lines.
- `tests/test_db.py`: five tests covering a schema round trip on fresh and upgraded databases, one membership per company and thesis with two predictions on one catalyst, watching atomicity on a mid-write failure, a theme merge and a company merge with a survivor collision, and the foreign key blocking deletion of a referenced node.
- `tests/test_worker.py`: three tests covering refusals for a missing theme, company or thesis and a non-company entity; duplicate and not-found codes and claim priority 0; an edit rechecked as a whole; and `/api/claims` gating and its 422.
- `tests/test_i18n.py`: the thesis, theme and company pages render with every key resolved in all six languages.
- `tests/test_web_navigation.py`: a `/thesis/ths_seed` render variant and a seeded thesis row in the fixture.
- `tests/test_web.py:112`, `tests/test_relationships.py:418`, `tests/test_web_research.py:457`: label text only, "Exposed Companies" to "Mentioned in notes". See Deviations.

### Unit evidence

- `uv run pytest tests/test_db.py::test_merge_node_into_moves_theses_and_resolves_membership_collisions tests/test_claims.py::test_merging_a_company_moves_its_thesis_membership_to_the_survivor`: RED, 2 failed with the `repoint_node` call temporarily removed (restored afterward). Other supporting tests were written after the implementation, so no RED was observed for them.
- `uv run pytest -q tests/test_db.py -k "claim or collisions or cannot_be_deleted or one_membership or watching_membership"`: 5 passed.
- `uv run pytest -q tests/test_worker.py -k claim`: 6 passed.
- `uv run pytest -q tests/test_i18n.py -k thesis`: 1 passed.
- `uv run pytest -q tests/test_web_navigation.py`: 50 passed.

### Green evidence

- Decisive witness: `uv run pytest tests/test_claims.py -v`, 2 passed.
- Protected witness unchanged: `shasum -a 256 tests/test_claims.py` = `6a6fd626dc1726c8b23d2835bfc8822d346b511c393c2cd32f2f93bf783ff17b`.
- Gate: `uv run pytest -q`, 564 passed (552 before). `tests/test_architecture.py` unchanged and green. The orchestrator re-observed 564 passed and the same hash prefix.
- Gate: `uv run ruff check`, all checks passed.
- `node --check src/stock_ontology/web/static/claims.js`: OK. The browser form flow was not run in a real browser.

### Intervention record

- None.

### Deviations

- Label assertions changed in tests the Frame didn't name. The Frame names `tests/test_web_research.py::test_theme_page_separates_stated_exposure_from_evidence_mentions`, but that test checks no label text. The label is asserted in `tests/test_web_research.py::test_theme_page_templates_only_see_presentation_models` (line 457), `tests/test_web.py::test_web_home_entity_theme_search_and_clippy_chat` (line 112) and `tests/test_relationships.py::test_read_side_consolidation_and_natural_ux_labels` (line 418). Only the label string changed in those three lines. The requester accepted these edits on 2026-11-26 ("Accept, run Audit").
- `tests/test_web_navigation.py` gained one VARIANT and a seeded thesis row, because the navigation registry test requires a render variant for every HTML route. Nothing was weakened.
- New source files in Frame-scoped areas: `src/stock_ontology/db/claims.py`, `src/stock_ontology/web/static/claims.js`, `src/stock_ontology/web/templates/thesis.html`, `src/stock_ontology/web/templates/partials/section_theses.html`.
- Design choices for Audit: claim forms are gated on the existing `note_actions` flag; claim foreign keys to `nodes(id)` make any future node-deletion path fail until it repoints claims; a membership edit to *in* keeps any existing catalyst; journey step 1's author display is not implemented, per Decision 1; Add a risk and exit predictions are not in the UI.
- UX note, not changed: the theme page now shows "Mentioned in notes" (stated exposure) above the existing evidence-only "Mentioned Companies" list. The two titles may read as near-duplicates.

## Audit

Candidate: `f86f8d5 @ /Users/jasonbxu/Documents/GitHub/stock_ontology/.claude/worktrees/theme-catalysts-phase-1 (branch proposal/theme-catalysts-phase-1) plus the uncommitted working tree: 28 modified tracked files and 6 untracked (docs/proposals/theme-catalysts-phase-1.md, src/stock_ontology/db/claims.py, src/stock_ontology/web/static/claims.js, src/stock_ontology/web/templates/partials/section_theses.html, src/stock_ontology/web/templates/thesis.html, tests/test_claims.py)`. The auditor audited the files on disk and did not recompute the Build's tree hash.

Independence: fresh-context. The auditing context had seen only the audit brief, AGENTS.md/CLAUDE.md, the ledger, and the candidate files. It did not build or prove the candidate.

Primary-claim verdict: PROVED. Evidence: `tests/test_claims.py::test_analyst_builds_a_thesis_and_teammates_reach_it_from_theme_and_company` passes (`uv run pytest tests/test_claims.py tests/test_architecture.py -v`: 6 passed). `shasum -a 256 tests/test_claims.py` matches Proof's protected revision `6a6fd626…ff17b`. Proof recorded RED. The test drives `ProcessingService.submit_claim` → `Worker.run_once` → the read-only thesis, theme and entity contexts and the rendered `/thesis/{id}`, `/theme`, `/entity` pages, covering add, refuse, edit and remove. `processing.check_claim`/`check_membership` refuse an *in* without a reason and a *watching* without an event, a real YYYY-MM-DD date or an expected effect. `worker._run_claim` rechecks the merged edit and writes it inside one IMMEDIATE transaction that also finishes the job. Limit: the witness submits through the service, not the HTML forms or `claims.js`. `POST /api/claims` gating and the 422 are covered only by `tests/test_worker.py::test_claim_routes_queue_jobs_only_with_actions_enabled`, and no browser run was made.

Guardrail verdicts:
- The ontology stays unchanged by claim writes: PROVED. The witness compares full `nodes`/`edges`/`pending_edges` snapshots before and after every claim job, refusals included. `rg` finds claim access only in `db/claims.py`, `storage.merge_node_into`, `worker._apply_claim` and `web/research/views.py`. `agent.py`, `vocab.py`, `pipeline.py`, `repair.py` and `GraphQueries` are unmodified. Limit: "no ontology reader reads claims" rests on inspection, not a test.
- Merge moves claims to the survivor, and no claim dangles: PROVED. `tests/test_claims.py::test_merging_a_company_moves_its_thesis_membership_to_the_survivor` (protected) and `tests/test_db.py::test_merge_node_into_moves_theses_and_resolves_membership_collisions` pass, the second covering a theme merge, a survivor collision and a zero-dangling query. `repoint_node` runs first inside `merge_node_into`'s transaction, before `DELETE FROM nodes`. Limit: on a collision the loser's status and reason are dropped, and an *in* survivor can end up carrying an entry catalyst. Documented behavior.
- Web and CLI stay read-only: PROVED. `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` passes unmodified. `POST /api/claims` calls `shell.require_note_actions` and then `shell.processing.submit_claim`, which spools a JSON file, the same path note corrections use.

Scope and duty verdict: scope HELD; duties HELD.
- Changes stay within Frame's Include list. `pipeline.py`, the extraction prompts and `EXPOSED_TO` handling are unchanged. No author fields and no *Add a risk* UI. `exit` exists only as a schema CHECK value.
- FK safety: claim FKs reference `nodes(id)` with `PRAGMA foreign_keys = ON` (`storage.py:125`). The only node-deleting paths are `delete_document_artifacts` and `merge_node_into`. Theme and company nodes are created with `source_doc_id=None` (`pipeline.py:268`, `:916`), and the worker accepts only theme nodes and company entities as claim targets. A scratch probe deleted every note's artifacts on a seeded graph with a thesis and membership, without error.
- Invariants: `README.md:29` and the `docs/architecture/storage.md` table list changed as Frame listed. The label-only edits in `tests/test_web.py:112`, `tests/test_relationships.py:418` and `tests/test_web_research.py:457` carry out Frame's intended relabel; the requester accepted them on 2026-11-26. Counted as a resolved deviation.
- `tests/test_web_navigation.py` gained one VARIANT and one seeded fixture row, as the route registry requires.
- Constraint capture: `docs/architecture/README.md` has "Repoint claims before deleting or merging a node" with **Why:** and **Guarded by:**, and both named tests pass.

Test homes: `tests/test_claims.py` (end-to-end, protected), `tests/test_db.py` (storage), `tests/test_worker.py` (job executor and route gating), `tests/test_i18n.py` (locales), `tests/test_web_navigation.py` (route registry), and label strings in their existing owners.

Full gates: PASS. `uv run pytest -q`: 564 passed. `uv run ruff check`: all checks passed. `uv run pytest tests/test_claims.py tests/test_architecture.py -v`: 6 passed. Protected hash matches. Limit: offline suite only, no browser run and no check against the deployed `ontology.db`.

Residual risks:
- Claims key on random node IDs, so a from-scratch rebuild of `ontology.db` loses every claim, and nothing exports or backs them up. Claims are the one table set notes can't regenerate.
- Future code that deletes a theme or company node without calling `repoint_node` fails with an `IntegrityError`, which the worker treats as a transient, retried error. The README entry warns about it.
- The claim forms sit behind the existing `note_actions` flag with no identity or access control. The deployed site has no login, so note actions there let anyone write claims.
- "Mentioned in notes" next to "Mentioned Companies" on the theme page may read as duplicates.
- Deploying the schema upgrade, merging to `main` and pushing stay human-owned.

Recommendation: ACCEPT
Packet: no repair needed. Next action is human-owned: commit and merge `proposal/theme-catalysts-phase-1`, then separately decide whether to deploy and run the schema upgrade on the server's `ontology.db`, backing it up first. If anything changes before merge, re-run `uv run pytest -q`, `uv run ruff check`, and the sha256 check on `tests/test_claims.py`.

## Revisions
