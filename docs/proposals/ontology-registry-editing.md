---
proposal_id: "ontology-registry-editing"
state: ACCEPTED
witness: independent
candidate: "93240d44e29d67595d36bf3fe21d135d45506479 @ main, /Users/jasonbxu/Documents/GitHub/stock_ontology, SHA-256 8bee59f7232d41f5780467f291a2d09d4b30b98ff4f1e43cb471132697da78e7"
---

# Proposal: Ontology Registry Editing

## Proposal

### Intent

Deliver the editing increment approved in [Ontology Registry and Schema](ontology-registry-and-schema.md). Let a user correct the fields in each section of a company, theme, or person record. Keep details and identity separate. Company and theme changes show a diff and use separate browser publication and application confirmations for an explicitly enabled local operator. Keep CLI confirmations available for agentic actions. Person corrections and relationship changes connect to their supporting note. The record shows the outcome of a correction or the state of a registry change where it affects the displayed fields.

### Tentative primary claim

A user can start from a Registry record, review and apply a supported correction through its appropriate workflow, then see the resulting values or relationships on the record.

### Why now

The requester approved browsing with source links first and editing second. The browsing work supplies the record pages and note links that the editing increment extends.

### Known constraints

Keep edit actions next to the fields they affect and keep Schema for shared definitions. Keep publication and application distinct and show pending status only where it helps the current task.

### Non-goals

Implementing the Suggestions and Run history sections of the mockup in this increment.

### Open choices

None. The requester chose browser confirmations for operators and retained the CLI workflow for agentic actions.

