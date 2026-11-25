---
proposal_id: "author-accuracy"
state: ACCEPTED
witness: independent
candidate: "ce3a230 + working tree d9e4dc19 @ main checkout"
---

# Proposal: Author accuracy facet for weighting rumors

## Proposal

### Intent

Add a facet to authors or people that indicates their level of accuracy. Some
writers aren't always accurate, so rumors written by these authors should be
weighted with that in mind.

### Tentative primary claim

A rumor written by an author whose accuracy facet marks them as less accurate is
weighted lower than the same kind of rumor written by a more accurate author.

### Why now

None stated.

### Known constraints

None stated.

### Non-goals

None stated.

### Open choices

- Whether the facet belongs on authors only, or on people in general.
- What the accuracy levels are, for example a few named levels or a number.
- Who sets an author's accuracy: a person by hand, or something derived from how
  that author's past rumors turned out.
- What an author with no accuracy recorded gets by default.
- Where the weighting shows up: in the stored ontology, in what the query agent
  says, in how the app ranks or displays rumors, or some combination.
- Whether the weighting applies only to rumors or to everything the author
  writes.
- Sequence: whether recording the facet ships before, or together with, using it
  to weight rumors.

## Frame

Candidate: `ce3a230 @ main checkout /Users/jasonbxu/Documents/GitHub/stock_ontology` (untracked proposal ledgers only)

### Verified reality
- `uv run pytest -q` before any change — proves the offline suite is green at the candidate: `543 passed in 19.26s`; limit: says nothing about live LLM behavior.
- `src/stock_ontology/vocab.py:28` and `ontology_registry.json` `facet_schema.node.view` — prove a rumor is a `view` node with `view_type: rumor`; limit: none relevant.
- `ontology_registry.json` `relations` (`AUTHORED_BY`) and `src/stock_ontology/llm/prompts.py:132` — prove extraction links a view to its author as `view --AUTHORED_BY--> person|institution`; limit: does not prove every rumor gets an author edge.
- `ontology_registry.json` `facet_schema.node["entity:person"]` — proves a person is an `entity` with `entity_type: person`, required text facets `role` and `organization`, and no accuracy facet; undeclared facets pass through (`src/stock_ontology/registry.py:514` `check_facets`, README.md:31); limit: none.
- `src/stock_ontology/llm/prompts.py:33`, `:83`, and a read-only count of the local `ontology.db` — prove people already carry a free-form, LLM-set `credibility` (`high|medium|low`) taken from how a note describes them (19 of 28 local people); limit: it is the note's self-description, which the human ruled is not our view of the author.
- `src/stock_ontology/pipeline.py:236` `_resolve_canonical_node` — proves ingest keeps an existing node's non-empty facets and adds only missing keys from the extraction; limit: an extraction could still set a key the stored node lacks.
- `src/stock_ontology/llm/prompts.py:148` `CONSENSUS_SYSTEM_PROMPT` — proves the only place the system weighs rumors is consensus synthesis, by LLM judgment; limit: no computed score exists.
- `src/stock_ontology/llm/prompts.py:196` `build_consensus_prompt` and `src/stock_ontology/pipeline.py:721` `_rebuild_company_consensus` — prove synthesis receives each view's id, name, summary and facets, and no author; limit: none.
- `src/stock_ontology/services/corrections.py:16` `_PERSON_FIELDS`, `:106`, and `src/stock_ontology/worker.py:536` — prove the app edits a person's `name`, `aliases`, `role`, `organization` through a note-correction job scoped to a note the person appears in, which refreshes consensus only for companies affected by that note; limit: no other person-edit path exists.
- `src/stock_ontology/web/notes/views.py:706` — proves the note page already builds per-person edit data (`role`, `organization`, `credibility`); limit: the matching form and script were not traced line by line.

### Final primary claim
- When consensus is synthesized for a company, each linked rumor whose author is a person carries that author's accuracy (`high`, `medium`, `low`, or `unrated`) in the synthesis input, and the synthesis instructions say to weigh rumors from less accurate authors lower and to treat `unrated` as today.

### Routing
- Witness: `independent`
- Why: it adds an official facet on stored person nodes, an app write path for it, and changes consensus synthesis input, which is stored data and the core ingest-to-consensus lifecycle.
- Human-owned irreversible action: merging, deploying to the production server, publishing and applying the registry change there, and setting accuracy on live people.

