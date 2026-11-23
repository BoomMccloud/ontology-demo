---
proposal_id: "registry-governance"
state: ACCEPTED
witness: independent
candidate: "8443720 @ /Users/jasonbxu/Documents/GitHub/stock_ontology + tracked diff SHA-256 009c19ad5dafa032de4d7f1159c68f4552ba5b0ed5a44949122bb06ee314450f + protected witness 75298ad64383e81694ce644904772290c498d0cd0cffa452f8512dfbbe40fd9a"
---

# Registry governance

## Proposal

Approved by the human on 2026-11-23. The same maintainer may make both approval decisions.

### Intent

Every change to the official ontology starts as a proposal. Agents and audit tools can collect evidence, draft changes, and preview their effects. A human publishes each approved registry version and separately approves any migration or repair needed to apply it to live data.

### Tentative primary claim

From proposal through rollout, each change to the official registry and each resulting change to live data can be traced to a separate human decision.

### Why now

An older checkout could open the shared database, attempt a migration, and change the schema stamp while leaving 24 incompatible price targets in place. Audit also writes suggestions into the registry file by default. The workflow needs a clear boundary between proposed changes, official definitions, and the version applied to live data.

### Known constraints

1. Record the proposed registry diff, its rationale, and the live evidence. Keep pending suggestions outside the official registry.
2. A human reviews the diff and publishes the approved registry version. Publishing leaves the live database on its applied version.
3. Preview the live impact. A human separately approves the exact plan, including any conversions, repairs, or version-only adoption. Apply that plan explicitly and record the applied version after validation succeeds. Ordinary opens and ingestion do not initiate this transition.
4. The same human can publish and approve rollout. The decisions are recorded separately. Routine ingestion continues under the applied version.

### Non-goals

None stated.

### Open choices

Resolved for the POC. The maintainer operates both steps from a local screen. Separate operator credentials and identity verification are outside this POC.

## Frame

Candidate `8443720`, tracked `main` tree at `/Users/jasonbxu/Documents/GitHub/stock_ontology`.

### Verified reality

- `.venv/bin/python -m pytest -q -p no:cacheprovider` passed all 458 offline tests before this proposal changed any files. This is the existing behavior baseline.
- `src/stock_ontology/cli.py:792` runs audit against a read-only database and synchronizes suggestions back into the registry by default. `src/stock_ontology/registry.py:1179` already provides an atomic JSON write. Neither is an approval boundary.
- `src/stock_ontology/db/storage.py:149` migrates and stamps on writable open or `use_registry`. `src/stock_ontology/registry.py:401` fingerprints facet vocabularies, facet schema, and metadata limits. The current stamp cannot distinguish versions that change relation definitions, companies, themes, or facet aliases alone.
- `src/stock_ontology/repair.py:70` applies deterministic repairs in a transaction. `src/stock_ontology/cli.py:848` runs those repairs when invoked and optionally reembeds survivors. There is no binding to a separately reviewed preview of the changes.
- A read-only comparison of the configured database and current registry found matching facet schema stamps and no node facet validation failures. This does not establish the identity of a published registry version or whether adoption was approved.
- `git remote -v` returned no configured remotes, and the repository has no `.github` directory. There is no verified protected publication workflow to reuse. These checks do not establish what maintainer credentials or permissions are available outside the repo.

### Final primary claim

- A proposed registry diff becomes an official version after confirmation in a local interactive maintainer workflow. The live database remains on its applied version until a human approves the exact rollout for that database and the rollout validates and commits.

### Routing

- Witness owner is independent because the workflow controls changes to persisted live data and separates two operator decisions.
- Official publication and application to the live database are human-owned actions. Proof, Build, and Audit use disposable databases and candidate registry artifacts.

### Decisive witness

- Use a CLI-level integration test with a temporary registry and SQLite database. Permanent ownership belongs in `tests/test_registry_governance.py` for the cross-command contract. The existing audit and migration test files must change their older expectations, so neither can be protected as a whole by this proof.
- Start with version A applied and a proposed version B. Declining either interactive confirmation leaves that stage unchanged. Human publication of B leaves the live data and applied version on A. A separate authorization for a reviewed A-to-B plan permits that exact plan to apply. If the planned inputs change or validation fails, the live changes and applied version do not commit. The confirmation is procedural under the shared local account.

### Operator contract

