---
proposal_id: "ontology-registry-and-schema"
state: ACCEPTED
witness: builder
candidate: "93240d44e29d67595d36bf3fe21d135d45506479 @ main, /Users/jasonbxu/Documents/GitHub/stock_ontology, application/test/README SHA-256 cd6f89e27bafc6acaf1778584bff547c6d232e3ffd247ee357d08dd3194eba50"
---

# Proposal: Ontology Registry and Schema

## Proposal

### Intent

Implement the Registry and Schema sections of the Ontology page shown in `work/ontology-tab.html`. In Registry, users can search the Companies, Themes, and People tabs and open a record with a breadcrumb, details, name and aliases, and any relationships they can inspect or act on. Each edit action opens the fields in its own section. Company and theme edits follow the registry review, publish, and apply flow. Person corrections and relationship changes link to their supporting notes.

Schema is where users inspect shared node and relationship definitions, including required fields, allowed endpoints, and direction.

### Tentative primary claim

From the Ontology page, users can find and edit a company, theme, or person in Registry and inspect the shared rules for those records and their relationships in Schema.

### Why now

The requester is ready to move the mockup into the product. The design work clarified where edits belong, where shared definitions belong, and which information helps users complete a task.

### Known constraints

Start with the basic task on each screen and add an element only if it helps users find a record, understand it, or act on it. Use **Ontology → Registry → record** as the breadcrumb without a separate back link. Show provenance where it supports inspection or correction. Keep shared schema definitions in Schema.

### Non-goals

Implementing the Suggestions and Run history sections of the mockup in this phase.

### Open choices

None on sequencing. The requester approved delivering Registry and Schema browsing with source links first, then editing.

## Frame

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main, /Users/jasonbxu/Documents/GitHub/stock_ontology, application source at HEAD with the approved sequencing recorded in the ledger`. Mockup reference: `work/ontology-tab.html`, SHA-256 `b0e2cb88fa07fc4b225a51dbd4e3d15916013b7126109d075b391a00b2ae6d32`.

### Verified reality

- `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py tests/test_web_navigation.py -k ontology` passed before implementation, 11 passed and 99 deselected. This covers existing ontology and navigation behavior. It does not exercise the proposed browse experience.
- `src/stock_ontology/web/ontology/routes.py::build_router` registers the existing `GET /ontology` and opens the graph through `WebShell`. `web/ontology/views.py::_build_registry_view` already maps official company and theme entries to zero or more graph records. `build_ontology_context` exposes entity nodes and their subtypes. This provides the authoritative browse inputs. It does not establish a one-to-one registry-to-graph mapping or a distinct People tab.
- `src/stock_ontology/registry.py::OntologyRegistry._facet_specs`, `RelationSpec`, `CompanySpec`, `ThemeSpec`, and the registry resolvers define layered facet requirements, direction, endpoints, aliases, and how names resolve. These support the Schema display and alias lookup. Official company and theme entries have no durable record ID. This increment can use existing resolver-backed labels without adding persistent IDs.
- `src/stock_ontology/db/storage.py::get_incident_edges` exposes edge `source_doc_id` values. `web/research/views.py::_exposure_notes` demonstrates resolving a relationship's source document into a note citation. `web/notes/routes.py::catalog_page` and `web/notes/views.py::safe_return_path` already accept a note path and a same-site return destination. These permit genuine source links without a second note reader. They do not establish that every edge has a reachable source.
- `src/stock_ontology/web/navigation.py::_ontology` and `tests/test_web_navigation.py:58` bind explicit ontology tabs and the current default to navigation state. `tests/test_web.py:787`, `:1151`, `:1187` and `:1198` record the current default explorer, combined Registry content and Audit route. They establish which behaviors have to remain reachable when the new design changes the landing and moves definitions.

### Final primary claim

- From Ontology, users can search Companies, Themes, or People, open the intended record, follow its available relationship evidence to the existing note reader and back, and inspect shared rules in Schema.

### Routing

- Witness: `builder`.
- Why: This increment changes read-only presentation and same-site links using existing registry, graph, and note-reader contracts. It adds no storage, writes, or service operations.
- Human-owned irreversible action: Merge and deploy the resulting candidate. This stage performs neither.

### Decisive witness

- Layer: Offline web HTTP integration against a temporary registry, graph, and note file with a fake LLM.
- Permanent owner: `tests/test_web.py`.
- Witness: From Registry, follow links from a company ticker or alias hit, a theme alias hit, and a graph-person hit to their respective record displays. Follow a relationship's valid source link to the seeded note and verify its return link restores the record. Follow Schema and check an inherited required field and a relationship's declared direction and allowed endpoint types. Use the focused command `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py -k ontology_registry_schema` for the new witness.

### Guardrail claims

- Existing explicit ontology explorer and Audit URLs retain their content and filters, and existing entity, theme, and note URLs remain valid.
- Browsing leaves the graph, official registry, and notes unchanged.
- Registry entries without graph matches and records or edges without available note sources remain readable, with no broken source links or fabricated evidence.

### Supporting obligations

- Build the browse records from official registry companies/themes and graph people. Reuse registry resolver and audit match results for record lookup, including zero and multiple graph matches. Preserve the selected Registry tab and search query in the record breadcrumb. Avoid passing arbitrary external URL or filesystem paths to the note reader.
- Use real registry facet layers, vocabulary, relationship domains, ranges, and symmetry for Schema. Preserve the existing distinction between published definitions and the applied graph where they differ. Keep observed graph counts and deviations in their existing explorer or Audit surfaces.
- Keep the recognizable browse hierarchy from the mockup: task-first tabs, record details and aliases, relationships with meaningful source links, and the single **Ontology → Registry → record** breadcrumb. Reuse shell navigation and localized labels.
- Preserve `#structure-explorer` as a usable fragment on compatible destinations. Verify the old explicit explorer and Audit cases with `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py tests/test_web_navigation.py -k ontology`.