### Decisive witness
- Layer: offline pipeline test with the fake LLM client, through the real `build_consensus_prompt`.
- Permanent owner: `tests/test_pipeline.py`.
- Witness: for a company with a rumor `AUTHORED_BY` a person whose `accuracy` is `low`, a second rumor by an unrated person, and an analyst report by a rated person, the built consensus input shows `low` for the first rumor, `unrated` for the second, no author accuracy on the analyst report, and the system prompt states the weighting rule.

### Guardrail claims
- Re-ingesting a note that mentions a person never sets or changes that person's `accuracy`, whatever the extraction returns.
- A person's `accuracy` set through the app is stored, checked against `high|medium|low` (or cleared), and refreshes consensus for every company with a rumor by that person.
- The LLM-set `credibility` facet is unchanged and plays no part in the new weighting.

### Supporting obligations
- Declare `accuracy` as an optional enum on `entity:person` in `ontology_registry.json` (`facet_vocabularies`, `facet_schema`) and the matching `Vocabulary` in `src/stock_ontology/vocab.py`, so existing people stay valid and the vocabulary check passes.
- Drop `accuracy` from extracted facets before ingest writes them.
- Add `accuracy` to the person correction (`_PERSON_FIELDS`, review diff, worker write) and the note page's person edit form, with locale keys in all six locales.
- Pass rumor authors into consensus synthesis and extend `CONSENSUS_SYSTEM_PROMPT`.
- Unit-test candidates: vocabulary rejects other values; extraction cannot set it; correction review and write; consensus refresh reaches companies outside the note.

### Allowed scope
- Reuse: registry `facet_schema` and `facet_vocabularies`; `AUTHORED_BY` edges; `build_consensus_prompt`; the note-correction person edit and its web form; existing `tests/test_pipeline.py`, `tests/test_web_notes.py`, `tests/test_i18n.py` owners.
- Cheaper alternative: reuse the existing `credibility` facet. Rejected by the human: it is the note's self-description, not our view of the author. Also rejected: hand-editing the database, since only the worker writes and the scale would be unchecked.
- Include: the obligations above, the README.md facet-schema sentence, and tests.
- Exclude/protect: no computed rumor score; no change to the query agent or to app ranking or display beyond the person edit form; no institution accuracy; no use of `credibility`; no change to non-rumor views; no live data, registry publish, or deploy.

### Invariants changed
- `README.md:31` — today: "The shipped registry requires `role` and `organization` on a person" and no other person facet is official; after: a person also has an optional official `accuracy` enum (`high|medium|low`) that only a person sets, through the app.

### Decisions required
- None.

Human decisions recorded 2026-11-25: accuracy is set by hand in the app; scale `high|medium|low`; an unrated author is shown as `unrated` and weighed as today; weighting applies in consensus synthesis only; rumors only; people only; a new `accuracy` facet separate from the LLM-set `credibility`.

## Proof

Candidate: `ce3a230 @ main checkout /Users/jasonbxu/Documents/GitHub/stock_ontology` (untracked proposal ledgers only, plus the witness additions to `tests/test_pipeline.py`)

**Protected witness**
- Primary claim, rumor author accuracy in the consensus synthesis input plus the weighting rule. Witness: `tests/test_pipeline.py` / `test_consensus_input_carries_rumor_author_accuracy_and_weighting_rule`
  - Defect and boundary: consensus synthesis gets each view's id, name, summary and facets but never the view's author, and `CONSENSUS_SYSTEM_PROMPT` says nothing about author accuracy. The witness covers ingest, the stored graph, and the prompt sent to the provider. It uses the real `IngestionPipeline.run(rebuild_consensus=True)`, the real `BaseLLMProvider.synthesize_consensus`, `build_consensus_prompt` and `CONSENSUS_SYSTEM_PROMPT`, the shipped `ontology_registry.json`, and an offline provider whose `generate_structured` records the request.
  - Assertion: the test sets accuracy on stored people, standing in for the app. In the outgoing consensus prompt, the JSON entry for the rumor by the `low` person (whose note credibility is `high`) carries `accuracy` `{"low"}`. The rumor by the unrated person (whose note credibility is `low`) carries `{"unrated"}`. The analyst report by the `high` person carries no `accuracy` key at any depth. The system instruction contains "accuracy" and "unrated". This proves the primary claim, and also guardrail 3 (credibility plays no part).
  - Limit: Build must put the accuracy inside each view's JSON entry, under an `accuracy` key at any depth, keyed by the view's `id`. A separate author table would not match. The system-prompt check tests wording, not the model's actual weighting.