## Frame

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main, /Users/jasonbxu/Documents/GitHub/stock_ontology, accepted browse application/test/README SHA-256 cd6f89e27bafc6acaf1778584bff547c6d232e3ffd247ee357d08dd3194eba50`.

### Verified reality

- `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_registry_governance.py tests/test_web.py tests/test_web_navigation.py tests/test_worker.py tests/test_architecture.py -k 'registry or ontology or relationship or relink or only_worker'` passed before editing, 23 passed and 109 deselected. This covers the existing browse, worker, CLI, and note correction boundaries. It does not exercise Registry editing.
- `src/stock_ontology/cli.py::registry_publish` and `registry_apply` submit `registry.publish` and `registry.apply` to the worker after separate CLI confirmations. `worker.py::_run_publish` and `_run_rollout` revalidate proposal or publication identity and the exact rollout inputs and outputs inside the transaction. These contracts are available for reuse. The web app has no operator submission surface today.
- `worker.py::plan_rollout` opens a disposable writable copy to preview repair. `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` and its import-layer test prohibit web modules from doing this directly. `db/storage.py::registry_rollout_rows` includes nodes, edges, pending edges and the ingestion log. It can bind a reviewed metadata change to the same graph input as repair if the preview and apply share the same deterministic transformation.
- `cli.py::_create_library_app` enables ordinary note actions and `serve` accepts a configurable bind address. `docs/architecture/web.md:73–86` describes the local shared account and the lack of hosted access control. `web/notes/routes.py::_submitted` returns existing job references. These mechanisms do not confer registry operator authority.
- `web/ontology/routes.py::ontology_page` and `web/ontology/views.py::build_registry_context` supply record pages, resolvers, and evidence return links. `_registry_graph_ids` can produce zero or multiple graph matches. `repair.py::repair_ontology` does not currently copy company/theme fields into graph nodes. Any graph metadata effect must be implemented and shown in the rollout plan.
- `pipeline.py::_current_note_doc` verifies current source and ingestion membership. Its relink method changes only the selected note’s attribution. Relationship correction supports type and endpoints with existing edge ownership checks, while adding a relationship already accepts facets. `work/ontology-tab.html:1814–1828` shows canonical person edits preserving node identity and changing only matching employment evidence from the same note. A canonical person-field correction and editable relationship facets require new worker behavior.

### Final primary claim

- From a Registry record, a user can review and complete a supported change through separate local operator browser publication and adoption or through a note-backed worker correction, then see the resulting fields or relationships on the record.

### Routing

- Witness: `independent`.
- Why: The change exposes a new browser authorization boundary and writes versioned registry state, graph metadata, and note relationships through the worker.
- Human-owned irreversible action: Publication to a real registry, live adoption and corrections, merge, and deploy. Proof, Build, and Audit use disposable fixtures.

### Decisive witness

- Layer: Offline HTTP integration through `TestClient`, the real command spool and worker, disposable registry, graph and notes, and fake LLM clients. Verify the accepted CLI contract separately.
- Permanent owner: `tests/test_web.py` for the new Registry workflow, `tests/test_registry_governance.py` and `tests/test_architecture.py` for existing governance and ownership guards.
- Witness: Add separable cases in `tests/test_web.py`, selected with `-k ontology_registry_editing`. The operator case submits a company or theme field diff visible only on the enabled local surface, rejects missing or mismatched Origin and untrusted requests before enqueue, and follows two separate confirmations. After publication, inspect the published revision and confirm the applied revision and graph fields are still old. Confirm adoption only from a completed worker preview, reject a forged or stale confirmation, then check the expected applied revision and record fields. Parameterize across company and theme field shapes where useful. The correction case reviews a person or existing relationship change using a seeded note and takes the worker to completion, then checks the edited record and the selected note’s facts while a second note’s evidence and both source files remain intact. Check stale note and wrong-owner cases independently from the success path.
- Run the witness RED against the accepted browse fingerprint. The immutable baseline can be reconstructed in a disposable directory from `git archive 93240d44e29d67595d36bf3fe21d135d45506479`, the external `/private/tmp/stock-ontology-editing-base/browse.patch`, and `/private/tmp/stock-ontology-editing-base/browse-new-files.tar.gz`. Verify the tracked changes and untracked file bytes against the accepted browse fingerprint before adding only the witness. Preserve that witness through Build and Audit. Use `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py -k ontology_registry_editing`.

### Guardrail claims

- The browser operator surface rejects disabled, non-local, cross-origin, and unreviewed submissions before they can enqueue a mutation. Existing CLI decisions remain usable, and only the worker opens writable ontology databases or rollout copies.
- Publishing preserves the applied revision and graph. Adoption requires a distinct current plan and confirmation. Declining, replaying a completed confirmation, or using a stale, substituted, or invalid preview cannot change the registry or graph again.
- A stale or unrelated note cannot authorize a persisted change. A valid person or edge correction preserves canonical node identity, source files, and unrelated notes’ memberships and evidence.

### Supporting obligations

- Default to no browser registry authority. Enable it explicitly on a literal loopback bind, such as `serve --registry-actions` on `127.0.0.1`, and pass the configured local origin into the app. Check the actual local peer, exact allowed Host and Origin, and app opt-in on every operator preview/confirm request before enqueue. Reject proxied authority and do not infer it from client-controlled forwarding headers. Add no login service and leave existing note-reader authority unchanged.
- Use the existing `/ontology` record route for the controls. The proposed browser contract is `POST /api/ontology/registry/publish/preview`, `/publish/confirm`, `/apply/preview`, and `/apply/confirm`, under that common registry prefix. Review responses provide a diff and a server-issued opaque or integrity-protected confirmation reference bound to action, reviewed identity, and exact proposal or plan. Publish confirmation submits an inline validated full proposal reconstructed server-side from a whitelisted record field edit. Preserve the CLI proposal path contract and reject browser-supplied filesystem paths and job payloads.
- Queue the browser adoption preview through `ProcessingService` to the worker, where `plan_rollout` can inspect and repair its disposable copy. The completed preview provides a meaningful, bounded description of the exact plan, including affected linked rows or version-only adoption. Confirm only that completed plan and reuse the existing worker revision, digest, and outcome checks. Treat an approval reference as server-controlled, distinct by action, and unusable after it has succeeded or become stale. Job polling may expose progress and a safe diff, without treating a client-supplied job ID or plan as authorization.
- Company and theme field edits operate on the matching registry entry. Keep the live record on the applied values while the new published revision is pending. Only propagate unambiguous linked graph metadata changes when included in the same dry-run and worker apply plan. Show registry-only impact if there is no graph match, and surface ambiguity instead of silently choosing graph nodes or merging them. Preserve graph IDs and evidence, avoid replacing research-derived summaries or aliases outside the reviewed edit, and return to the canonical record after a rename.
- Use `POST /api/ontology/corrections/preview` and `/confirm` for record-originated note corrections, or the same reviewed contract at the existing note reader reached from the record. Bind the selected note content hash and current document ID, exact reviewed person fields and affected edge identity/revision, and the whitelisted replacement fields. Recheck them in the worker transaction. Continue using the existing local note-action gate and schema validators. A person correction changes the canonical person’s identity fields or role/organization without replacing the node. It updates only matching same-note employment evidence when those fields require it. Relationship changes preserve or update the selected note’s facets through the existing correction architecture and do not modify another note’s edge. Keep the permitted prior name as an alias when selected and test that a routine matching extraction does not undo the correction or create a second canonical node.

### Allowed scope

- Reuse: `web/ontology/{routes,views}.py`, the Registry partial and shell, `services/{registry,processing}.py`, CLI and worker governance contracts, note ownership and graph validators, and existing job polling and reference links.
- Cheaper alternative: Have the browser export a reviewed draft and retain final CLI-only decisions. It avoids a new operator surface, but cannot satisfy the explicitly approved local browser confirmations. Running preview repair within the web process is also ruled out by the existing module boundaries.
- Include: Local operator configuration and gated browser routes, stage-specific record UI, exact worker-backed registry previews and confirmations, bounded linked metadata rollout, and source-bound person and relationship corrections with scoped documentation, localization and tests. Add only the service, worker, or storage behavior those contracts need.
- Exclude/protect: Hosted operator login or privilege expansion, direct web database writes or worker imports, unattended adoption, arbitrary worker payloads or paths, graph merges, raw note rewrites, Schema changes, Audit/Suggestions and Run history redesign, and live execution. Retain accepted browse and legacy note and CLI regressions. Protect the independently authored witness through Audit.

### Invariants changed

- `README.md:162` and `services/registry.py::RegistryService` currently specify the operator CLI as the only registry confirmation surface. The approved increment adds an explicitly enabled local operator browser surface. The CLI and separate decisions remain supported and `tests/test_registry_governance.py::test_publish_and_apply_require_separate_interactive_decisions` remains green.
- `README.md:207–215` continues to govern relink semantics and relationship ownership. The new canonical person edit is a separate source-bound operation. It preserves note attribution, other notes’ evidence, and graph identity. No prior note-reader witness needs relaxation.
- The accepted Registry browsing, Schema defaults, and architecture rules continue without relaxation.

### Decisions required

- None.

## Proof

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main`. Reconstructed and verified the accepted browsing baseline at SHA-256 `cd6f89e27bafc6acaf1778584bff547c6d232e3ffd247ee357d08dd3194eba50` and the rejected R1 candidate at `70db6af01d39ea380434d4e4ced71078a92487d14270a9b6a9dedf90e6969057` before adding the revised witness to each.

