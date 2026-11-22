---
name: proposal-audit
description: Use when a proposal-pipeline candidate is ready for independent acceptance review, especially when a builder reports green tests, a protected witness may have changed, scope may have expanded, or release pressure could weaken evidence.
---

# Proposal Audit

Independently decide whether the candidate's approved claims are proved. Evidence—not a plausible UI, implementation, or green suite—controls the verdict.

## Audit procedure

0. Run in a context that has not built the candidate, as `proposal-pipeline`
   defines independence, given only the ledger path, the candidate identity, and
   the repository. When the environment does not permit starting one, audit anyway
   and record `Independence: same-context`: a verdict from the context that
   authored the work is weaker evidence, and a reader cannot tell the difference
   unless the ledger says so. Never report `fresh-context` for a run that merely
   changed stage.
1. Read the ledger's Proposal, Frame, Proof when present, Build, and Revisions sections. Record the final primary claim, every guardrail claim, approved scope, supporting obligations, decisive-witness paths, protected paths, and required project gates. Do not rewrite any upstream section.
2. Inspect the actual candidate diff and the decisive-witness files. Compare them
   with Proof's retrievable protected revision; a missing revision makes the
   affected claim unproved. Run or inspect each claimed decisive witness and
   every required deterministic project gate yourself; record the path, command,
   and result. Do not accept a builder's report as evidence.
3. For each primary or guardrail claim, require a decisive witness that is independently authored where the route requires it, remains in its permanent owner, was verified RED, still proves the claim, and has not been compromised by editing, deletion, omission, or weakening. A missing proof section or an absent applicable witness is also non-proving.
4. Mark the affected claim **UNPROVED** if its decisive witness is compromised, edited, missing, never RED, or non-proving—regardless of green tests, apparently correct copy, or a working UI. Do not infer satisfaction from code existence, copy, or a broad suite.
5. Compare every changed file and behavior with approved scope; compare the candidate with its supporting obligations and protected witnesses. Treat out-of-scope edits, witness rewrites, or skipped duties as evidence for **EXPANDED** scope or **VIOLATED** duties. Report **PASS** for full gates only when every applicable deterministic command passes and all required decisive witnesses remain valid; a green suite with a compromised required witness is **FAIL**. Every change to an existing README invariant, or to a test this ledger's Proof did not author, must match an entry under Frame's `Invariants changed`: an unlisted change is **EXPANDED** scope, and a listed change not made is a **VIOLATED** duty. The one exception is a new `README.md` entry that step 7's constraint-capture duty requires: it is in scope on every route, so judge it under step 7, not as **EXPANDED** scope.
6. Check that the candidate built what Frame framed as smallest: it extends the reuse
   Frame named, and delivers no more than Frame justified against its rejected cheaper
   alternative. Unclaimed work beyond that is **EXPANDED** scope, whatever its quality.
7. Check the constraint-capture duty. If the change established a durable rule —
   one where doing the obvious thing later would reintroduce a bug this change
   paid for — the nearest `README.md` must carry an entry with its `**Why:**`
   and a `**Guarded by:**` test that exists. A missing entry is a **VIOLATED**
   duty, not a nitpick: the rule survives only if it is written down somewhere
   permanent and local. An entry naming a test that does not exist is also
   VIOLATED. Judge only constraints this change actually established.
8. Select the recommendation mechanically: **ACCEPT** only if every claim is PROVED, scope and duties are HELD, gates PASS, and no unresolved deviation exists. Use **REVISE** for correctable evidence, code, or scope failures. Use **REJECT** only when proposal intent cannot be met or approved constraints conflict.

When this is a re-audit, read every `## Revisions` entry first and check that the
verdict each one claims to answer is actually answered by the changed paths it
names. A revision that restates a verdict without changing the evidence is not an
answer. Return one Audit section holding the current verdict only; the
orchestrator appends the superseded verdict to Revisions. Never open a second
`## Audit` heading.

Audit is read-only. Never fix the candidate, merge, push, deploy, or perform an
irreversible action. `ACCEPT` means the claims are proved; it never authorizes an
irreversible action, which stays human-owned on every route.

## Output contract

Return only this section, in this order; do not edit the ledger, code, tests, or logs. State the evidence and its limit for every verdict. Reference artifacts by path, command, and result; do not paste logs or diffs.

```markdown
## Audit

Candidate: `<identity of the exact independently audited source tree>`

Independence: fresh-context|same-context — `<what the auditing context had already seen>`

Primary-claim verdict: PROVED|UNPROVED — evidence: ...; limit: ...

Guardrail verdicts:
- <claim>: PROVED|UNPROVED — evidence: ...; limit: ...

Scope and duty verdict: scope HELD|EXPANDED; duties HELD|VIOLATED — evidence: ...; limit: ...

Test homes: `<each test file the candidate added or amended>` — `<permanent owner it landed in, and why>`; or `None — the candidate added no tests.`

Full gates: PASS|FAIL — <path or command>: <result>; limit: ...

Residual risks:
- ...

Recommendation: ACCEPT|REVISE|REJECT
Packet: <the smallest next action, affected paths, and the evidence required to re-audit>.
```

If there are no guardrail claims, write `Guardrail verdicts: none stated — limit: no guardrail proof was requested.` Do not convert absence into proof.

Read [references/baseline.md](references/baseline.md) when a correct-looking response or UI
tempts you to call a claim proved despite a compromised witness, or to prescribe a fix beyond
restoring proof.