- `stock-ontology registry-publish PROPOSAL --registry FILE --db FILE` displays the diff and asks for confirmation. `PROPOSAL` is a proposed full registry JSON, and `FILE` is the official registry destination. Publication uses a distinct version and leaves the database unchanged.
- `stock-ontology registry-apply --registry FILE --db FILE` previews adoption and asks separately for confirmation. The initial application can establish the applied registry for an existing database. Later publication requires a database with an identified applied revision.
- `audit --sync-suggestions` writes a separate proposal queue beside the registry. The name is the registry filename stem plus `.suggestions.json`.

### Guardrail claims

- Audit can emit or refresh pending proposals while preserving the official registry and live database.
- Routine ingestion continues with the applied registry. Writable open and registry selection do not implicitly apply a newer version.
- A change limited to official definitions outside the existing facet stamp still requires human publication and explicit adoption.

### Supporting obligations

- Distinguish the published revision from the applied revision and bind the approval to the exact registry content. Exclude proposal records from the official registry identity.
- Bind the rollout approval to its source revision, target revision, and reviewed changes. Recheck the approved inputs under the write transaction and record adoption only after validation.
- Identify how the audited rules and migration preview use the same validators and repair behavior as the apply path.

### Allowed scope

- Reuse the existing registry JSON loader and audit report, CLI audit and repair entry points, registry validators, and SQLite transactions. The independent witness can extend existing CLI and storage tests.
- A written checklist and branch-specific database paths can reduce accidental drift now. They cannot enforce that an agent using the same local account is unable to publish or apply a change.
- Include proposal output, registry publication and applied-version records, migration preview and explicit apply, and a local interactive terminal workflow with separate review and confirmation screens.
- Exclude web administration, changes to ontology definitions, LLM behavior changes, and live migration during development.

### Invariants changed

- `README.md:31,74,102,138`, `docs/architecture/governance.md:22`, and `tests/test_registry_audit.py:631,667,877` currently put automatic audit suggestions into the official registry. The approved workflow keeps the proposal queue separate.
- `README.md:147`, `docs/architecture/storage.md:55`, `docs/architecture/ontology.md:140`, and `tests/test_official_facets.py:338,586` and `tests/test_db.py:1199` currently require an automatic writable-open migration when the stamp differs. The approved workflow requires explicit adoption of an approved registry revision.
- `docs/architecture/governance.md:30` and `tests/test_repair.py:409` currently describe and verify repair applying changes and stamping the registry schema. Live repairs resulting from adoption must be bound to the separately approved rollout plan. The CLI coverage in `tests/test_db.py:737,1000` and `tests/test_relation_facets.py:178` currently runs repair without interactive approval. It must exercise the reviewed repair or rollout, respectively.

### Decisions required

- None. The POC uses the existing interactive terminal CLI as its operator screen. The decision is procedural under the shared local account.

## Proof

Candidate `8443720` with the independently authored `tests/test_registry_governance.py`.