### Allowed scope

- Reuse: `web/ontology/{routes,views}.py`, `web/navigation.py`, the existing ontology template and `library.css`, `OntologyRegistry`, `GraphStore`, and the canonical note reader URL with its existing return-path check.
- Cheaper alternative: Link official registry rows straight to existing research pages. That misses official entries with no graph node and does not deliver Registry record breadcrumbs or evidence return context. Same-route read-only browse views are sufficient.
- Include: Registry and Schema presentation, searches and links served by `/ontology`, navigation and related locale keys, focused tests, and matching documentation only if needed. Move shared relationship and facet definitions out of the Registry browse surface while keeping them reachable in Schema.
- Exclude/protect: All worker and mutation paths, publish/apply and edit controls for this increment, new registry identifiers or migrations, redesign of the Audit/Suggestions or Run history workflows, and changes to existing research pages or the note reader contract. No witness is protected for this builder route.

### Invariants changed

- `tests/test_web_navigation.py:58` and `tests/test_web.py:787` and `:1151`. Today `/ontology` opens the Entity explorer with its overview. Afterward it opens Registry as in the approved mockup. The existing overview and Entity explorer remain reachable at explicit `?tab=entity`.
- `tests/test_web.py:1187`. Today `?tab=registry` combines official company and theme rows and shared relation and facet definitions. Afterward it opens the Registry record browser. The shared definitions remain available under Schema, and existing research detail URLs remain reachable. The explicit Audit and other explorer expectations continue to apply.
- `tests/test_web.py::test_web_multilingual_pages_preserve_original_notes`, lines 926–932. Today the test verifies localized legacy structure headings and the stored facet `custom_metric` through bare `/ontology`. Afterward the same status, translation, and stored-facet assertions run through explicit `/ontology?tab=entity`, which retains the legacy explorer when Registry becomes the default.

### Decisions required

- None for the approved browsing increment. The follow-on editing increment must frame its write and confirmation behavior separately.

## Proof

Builder route. The decisive witness in Frame is builder-owned and deferred to Build. No witness path is protected.

## Build

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main, /Users/jasonbxu/Documents/GitHub/stock_ontology, application/test/README SHA-256 cd6f89e27bafc6acaf1778584bff547c6d232e3ffd247ee357d08dd3194eba50`. The digest covers `git diff --binary --no-ext-diff --no-color HEAD -- README.md src/stock_ontology tests`, followed by each sorted untracked path in that scope, a NUL delimiter, and its raw SHA-256 digest.

### Files changed

- `src/stock_ontology/web/ontology/routes.py`, `src/stock_ontology/web/ontology/views.py`, `src/stock_ontology/web/navigation.py`. Open Registry by default, add searchable company, theme, and people records, and expose published Schema definitions. Retain explicit legacy explorer and Audit views. Relationship citations now require the note reader’s normalized lookup to resolve to the same file as the logged source.
- `src/stock_ontology/web/templates/ontology.html`, `src/stock_ontology/web/templates/partials/ontology_registry.html`, `src/stock_ontology/web/templates/partials/ontology_schema.html`, `src/stock_ontology/web/static/library.css`. Render Registry and Schema within the existing shell and mobile breakpoint.
- `src/stock_ontology/locales/{en,es,fr,ja,ko,zh}.json`. Localize new user-visible labels.
- `tests/test_web.py`, `tests/test_web_navigation.py`. Add the decisive witness and update the existing expectations authorized by Frame. The repaired witness follows the note return through the record and restored Registry search, checks required status within each field row, asserts ordered directed endpoints, and rejects a citation when a competing filename would open unrelated evidence.
- `README.md`. Document the durable URL, published definitions, and source-link constraints.

### Unit evidence

- Builder-owned decisive witness: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py -k ontology_registry_schema`. RED before the original implementation at the missing Companies tab. Log: `/private/tmp/ontology-registry-schema-red.log`.
- Same focused command with the stronger witness before the repair. RED at the citation that would open the competing file. Log: `/private/tmp/ontology-registry-schema-unsafe-source-red.log`.
- `python3 /private/tmp/ontology-registry-schema-repair-probe.py baseline`. RED at the missing Companies tab using the current witness against an isolated archive of `HEAD`. Log: `/private/tmp/ontology-registry-schema-repair-baseline-red.log`.
- `python3 /private/tmp/ontology-registry-schema-repair-probe.py optional`. RED when an isolated candidate copy marks the inherited `entity_type` field Optional. Log: `/private/tmp/ontology-registry-schema-repair-optional-red.log`.
- `python3 /private/tmp/ontology-registry-schema-repair-probe.py reversed`. RED when a separate isolated candidate copy reverses the ordered `WORKS_AT` endpoints. Log: `/private/tmp/ontology-registry-schema-repair-reversed-red.log`.