- Guardrail 1, re-ingest never sets or changes accuracy. Witness: `tests/test_pipeline.py` / `test_reingest_never_sets_or_changes_person_accuracy`
  - Defect and boundary: an extracted person facet named `accuracy` passes through to the stored node, because undeclared facets pass and `_resolve_canonical_node` adds missing keys. The witness covers ingest of the extraction and the stored person node, with the shipped registry.
  - Assertion: an extraction that claims `accuracy=high` leaves the new stored person with no `accuracy`. After the test sets `low` and a changed note is re-ingested with the same claim, the stored value stays `low`. This proves guardrail 1.
  - Limit: it covers the `extract_document` path. It does not cover staged extraction or merges by registry alias.
- Guardrail 2, an app-set accuracy is checked, stored, clearable, and refreshes every company with a rumor by that person. Witness: `tests/test_pipeline.py` / `test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors`
  - Defect and boundary: `review_note_correction` only allows `name`, `aliases`, `role` and `organization` on a person, and consensus refresh only reaches companies in the correcting note. The witness covers the app's correction service, the job queue (`ProcessingService.submit_correction` with `note.ontology.correction`), the worker write, the stored graph and the job result, with the shipped registry.
  - Assertion: the correction is submitted from the Acme note. A person correction `{"accuracy": "low"}` succeeds and stores `low`. The person's `credibility` stays `high`. The job result `consensus_updated_for` includes both "Acme Widgets" and "Beta Gears", and Beta's rumor by that person lives only in another note. `{"accuracy": "excellent"}` raises `ServiceError` at review. `{"accuracy": None}` succeeds and leaves no `accuracy` key. This proves guardrail 2 and the "credibility unchanged" half of guardrail 3.
  - Limit: it tests the service and worker that the web routes call, not the HTTP route, the person edit form markup, or locale strings. Those are supporting obligations. Clearing is fixed as a JSON null value in `changes`.
- Protected paths: `tests/test_pipeline.py` (the appended "Author accuracy" block with its helpers `_person`, `_company`, `_authored_view`, `_extraction`, `_set_person_facets`, `_json_entries_with_id`, `_accuracy_values` and `_ConsensusWireProvider`, plus the three tests above).
- Protected revision: `work/author-accuracy/proof-witness.patch` (a `git diff -- tests` against ce3a230), sha256 `53f96addbb4f4a4217f872dbceafe48453f6d9d1b1046f4adbc14fec3e2299d1`. `work/` is gitignored.

**Red evidence**
- `uv run pytest tests/test_pipeline.py -v -k "test_consensus_input_carries_rumor_author_accuracy_and_weighting_rule or test_reingest_never_sets_or_changes_person_accuracy or test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors"` → 3 failed, 31 deselected; log: `work/author-accuracy/proof-red.log`.
  - Primary: `a rumor must carry its author's accuracy`, `assert set() == {'low'}`.
  - Guardrail 1: `extraction must not set a person's accuracy`; stored facets contain `'accuracy': 'high'`.
  - Guardrail 2: `ServiceError: Choose person details or identity fields.` from `review_note_correction`.
- Full suite `uv run pytest -q`: 3 failed (exactly these witnesses), 543 passed. Orchestrator re-ran the focused command and the patch hash on the same tree: 3 failed, hash matches.

**Supporting test plan**
- Declare `accuracy` as an optional `high|medium|low` enum on `entity:person` in `ontology_registry.json` and `vocab.py` → Build: `tests/test_official_facets.py` and the registry and vocabulary tests; catches existing people becoming invalid, or other values accepted.
- Person edit form field and locale keys in all six locales → Build: `tests/test_web_notes.py` / `tests/test_web_ontology.py` and `tests/test_i18n.py`; catches a missing form control or untranslated labels.
- Staged extraction path also dropping `accuracy` → Build: `tests/test_staged_extraction.py`; catches the guard applied only on the single-call path.

## Build

Candidate: `ce3a230 + uncommitted working tree @ main checkout /Users/jasonbxu/Documents/GitHub/stock_ontology`; `git diff HEAD -- . ':!docs' | shasum -a 256` = `d9e4dc198d8224925177c28546991df29904e17359d9ec3c25361c9fe14bc3dd`

### Files changed

