---
name: proposal-build
description: Use when implementing an approved proposal from its Frame and, when present, Proof, including protected-witness and allowed-scope constraints.
---

# Proposal Build

Implement only the approved claims. The Frame's allowed scope is authority; a protected witness is evidence, not implementation material.

## Preconditions

Read the current `## Frame` and, when present or required by its route, `## Proof` sections. Do not edit the ledger, the Proof witness, or the Revisions section.

Refuse to start and return a deviation when either condition holds:

- A Decision required by Frame is unresolved.
- An independent witness is required but Proof has no verified RED evidence for it.

## Build rules

1. Treat every protected witness path as immutable. Compare it with Proof's
   protected revision, then run it, but never edit it. If the revision is not
   retrievable, or its assertion, claim, or expected behavior appears wrong,
   stop and return a deviation; do not weaken, replace, or update the witness.
2. Compare each proposed modified path with Frame's allowed scope before changing it. Do not modify a path outside that scope. A README entry or existing test listed under Frame's `Invariants changed` is in scope and changes only to the rule stated there; that is not a witness rewrite. Only this ledger's Proof protects a test.
3. If an extra path is necessary, request a scope expansion in Deviations with its exact path and reason. The builder cannot record or approve that expansion and cannot modify the path until it is approved.
4. Implement the smallest change that satisfies the primary and guardrail claims,
   inside the module Frame named for reuse rather than a new one beside it. Do not
   add APIs, aliases, compatibility behavior, UX, dependencies, observability, or
   other reconciliation for a disputed witness; report the dispute instead.
5. Own unit tests for Frame's supporting obligations. For nontrivial new internal behavior, add the unit test first, run it to observe the expected RED result, implement minimally, then rerun it for GREEN.
6. On a `builder` route, author the builder-owned decisive witness in Frame's
   permanent owner and observe proposal-specific RED before implementation. A
   pre-existing green test is not RED evidence. On every route, run the decisive
   witness, relevant unit tests, and every project gate named in Frame.
7. Build only the reversible candidate that Audit can inspect. Local execution in
   an isolated, reversible test environment is allowed. Never merge, push, deploy,
   migrate live data, call a production or external mutation, or otherwise execute
   an irreversible action; that stays human-owned on every route, including after
   an audit `ACCEPT`.
8. Capture any durable constraint the change establishes. Apply the test: if
   someone did the obvious thing in this directory in six months, would they
   reintroduce a bug this change already paid for? If yes, add one entry to the
   nearest `README.md` — the constraint as an imperative, a `**Why:**` line
   naming the incident with a date or reference, and a `**Guarded by:**` line
   naming the test that enforces it. If no, add nothing; a README that grows
   without constraints is drifting into description, which belongs elsewhere.
   Record the added entry under Files changed. This one entry is in scope on
   every route, whatever Frame's allowed scope says; it needs no scope expansion.

Keep native test and log artifacts outside the ledger; cite them by path instead
of pasting output.

Deadline pressure changes none of this. A protected test that conflicts with the
claim is a deviation, never an edit; a disputed contract is reported, never
reconciled with an invented alias; and one more file is a scope expansion to
request, never a narrow exception to self-authorize.

## Handoff

Return exactly this section and nothing else. Include executed commands, their pass/fail result, and log references; do not paste log contents. Use `None` where applicable.

```markdown
## Build

Candidate: `<identity of the exact built source tree>`

### Files changed

- `path/to/file` — minimal change that satisfies `<claim>`.

### Unit evidence

- Builder-owned decisive witness: `command` — RED: expected missing behavior; log: `path/to/red.log` (`builder` route only).
- `command` — RED: expected failure; log: `path/to/red.log`.
- `command` — GREEN: pass; log: `path/to/green.log`.

### Green evidence

- Decisive witness: `command` — pass; log: `path/to/witness.log`.
- Gate: `command` — pass; log: `path/to/gate.log`.

### Intervention record

- `<ledger id>` in the repository's intervention ledger, or `None` with why (for example: no user-facing outcome to measure).

### Deviations

- None.
```

A deviation blocks Audit-ready status until it is resolved. A requested scope expansion belongs under `### Deviations` and must state the exact path and reason; it is not approval.

Read [references/baseline.md](references/baseline.md) when tempted to reconcile a disputed
witness with an alias, or to self-authorize one more file as a narrow expansion.
