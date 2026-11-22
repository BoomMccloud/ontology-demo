---
name: proposal-frame
description: Use when a proposed change needs codebase-grounded framing, risk routing, an executable claim, decisive-test ownership, or a decision on whether product choices block proof and build.
---

# Proposal Frame

Turn a human-owned proposal into the next executable handoff. Own verified reality and framing; do not reinterpret product intent or make product choices. Read the ledger's human-owned `## Proposal` first and preserve its intent, constraints, non-goals, and unresolved choices.

## Procedure

1. Record whether the suites judging this change were green **before** it started,
   measured by running them. Then inspect the repository before relying on any named
   helper, file, behavior, API, test, or architecture, citing path and symbol, command
   and result, or stable artifact, with what each proves and its limit.
2. Survey what already exists that could carry the change — component, helper, route,
   or permanent test owner — and name the one to extend or why none fits. Reuse is the
   default; an unverified helper is something to inspect, not a reason to build beside it.
3. State one final primary claim as an observable outcome; mark it `BLOCKED` with the
   decision needed if it is impossible, contradictory, or waits on a product choice.
   Convert independent material risks into zero to three observable guardrail claims,
   and put implementation facts and unit-test candidates under supporting obligations.
4. Select the route and state in one line why it applies:

   | Exposure | Route | Witness |
   | --- | --- | --- |
   | Contained and reversible | May proceed without Prove. | `builder` |
   | Crosses a component or service boundary, or reaches the core product lifecycle, authentication, payment, or stored user data | Require independently authored Prove before Build. | `independent` |

   Judge exposure by what the change can break, not by what it renders; a surface a user
   merely passes through is not exposure. Name any human-owned irreversible action it
   leads to, which no stage may execute on any route. Select the lowest sufficient
   witness layer and name its permanent owner.
5. Constrain allowed scope to the smallest work the claims need, and name the cheaper
   alternative you rejected with what the claims need beyond it, or record that the
   cheapest is the one framed. Invoke `kiss` when scope outgrows the claim, and name
   protected boundaries and excluded work when verified.
6. Put every unresolved material product choice under `Decisions required`. A choice is
   material when its alternatives differ in what the user gets on a surface the route's
   second row covers; elsewhere take the cheapest option satisfying the claim. When any
   decision is required, stop: do not route to Prove or Build.
7. Search the directory READMEs and existing tests the change touches for every rule
   the approved Proposal overrides, and list each under `Invariants changed` with its
   citation, the rule today, and the rule after. The Proposal's approval is the
   authority for these overrides. An earlier accepted ledger, or an old in-file
   "protected" banner, never blocks one and is never edited. An override the Proposal
   does not clearly intend is a `Decisions required` item instead.

## Output Contract

Return exactly this Markdown section and nothing else. Use `- None.` for an empty category. Do not label criteria strong or weak, and do not edit the ledger or its other sections.

```markdown
## Frame

Candidate: `<identity of the exact inspected source tree>`

### Verified reality
- `<citation>` — proves `<fact>`; limit: `<what it does not establish>`.

### Final primary claim
- `<observable user or system outcome, or BLOCKED pending the named decision>`

### Routing
- Witness: `<builder|independent, or BLOCKED pending decisions>`
- Why: `<what the change can break, in one line>`
- Human-owned irreversible action: `<the merge, deploy, or migration no stage may execute, or "None.">`

### Decisive witness
- Layer: `<lowest sufficient layer, or BLOCKED pending decisions>`
- Permanent owner: `<test suite, contract, operational owner, or BLOCKED>`
- Witness: `<observable assertion or check, or BLOCKED>`

### Guardrail claims
- `<zero to three independently material observable outcomes>`

### Supporting obligations
- `<internal implementation obligation and unit-test candidate>`

### Allowed scope
- Reuse: `<existing component, helper, or test owner this extends, or why none fits>`
- Cheaper alternative: `<the smaller change rejected and what the claims need beyond it, or "None smaller.">`
- Include: `<minimal verified changes>`
- Exclude/protect: `<boundaries not authorized or protected evidence>`

### Invariants changed
- `<README entry or test, path:line>` — today: `<current rule>`; after: `<new rule>`. Or `None.`

### Decisions required
- `<material human product decision, or “None.”>`
```

## Checks Before Handoff

- Never silently settle a product choice the human left open on a routed surface. Everywhere else the cheaper alternative is the right one; name it and take it.
- Require Prove for every `independent` route. Never route a boundary, lifecycle, authentication, payment, or stored-data exposure to `builder`, and emit no downstream section while a decision is required.

Read [references/baseline.md](references/baseline.md) when tempted to trust a claimed helper without inspecting it, or to settle an open UX choice yourself.