- Protected witness SHA-256 `75298ad64383e81694ce644904772290c498d0cd0cffa452f8512dfbbe40fd9a`. Comparison copy at `/tmp/stock-ontology-registry-proof.5ungIS/test_registry_governance.py`.
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_registry_governance.py` observed four RED cases. Audit rewrote official JSON, writable open coerced a facet, and the CLI had no adoption command for the two operator-workflow cases. Log `/tmp/stock-ontology-registry-governance-red-8443720.log`.
- The witness verifies separate decisions, separate suggestions, version-only drift detection, promotion through an approved adoption, and preservation on incompatible rollout. It does not exercise concurrent modifications during review.

## Build

Candidate `8443720` plus workspace diff SHA-256 `009c19ad5dafa032de4d7f1159c68f4552ba5b0ed5a44949122bb06ee314450f` and the protected witness above.

### Files changed

- `src/stock_ontology/cli.py` and `registry.py` implement separate proposal, publication and reviewed adoption, including an audit status and sidecar.
- `src/stock_ontology/db/storage.py`, `pipeline.py`, and `repair.py` pick the applied definitions, preview with a database copy, verify rollout inputs under a write lock, and validate before storing adoption.
- `tests/test_db.py`, `tests/test_official_facets.py`, `tests/test_registry_audit.py`, `tests/test_relation_facets.py`, and `tests/test_repair.py` update the prior rules and exercise a changed graph between preview and approval.
- `README.md` and the storage, ontology, and governance architecture pages record the new operator workflow and invariants.

### Unit evidence

- `.venv/bin/python -m pytest -q -p no:cacheprovider` included `tests/test_db.py::test_confirmed_registry_rollout_rejects_data_changed_during_review`. The result confirms that a concurrent node write survives and the stale adoption is refused. This supporting test was added after the guard. Removing the stale-review checks on a disposable source copy made the test fail because the stale plan was accepted. Log `/tmp/stock-registry-governance-stale-guard-mutation.log`.
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_db.py -k "writer_opened_before_first or later_registry_confirmations"` produced two RED failures on the first candidate. The pre-adoption handle could still write and repeat adoption lost the earlier receipt. Log `/tmp/stock-registry-governance-r1-red.log`.
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_db.py tests/test_registry_governance.py` passed 44 tests after both fixes. Log `/tmp/stock-registry-governance-r1-focused.log`.

### Green evidence

- `.venv/bin/python -m pytest -q -p no:cacheprovider` passed 465 tests on the final candidate. Log `/tmp/stock-registry-governance-r1-full.log`.
- `.venv/bin/ruff check src/stock_ontology/{cli,registry,pipeline,repair,db/storage}.py` and `git diff --check` passed.
- `registry-apply` with a declined confirmation previewed the configured live data on a copy. No graph rows were planned to change, and the live registry and database file hashes were unchanged. Log `/tmp/stock-registry-governance-live-preview.log`.

### Intervention record

- This ledger records the workflow, tested on disposable databases. The live adoption remains with the maintainer.

### Deviations

- None.

## Audit

Candidate `8443720` with tracked diff SHA-256 `009c19ad5dafa032de4d7f1159c68f4552ba5b0ed5a44949122bb06ee314450f` and protected witness SHA-256 `75298ad64383e81694ce644904772290c498d0cd0cffa452f8512dfbbe40fd9a`.

Independence: fresh-context. I reviewed both candidates without authoring the implementation or protected witness.

Primary-claim verdict: **PROVED**. The protected CLI tests verify separate confirmations, unchanged files after declines, and rollback when adoption fails validation. The revision tests verify stale-plan rejection and retention of earlier publication and rollout receipts through repeated approvals. Evidence uses disposable databases.

Guardrail verdicts:

- **PROVED** for proposal isolation. Audit writes the separate sidecar and preserves the official registry and database bytes.
- **PROVED** for continued use of the applied registry. The protected witness verifies the selected registry before and after adoption. The R1 regression test verifies that a writable connection opened before first adoption rejects a stale write after rollout.
- **PROVED** for changes outside the facet stamp. The protected workflow verifies separate adoption of an equal-stamp version.

Scope and duty verdict: scope **HELD**, duties **HELD**. R1 addresses the write guard and receipt defects within the approved CLI and storage scope. The protected witness matches its independent comparison copy. Baseline RED logs and the stale-plan mutation check establish the supporting tests’ sensitivity.

Test homes: `tests/test_registry_governance.py` owns the cross-command contract. `tests/test_db.py`, `tests/test_official_facets.py`, `tests/test_registry_audit.py`, `tests/test_relation_facets.py`, and `tests/test_repair.py` retain their storage, CLI, relation, and repair contracts.

Full gates: **PASS**. Independent runs passed all 465 offline tests and all 44 focused tests. Ruff, the protected witness comparison, and `git diff --check` passed.

Residual risk: Terminal confirmations record operator intent under the shared local account. Identity verification is outside the approved POC.

Recommendation: **ACCEPT**

Packet: The maintainer can review and confirm the initial adoption through `registry-apply`. This audit made no live changes.

## Revisions

### R1, 2026-11-23, pre-adoption writer and approval records

- Verdict `REVISE` on candidate `bc7521aa3f4f85b3a30ed8938870aa2573cc442c662c9749adc31043468c3c1b`. A connection opened before the first adoption could continue to write with an obsolete registry. Successive publications and repeated adoptions could overwrite earlier approvals. Evidence for the stale-plan support test was incomplete.
- Changed `src/stock_ontology/db/storage.py`, `src/stock_ontology/cli.py`, `src/stock_ontology/registry.py`, and `tests/test_db.py` to check registry identity for all outer write transactions, retain operation receipts, and exercise the old-writer and repeated-approval cases. The protected witness is unchanged. The stale-plan witness was checked by removing the guards in a disposable source copy.
- Re-audit returned `ACCEPT` for candidate `009c19ad5dafa032de4d7f1159c68f4552ba5b0ed5a44949122bb06ee314450f`.