**Protected witness**

- Separate company and theme publication and adoption: `tests/test_web.py::test_ontology_registry_editing_operator_two_decisions[company]` and `[theme]`.
  - Defect and boundary: The browser needs local operator authority and distinct review and confirmation steps before registry or graph writes reach the worker.
  - Assertion: The loopback client can publish a reviewed field diff while the applied registry, graph, and visible record retain their old values. A completed worker preview and separate confirmation apply the new values. Disabled, direct remote, forwarded, wrong-Origin, wrong-Host, and unreviewed requests fail before enqueue. Abandoning publication or adoption preserves state. A genuine adoption reference is withheld while queued and rejected if submitted early. The witness also exercises stale, forged, substituted, and replayed confirmations. Coverage is one linked detail field each for a company and theme.
- Note-backed person and existing relationship corrections: `tests/test_web.py::test_ontology_registry_editing_note_correction[person]`, `[relationship]`, `[wrong-owner]`, and `[stale-note]`.
  - Defect and boundary: Corrections must bind the reviewed graph edit to a valid supporting note and commit through the worker.
  - Assertion: The reviewed person role or relationship facet appears on the record and in the selected note’s facts. The worker preserves canonical IDs, other note memberships and evidence, and both source files. Another note cannot authorize an existing edge edit. A source file changed after submission invalidates the queued correction. Coverage is `WORKS_AT` evidence and a source-content race.
