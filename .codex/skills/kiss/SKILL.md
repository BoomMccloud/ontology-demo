---
name: kiss
description: Evaluate a proposed change against KISS (Keep It Simple, Stupid) to avoid over-engineering. Sizes the change first — which requirements are already covered, and whether the ceremony is proportional — then scores five simplicity tests against what survives. Use when reviewing a plan, spec, diff, refactor, or architecture, or whenever a solution feels bigger than its problem.
---

# KISS

Is this as simple as it can be while still doing the job, and is the job as small
as it should be? The second question comes first, because the five tests below are
all ratios and none can be scored until the size of the change is fixed.

Bring the proposed change and access to the code it touches. A spec, plan, diff,
issue, or spoken description all work as the proposal. Read the code wherever the
description is not enough, and say where you did.

## Pass 1 — size the change

For each thing the proposal says must be built or asserted, return exactly one:

| Disposition | Meaning | Required evidence |
|---|---|---|
| `ALREADY-COVERED` | existing code or a test already fails if this is violated | `file:line` **and what it asserts** |
| `SELF-GUARDING` | the change itself makes the check unnecessary | the mechanism |
| `CUT` | it costs more than the risk it retires | the risk, named |
| `KEEP` | genuinely new work | — |

`ALREADY-COVERED` is the one that pays: code and tests that derive their cases
from data rather than listing them cover new cases for free, but only reading them
reveals it. A disposition without its citation is a guess — mark it `KEEP`.

**A requirement guarding an irreversible failure may return only `KEEP` or
`ALREADY-COVERED`, and the citation is mandatory.** Irreversible means rerunning
cannot undo it: data destroyed, a message sent, money spent, a migration applied,
a published contract broken. `CUT` weighs cost against risk, and that
expected-value trade is exactly what misprices a small chance of permanent loss.
`SELF-GUARDING` asserts a mechanism will hold with nothing left to catch it if the
mechanism changes. Both are sound on reversible work and unsound here.

Downstream work follows these dispositions, so a wrong `CUT` on irreversible work
deletes the only witness for the one thing that cannot be walked back. If such a
requirement genuinely looks unnecessary, say so under proportionality and leave it
`KEEP`; retiring it is the author's call, not yours.

### Proportionality

Judge the proposal's ceremony against the change that survives.

**Red flags**: a new file for a change that must edit an existing one anyway; an
assertion guarding something the same diff deletes; text explaining how to stop a
test from matching itself; a guard for a property already asserted elsewhere; a
case count exceeding the number of behaviours actually changing.

**Verdict**: `PROPORTIONATE` or `OVERSPECIFIED`. Neither stops anything; the
dispositions are what change the work.

### The honest split

Close with `minimalChange`: what actually must be built, in prose. Name the
behavioural changes separately from the mechanical ones — the ratio between them
is the finding. Where a behavioural change is coupled to a mechanical one, say so
and why it cannot be descoped. A change that alters what renders is not a text
edit no matter how few lines it takes.

Score everything below against `minimalChange`, not the proposal as written, and
say so explicitly. Having just concluded the change is smaller than claimed, the
failure mode here is rubber-stamping: a test passes because you checked it and it
held, never because pass 1 already declared the change small.

## Pass 2 — the five tests

Score each `PASS`, `WARNING`, or `FAIL`, citing specific files or sections.

### 1. Problem — are we solving the right problem?

State the actual problem in one sentence, then separate MUST from COULD. Anything
outside MUST is a candidate for cutting.

**Red flags**: "we might need this later"; "this makes X easier"; "this is more
flexible"; "this is the enterprise way".

Solve today's problem. You can refactor when a real second need appears.

### 2. Simplicity — can it be simpler?

For each new abstraction, ask what happens if it simply doesn't exist. Check
whether the codebase already has a pattern that solves this; prefer consistency
over novelty.

**Red flags**: many new files for a small change; new patterns where existing ones
fit; generic code for a single use case; `Factory`, `Manager`, `Handler`,
`Strategy` where a concrete name would do.

### 3. Abstraction cost — the three-strikes rule

Count real current uses; fewer than three usually means don't abstract. Ask
whether the abstraction reduces or increases cognitive load, and count the
indirection penalty: how many jumps to follow the flow.

**Red flags**: a helper used once; an abstraction hiding a trivial operation; deep
wrappers; generic code where specific would be clearer.

Duplication is cheaper than the wrong abstraction.

### 4. Configuration vs code — configurable for no reason?

Hard-code until something real needs to vary. Do not design extension points for
cases that do not exist.

**Red flags**: more than four parameters; option objects of mostly-optional
fields; flags for non-optional behaviour; one strategy behind a strategy pattern;
injection at simple call sites.

Make it work first; make it configurable at the second real configuration.

### 5. Indirection and naïve-first — how long is the path from intent to work?

Trace one user action through the proposal and count the files opened and hops
taken before anything useful happens. Then ask whether the naïve version was tried
first, and whether there is measurement showing it fails or only a hunch.

**Red flags**: one action touching many files before reaching the work; logic
spread across many tiny modules; premature caching, memoization, or
virtualization; "this won't scale" without evidence.

Make it work, make it right, make it fast, in that order. Skip the third until you
have proof you need it.

## When complexity is justified

A measured performance problem, not a theoretical one. Three or more real current
use cases, not future ones. Elimination of significant real duplication. A
requirement of a framework, external API, or protocol. Security or correctness.

Be equally direct in both directions: say "this is over-engineered, start with the
simple version" and point at the exact abstraction with its simpler alternative
inline, but do not oversimplify a critical path.

## Deliverable

The dispositions with their evidence, the proportionality verdict, `minimalChange`,
the five tests scored against it, and for each `WARNING` or `FAIL` what to remove,
simplify, inline, or defer until proven needed. When several tests fail, sketch the
stripped-down version: bare requirements, no speculative abstractions, no unused
configuration, related code kept together.