- `src/stock_ontology/vocab.py` — `ACCURACY` vocabulary (`high|medium|low`, no fallback) under `NODE_FACET_VOCABS["entity"]` and `ALL_VOCABS`; supports the official facet.
- `ontology_registry.json` — `facet_vocabularies.node.entity.accuracy` (generated from code's spec) and `facet_schema.node["entity:person"].accuracy` as an optional enum.
- `src/stock_ontology/pipeline.py` — the entity loop drops `accuracy` from extracted facets (guardrail 1, both extraction paths). `_with_rumor_authors` gives each rumor's synthesis copy, never stored, `facets.authors` with each person author's `accuracy` or `unrated` (primary claim).
- `src/stock_ontology/llm/prompts.py` — `CONSENSUS_SYSTEM_PROMPT` states the weighting rule and that `unrated` means no adjustment (primary claim).
- `src/stock_ontology/services/corrections.py` — `accuracy` added to `_PERSON_FIELDS`. It is checked against the vocabulary (`service_error.choose_accuracy`), and blank or null clears it. When it changes, the payload lists `rumor_company_ids` for every company the person's rumors touch (guardrail 2).
- `src/stock_ontology/worker.py` — the person correction write adds `rumor_company_ids` to the consensus refresh set (guardrail 2).
- `src/stock_ontology/web/templates/partials/ontology_edit_forms.html`, `src/stock_ontology/web/ontology/views.py` — the person "Edit details" form gets an accuracy select (Unrated, high, medium, low) with the current value selected (approved scope expansion, see Deviations).
- `src/stock_ontology/locales/{en,zh,ja,ko,fr,es}.json` — `facet.accuracy`, `enum.accuracy.*`, `ontology_edit.accuracy_unrated`, `service_error.choose_accuracy`.
- `README.md` — line 31 rule updated as Frame's `Invariants changed` states. One constraint entry added under Ingestion Constraints (drop extracted `accuracy`, refresh every rumor's company), with Why and Guarded by.
- `tests/test_vocab.py` — `accuracy` exempted from the base-schema enum check (like `confidence`) and from the "every entity-type facet is required text" check, plus an assertion that the person layer declares it as an optional enum (approved scope expansion).
- `tests/test_official_facets.py`, `tests/test_web_ontology.py`, `tests/test_staged_extraction.py` — supporting unit tests from Proof's plan.

### Unit evidence

- Protected witness unchanged: `git diff -- tests/test_pipeline.py | shasum -a 256` = `53f96addbb4f4a4217f872dbceafe48453f6d9d1b1046f4adbc14fec3e2299d1`, which matches Proof's protected revision.
- `uv run pytest -q` after the registry and vocab change → RED: `tests/test_vocab.py` 2 failed (the two rules above), then GREEN after the approved test edit: `134 passed`.
- `uv run pytest tests/test_official_facets.py -q -k accuracy` → GREEN: `test_person_accuracy_is_an_optional_official_enum` passes (accepts absent and `LOW`→`low`, rejects `excellent`).
- `uv run pytest tests/test_web_ontology.py -q -k accuracy` → GREEN: `test_person_details_form_edits_accuracy` passes (select rendered with `medium` selected and an Unrated option; preview diff `medium`→`low`; blank clears; `excellent` refused).
- `uv run pytest tests/test_staged_extraction.py -q -k accuracy` → GREEN: `test_staged_extraction_cannot_set_a_person_accuracy` passes. It was written after the pipeline guard, so no RED was observed for it.

### Green evidence

- Decisive witness: `uv run pytest tests/test_pipeline.py -v -k "test_consensus_input_carries_rumor_author_accuracy_and_weighting_rule or test_reingest_never_sets_or_changes_person_accuracy or test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors"` → 3 passed, 31 deselected; log: `work/author-accuracy/build-witness.log`.
- Gate: `uv run pytest -q` → 549 passed; log: `work/author-accuracy/build-gate.log`.
- Lint: `uv run ruff check src tests --output-format concise` → 46 findings before and after, with identical sets; logs: `work/author-accuracy/ruff-before.txt`, `work/author-accuracy/ruff-after.txt`. No new findings.

### Intervention record

- None: the repository keeps no intervention ledger, and no live outcome is measured until a human deploys and rates authors.

### Deviations