### Green evidence

- Decisive witness: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py -k ontology_registry_schema`. 1 passed. Log: `/private/tmp/ontology-registry-schema-repair-witness.log`.
- Frame gate: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py tests/test_web_navigation.py -k ontology`. 12 passed. Log: `/private/tmp/ontology-registry-schema-repair-gate.log`.
- Web, navigation, and localization: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q tests/test_web.py tests/test_web_navigation.py tests/test_i18n.py`. 119 passed. Log: `/private/tmp/ontology-registry-schema-repair-web-gate.log`.
- Full offline suite: `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline pytest -q`. 521 passed. Log: `/private/tmp/ontology-registry-schema-repair-full-gate.log`.
- `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache uv run --offline ruff check src/stock_ontology/web/ontology src/stock_ontology/web/navigation.py` and `git diff --check` passed.

### Intervention record

- None. Verification used offline fixtures and isolated source mutations.

### Deviations

- None.

## Audit

Candidate: `93240d44e29d67595d36bf3fe21d135d45506479 @ main`, application/test/README SHA-256 `cd6f89e27bafc6acaf1778584bff547c6d232e3ffd247ee357d08dd3194eba50`. Independently reproduced the digest.

Independence: fresh-context. The independent auditor had reviewed the prior candidate and authored none of the implementation or repair.

Primary-claim verdict: **PROVED**. `tests/test_web.py::test_ontology_registry_schema_browse_records_and_sources` follows company, theme, and person results to their records, opens the cited note, follows its return link, and verifies the restored Registry tab and search. It checks required status in each Schema field’s own row and verifies the ordered `WORKS_AT` endpoints and direction. The witness failed against baseline at the missing Companies tab and failed in separate isolated probes for an optional inherited field and reversed endpoints. It passed on the candidate. Coverage is limited to the seeded records and Schema definitions.

Guardrail verdicts:

- Existing explorer, Audit, entity, theme, and note URLs remain valid: **PROVED**. The focused Ontology and web suites passed their retained structure, filter, Audit, research, and note checks. Coverage is limited to the routes and fixtures in those suites.
- Browsing leaves the graph, official registry, and notes unchanged: **PROVED**. The witness compares the database digest, registry bytes, and all fixture note bytes before and after browsing.
- Records without graph matches and relationships without accessible sources remain readable, with no broken links or misattributed evidence: **PROVED**. The witness covers a zero-match record, a missing file, and a relationship with a logged filename whose trimmed form points to a different note. Restoring the prior citation logic in an isolated copy caused the competing-file assertion to fail at the erroneous link. The candidate retains the relationship and suppresses that link.

Scope and duty verdict: **scope HELD, duties HELD**. The revision resolves R1 in the Ontology view, its existing test file, and the README. The note reader contract remains intact, the existing test changes match Frame, and the README names the citation constraint, explains it, and references tests that exist.

Test homes: `tests/test_web.py` owns the offline HTTP witness and Ontology compatibility checks. `tests/test_web_navigation.py` owns the default navigation expectation.

Full gates: **PASS**. Independently ran `uv run --offline pytest -q tests/test_web.py -k ontology_registry_schema` (1 passed), the Frame Ontology gate (12 passed), the web, navigation, and localization gate (119 passed), and `uv run --offline pytest -q` (521 passed), using `UV_CACHE_DIR=/private/tmp/stock-ontology-frame-cache`. Focused Ruff and `git diff --check` passed. The baseline, optional-field, reversed-endpoint, and citation probes failed at their intended assertions.

Residual risks:

- Citation availability depends on the logged file remaining accessible when the reader opens it.

Recommendation: **ACCEPT**

Packet: Record the accepted verdict and close R1 in `docs/proposals/ontology-registry-and-schema.md` for the verified candidate digest.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->

### R1 — 2026-11-24 — Schema assertions and source-note fidelity
- Verdict: REVISE — The primary witness passed with reversed relationship endpoints and an inherited required field marked optional. It stopped short of following the real note return link. A whitespace-normalized note citation could resolve to a different source.
- Changed: `src/stock_ontology/web/ontology/views.py` rejects aliases resolving to a different note. `tests/test_web.py` demonstrates the competing-source case, the actual return path, and the ordered endpoint and per-field schema assertions.
- Re-audit: ACCEPT — The repaired witness detects all three isolated regressions and passes on candidate `cd6f89e27bafc6acaf1778584bff547c6d232e3ffd247ee357d08dd3194eba50`.