- New relationship source eligibility: `tests/test_web.py::test_ontology_registry_editing_relationship_add_source[source-options]`, `[unrelated-http]`, `[authorized]`, and `[ownership-race]`.
  - Defect and boundary: The rejected candidate offered an unrelated processed note, accepted it over HTTP, and could commit a reviewed relationship after the selected note lost its connection to the record.
  - Assertion: The form offers the related note only. HTTP preview rejects a note that contains neither endpoint. A valid review and confirmation add the relationship to the selected note while preserving the unrelated note’s membership, edges, and file. Removing the record’s sole membership after confirmation forces the worker to fail while source bytes and ingestion identity stay unchanged. Coverage is a person-anchored employment relationship.
- Optional details in browser edits: `tests/test_web.py::test_ontology_registry_editing_optional_details[company]` and `[person]`.
  - Defect and boundary: Built-in browser form validation blocks a valid ticker-only edit when sector is absent and a valid role-only edit when organization is absent.
  - Assertion: Each form renders the single-field edit control and a blank optional control without `required`. The real preview endpoint accepts the one-field edit and returns a diff omitting the blank field. A supplemental Chromium probe clicks Review and checks native form validity and visible review output. Coverage is a missing company sector and person organization.
- Protected path: `tests/test_web.py`. Every prior assertion remains.
- Protected revision: SHA-256 `99f5a857a3fdacd8cb9be4ccd507ae3481ff2131ba4a645302a1ef65fadb098b`. Retrievable artifact `/private/tmp/stock-ontology-editing-proof-r1/test_web.py`.

**Red evidence**

- In `/private/tmp/stock-ontology-editing-proof-r1/rejected` and then `/private/tmp/stock-ontology-editing-proof-r1/baseline`, `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache UV_PROJECT_ENVIRONMENT=/Users/jasonbxu/Documents/GitHub/stock_ontology/.venv PYTHONPATH="$PWD/src" uv run --offline --no-sync pytest -q tests/test_web.py -k ontology_registry_editing` → the unchanged rejected candidate had five expected failures and seven passes. It offered an unrelated note, returned HTTP 200 for the unrelated note review, committed after source ownership changed, and marked empty sector and organization inputs required despite successful single-field HTTP reviews. The accepted browsing baseline failed all 12 cases at the missing review routes with HTTP 404. Logs `/private/tmp/stock-ontology-editing-proof-r1/rejected.log` and `/private/tmp/stock-ontology-editing-proof-r1/baseline.log`.
- From each isolated copy named `remote-peer`, `publish-abandon`, `adopt-abandon`, and `early-confirm` under `/private/tmp/stock-ontology-editing-proof-r1`, `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache UV_PROJECT_ENVIRONMENT=/Users/jasonbxu/Documents/GitHub/stock_ontology/.venv PYTHONPATH="$PWD/src" uv run --offline --no-sync pytest -q 'tests/test_web.py::test_ontology_registry_editing_operator_two_decisions[company]'` → each negative control triggered its corresponding assertion. Removing direct peer enforcement allowed HTTP 200. Auto-publishing or auto-applying abandoned reviews ran a mutation job. Bypassing preview completion accepted the genuine early reference with HTTP 202. Logs `/private/tmp/stock-ontology-editing-proof-r1/remote-peer.log`, `publish-abandon.log`, `adopt-abandon.log`, and `early-confirm.log` in the same directory.
- In `/private/tmp/stock-ontology-editing-proof-r1/rejected`, `STOCK_ONTOLOGY_INCOMPLETE_FIXTURE=1 node ../browser-optional.mjs` → Chromium marked the empty sector and organization controls invalid. Clicking Review produced neither diff. Log `/private/tmp/stock-ontology-editing-proof-r1/browser-optional.log`.
- In the rejected candidate copy, `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache UV_PROJECT_ENVIRONMENT=/Users/jasonbxu/Documents/GitHub/stock_ontology/.venv PYTHONPATH="$PWD/src" uv run --offline --no-sync pytest -q tests/test_registry_governance.py::test_publish_and_apply_require_separate_interactive_decisions tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` → two passed. Log `/private/tmp/stock-ontology-editing-proof-r1/legacy-guards.log`.