- Scope expansion, approved by the human in chat on 2026-11-25 before the edits: `tests/test_vocab.py`, because two existing tests encoded "every node enum is in code's base schema" and "every `entity:person` facet is required text", which the approved Proposal overrides. Frame did not list them under `Invariants changed`.
- Scope expansion, approved by the human in chat on 2026-11-25 before the edits: `src/stock_ontology/web/templates/partials/ontology_edit_forms.html` and `src/stock_ontology/web/ontology/views.py`. Frame named "the note page's person edit form", but the person edit form lives on the ontology record page.
- Residual: the consensus input puts authors under the rumor's `facets` key (`facets.authors`) in a copy that is never stored, rather than in a new top-level field. Changing the `synthesize_consensus` signature would have broken about 15 test fakes outside scope.

## Audit

Candidate: `ce3a230 + uncommitted working tree @ main checkout /Users/jasonbxu/Documents/GitHub/stock_ontology`. `git diff HEAD -- . ':!docs' | shasum -a 256` = `d9e4dc198d8224925177c28546991df29904e17359d9ec3c25361c9fe14bc3dd`, the same tree audited before. The witness diff hash `53f96addbb4f4a4217f872dbceafe48453f6d9d1b1046f4adbc14fec3e2299d1` still matches Proof. The gates were not rerun because the tree is unchanged.

Independence: fresh-context. This is the same audit context as the first REVISE. It never authored or built the candidate.

Primary-claim verdict: PROVED. `tests/test_pipeline.py::test_consensus_input_carries_rumor_author_accuracy_and_weighting_rule` is protected and unedited. It was RED at ce3a230 and passes now (`work/author-accuracy/audit-witness.log`). Limit: it checks prompt wording, not live model weighting.

Guardrail verdicts:
- Re-ingest never sets or changes accuracy: PROVED. The protected witness passes, and the staged-path supporting test passes. Limit: the staged test was never seen RED, and alias merges are not exercised.
- App-set accuracy is checked, stored, clearable, and refreshes every rumor's company: PROVED. The protected witness passes. Limit: the HTTP apply path is not exercised, and the web test covers preview only.
- `credibility` is unchanged and plays no part: PROVED. No new code reads it. The existing "high-credibility primary channel checks" prompt line is unchanged.

Scope and duty verdict: scope HELD; duties HELD. R1 records the human's approval of exactly the three expansion paths, made before the edits. Every other change maps to a Frame obligation. The README invariant and the constraint entry are correct. Limit: the approval lives in Revisions, not in an amended Frame.

Test homes: `tests/test_pipeline.py`, `tests/test_official_facets.py`, `tests/test_staged_extraction.py`, `tests/test_web_ontology.py`, `tests/test_vocab.py` (approved under R1).

Full gates: PASS on this tree. `uv run pytest -q` 549 passed (`work/author-accuracy/audit-gate.log`). The focused witnesses: 3 passed. Ruff: the same 46 pre-existing findings (`work/author-accuracy/audit-ruff.txt`). These runs are offline only.

Residual risks: weighting depends on how the LLM reads the prompt and is not measured. `facets.authors` is on a synthesis-only copy and would leak if a future change persisted it. `_rumor_company_ids` refreshes companies linked by any relation, which can cause extra refreshes but misses none. The live rollout is human-owned.

Recommendation: ACCEPT

Packet: none. ACCEPT does not authorize merging, deploying, publishing or applying the registry, or rating live people.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->

### R1 — 2026-11-25 — Scope expansions approved only in Build's text
- Verdict: REVISE. `tests/test_vocab.py` (two existing tests encoding "every node enum is in code's base schema" and "every `entity:person` facet is required text") and the person edit form at `src/stock_ontology/web/templates/partials/ontology_edit_forms.html` and `src/stock_ontology/web/ontology/views.py` are outside Frame's text. The human's approval was recorded only by the builder.
- Changed: ledger only, with no code or test change. The orchestrator records the approval here. On 2026-11-25, during Build and before those edits, the human was asked to approve exactly these three paths. The question named both `tests/test_vocab.py` rules and named the ontology record page form as the real location of the person edit form Frame meant. The human chose "Approve all three". The candidate is unchanged: `git diff HEAD -- . ':!docs' | shasum -a 256` = `d9e4dc198d8224925177c28546991df29904e17359d9ec3c25361c9fe14bc3dd`.
- Re-audit: requested from the same fresh audit context on candidate `ce3a230 + working tree d9e4dc19`. Its verdict replaces the Audit section.
