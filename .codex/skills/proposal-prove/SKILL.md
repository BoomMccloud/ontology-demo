---
name: proposal-prove
description: Use when a framed proposal routed to an independent witness requires proof before implementation, because it crosses a boundary or reaches the core product lifecycle, authentication, payment, or stored user data.
---

# Proposal Prove

Author the smallest decisive, externally observable witnesses for framed claims. Proof is an observed RED result, not code inspection or a pre-existing green test.

## Entry gate

Consume only the Frame section. Proceed only when its `witness` is `independent`
and `Decisions required` is `None.` Independence is defined by `proposal-pipeline`:
a context that has not authored what it judges, given only the ledger path, the
candidate identity, and the repository. A stage that cannot be run that way is
still worth running, but Audit records the limit.

Otherwise return no proof section: a `BLOCKED pending decisions` route returns to
the human who owns the named decision, and a `builder` route defers its
builder-owned witness to Build.

Do not edit the ledger, production code, upstream sections, or downstream sections. Return the section below for the orchestrator to write.

## Author the proof

For each primary claim and guardrail claim:

1. Name the production defect and the boundary it crosses before choosing a test. If it is a one-module defect, do not make it an integration witness; record it as a supporting obligation for Build.
2. Write one decisive witness at Frame's lowest sufficient layer, extending the
   permanent owner Frame named for reuse; never default to a new test file.
3. State what every assertion proves and its limit. Assert user-visible or public-boundary behavior, not implementation shape or a value captured inside a test double.
4. Run the exact new or amended witness before implementation. RED means the new assertion fails because the proposed behavior is missing. An import error, setup failure, or unrelated failure is not RED.
5. Protect the witness path and any permanent owner paths declared by Frame from Build changes, except a separately approved test-only correction. Protection lasts until this ledger's Audit verdict and is recorded only in Proof: never write a "protected" banner or comment into the test file.

An existing green test may identify the permanent owner, but it is proof only after a minimal new assertion is added and that assertion is observed RED for this proposal's missing behavior. Never cite code existence as product proof.

## Output contract

Return exactly this Markdown section; reference logs by path and concise result, never paste their full output.

```md
## Proof

Candidate: `<identity of the exact source tree on which RED was observed>`

**Protected witness**
- `<claim>` — `<permanent test path>` / `<test name>`
  - Defect and boundary: `<production defect>; <boundary crossed>`.
  - Assertion: `<observable result>`; proves `<claim>`; limit: `<what it does not prove>`.
- Protected paths: `<test path(s)>`.
- Protected revision: `<retrievable revision or artifact identity for comparison during Build and Audit>`.

**Red evidence**
- `<exact command>` → `<concise expected failure caused by missing behavior>`; log: `<path>`.
- `<claim>` has no proof until this command is observed RED.

**Supporting test plan**
- `<one-module supporting obligation>` → Build: `<permanent unit-test owner>`; catches `<defect>`.
- `None.` when there are no supporting obligations.
```

Read [baseline.md](references/baseline.md) when tempted to reuse a green test or production citations as proof.