**Supporting test plan**

- Registry-only and ambiguous graph matches → Build: `tests/test_worker.py`. Check that previews report both outcomes and leave ambiguous graph rows untouched.
- Routine extraction after person identity correction → Build: `tests/test_pipeline.py`. Check that a retained prior name resolves to the canonical person and ingestion preserves the correction.

## Build

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main`, SHA-256 `8bee59f7232d41f5780467f291a2d09d4b30b98ff4f1e43cb471132697da78e7`. The digest covers `git diff --binary --no-ext-diff --no-color HEAD -- README.md docs/architecture/governance.md docs/architecture/web.md src/stock_ontology tests`, followed by each sorted untracked path in that scope, a NUL delimiter, and its raw SHA-256 digest. Protected `tests/test_web.py` remains byte-identical at SHA-256 `99f5a857a3fdacd8cb9be4ccd507ae3481ff2131ba4a645302a1ef65fadb098b`.

### Files changed

- `src/stock_ontology/cli.py`, `src/stock_ontology/web/{app,shell}.py`, `src/stock_ontology/web/ontology/routes.py`. Add loopback-only browser operator authority, action-specific confirmations, and worker job submission. Preserve CLI confirmations.
- `src/stock_ontology/services/{registry,processing,corrections}.py`, `src/stock_ontology/worker.py`, `src/stock_ontology/db/storage.py`. Review and bind company and theme proposals, worker rollout plans, and note-backed corrections before writes. R1 binds new relationships to the selected note’s evidence for the anchor record. The worker’s fresh review checks that evidence again before committing.
- `src/stock_ontology/web/ontology/views.py`, `src/stock_ontology/web/templates/ontology.html`, `src/stock_ontology/web/templates/partials/{ontology_registry,ontology_edit_forms}.html`, `src/stock_ontology/web/static/{ontology_edit.js,library.css}`, `src/stock_ontology/locales/{en,es,fr,ja,ko,zh}.json`. Expose field-level edits, pending publication state, and separate adoption review. R1 limits Add relationship sources to notes connected by membership, the record’s source document, or sourced non-synthesized incident evidence. Blank legacy details do not block unrelated one-field reviews.
- `tests/test_worker.py`, `tests/test_pipeline.py`. Cover rollout resolution, CLI publication separation, loopback startup, retained person identity after extraction, and theme source eligibility.
- `README.md`, `docs/architecture/{governance,web}.md`. Document local operator checks, worker-owned review, and relationship source eligibility.

### Unit evidence

- `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_worker.py -k relationship_sources_include_theme`. RED before R1 because synthesized and unrelated notes appeared in the picker. Log: `/private/tmp/ontology-registry-editing-r1-theme-red.log`.
- `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_worker.py tests/test_pipeline.py -k 'browser_registry_edit_rollout or registry_person_identity_correction or browser_registry_preview or serve_registry_actions or relationship_sources_include_theme'`. GREEN, 6 passed. Log: `/private/tmp/ontology-registry-editing-r1-support-green.log`.

### Green evidence

- Protected witness: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py -k ontology_registry_editing`. 12 passed. Log: `/private/tmp/ontology-registry-editing-r1-witness.log`.
- Focused gate: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py tests/test_worker.py tests/test_pipeline.py tests/test_web_navigation.py tests/test_i18n.py tests/test_registry_governance.py tests/test_architecture.py -k 'registry or ontology or relationship or relink or only_worker or follow_layers or breakpoint'`. 50 passed. Log: `/private/tmp/ontology-registry-editing-r1-focused.log`.
- Full offline suite: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q`. 539 passed. Log: `/private/tmp/ontology-registry-editing-r1-full.log`.
- Targeted Ruff, `node --check src/stock_ontology/web/static/ontology_edit.js`, and `git diff --check` passed.
- The orchestrator’s disposable Chromium fixture verified a ticker-only company edit with blank sector through publication and adoption, a role-only person correction with blank organization, an independent relationship correction, and rendering at 390px.

### Intervention record

- None. Verification used disposable fixtures.

### Deviations

- None.

## Audit

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main, /Users/jasonbxu/Documents/GitHub/stock_ontology, SHA-256 8bee59f7232d41f5780467f291a2d09d4b30b98ff4f1e43cb471132697da78e7`

Independence: fresh-context. This context audited the first candidate and authored neither candidate nor either protected witness.

Primary-claim verdict: PROVED. The protected `tests/test_web.py` cases verify separate publication and adoption for company and theme edits, plus note-backed person and relationship edits that appear on the Registry record. Chromium independently verified ticker-only and role-only reviews with blank sector and organization fields. Coverage is limited to the seeded fields and relationships.

Guardrail verdicts:

- Browser operator authority, CLI compatibility, and worker-only writes: PROVED. The protected operator cases independently check a direct non-loopback peer, forwarded requests, disabled actions, missing or mismatched Origin and Host, and unreviewed requests. The isolated direct-peer negative control failed at the intended check. The CLI confirmation and worker-only database architecture tests passed. Coverage is limited to the supported loopback launch and tested request shapes.
- Separate publication and adoption: PROVED. The protected cases verify that publication leaves the applied registry and graph intact. Abandoned reviews preserve state, and the candidate rejects early, substituted, stale, and replayed confirmations. The three isolated controls for automatic publication, automatic adoption, and early confirmation failed at the intended checks. Staleness coverage uses a graph change after preview.
- Source-bound corrections and preservation of unrelated evidence: PROVED. The revised protected tests verify that the source picker omits unrelated notes, HTTP review rejects them, and the worker fails a queued addition if its note loses the record association. Valid edits preserve canonical IDs, unrelated note evidence, and source files. The supporting theme test verifies direct source, membership, and extracted incident evidence, and excludes synthesized and unrelated sources. The worker race uses person membership, and the theme test ends at review.

Scope and duty verdict: scope HELD, duties HELD. R1 corrects the reviewed source boundary and optional-field forms within the approved editing paths. The first witness’s assertions remain in the revised witness, the accepted browse and Schema surfaces retain their tests, and the README records the source rule with an existing guard. The comparison is limited to the scoped candidate fingerprint and accepted browsing baseline.

Test homes: `tests/test_web.py` owns browser-to-worker integration, `tests/test_worker.py` owns rollout, launch, and source-provenance integration, and `tests/test_pipeline.py` owns identity preservation through matching extraction. The protected file matches the retrieved SHA-256 `99f5a857a3fdacd8cb9be4ccd507ae3481ff2131ba4a645302a1ef65fadb098b`.

Full gates: PASS. Independently ran `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q` with 539 passed. The focused suite passed 50 cases, and `pytest -q tests/test_web.py -k ontology_registry_editing` passed all 12 protected cases. The archived baseline reproduced 12 expected failures, the rejected candidate reproduced five, and all four operator negative controls failed at their intended assertions. Scoped Ruff, `node --check src/stock_ontology/web/static/ontology_edit.js`, and `git diff --check` passed. All writes during verification used disposable fixtures.

Residual risks:

- The witnesses cover representative company and theme fields and seeded note evidence. Coverage of the source-association race uses membership removal.

Recommendation: ACCEPT

Packet: Record this verdict against the verified R1 fingerprint and update the R1 revision entry and ledger state.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->

### R1 — 2026-11-24 — Source eligibility, partial edits, and operator guard evidence
- Verdict: REVISE — Relationship addition could use a note with no connection to the record. Blank unrelated fields could block valid browser edits. The witness did not independently establish direct non-loopback denial, a review abandoned without confirmation, or an incomplete adoption preview.
- Changed: `tests/test_web.py` independently proves the operator guards, note eligibility and worker race, and legacy optional-field behavior. `services/corrections.py` and `web/ontology/views.py` share and recheck source eligibility. `ontology_edit_forms.html` supports one-field edits on valid incomplete records. Worker coverage includes theme source eligibility.
- Re-audit: ACCEPT — All 12 protected cases passed on candidate `8bee59f7232d41f5780467f291a2d09d4b30b98ff4f1e43cb471132697da78e7`; independently rechecked proof, source eligibility, optional-field browser behavior, and all 539 offline tests.
