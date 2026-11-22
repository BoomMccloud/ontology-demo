---
name: proposal-intake
description: Use when turning an early product request, founder brief, or launch idea into the human-owned Proposal section before technical framing or implementation.
---

# Proposal Intake

Turn the request into a concise statement of product intent without deciding how it will be built. The Proposal is human-owned: supply a draft for review, not a technical plan.

## Produce exactly this section

Return only the completed section below. Do not edit a ledger, inspect a codebase, or return downstream sections.

```markdown
## Proposal

### Intent

<What the requester wants to be different, in their language.>

### Tentative primary claim

<Exactly one observable outcome; retain uncertain terms rather than defining them.>

### Why now

<The stated motivation, deadline, or urgency; otherwise “None stated.”>

### Known constraints

<Only constraints the requester supplied; otherwise “None stated.”>

### Non-goals

<Only exclusions the requester supplied; otherwise “None stated.”>

### Open choices

<Unresolved product decisions evident in the request; otherwise “None stated.”>
```

## Intake rules

- Preserve the requester's words, qualifiers, and uncertainty. Do not silently turn “better,” “sometimes,” or “for launch” into definitions.
- Write one tentative primary claim only. Preserve the requested actor, trigger, system
  action, and outcome when stated, including words such as “automatically.” It must
  describe observable product behavior, not a test, implementation mechanism, model
  choice, retry count, timeout, metric, or acceptance checklist.
- Put an unresolved product decision in **Open choices**. When the request bundles parts
  that could ship separately, name that as an open choice of sequence; the human decides
  whether to cut, not you. Missing technical facts belong to Frame's verification.
- State only explicitly supplied constraints and non-goals; a demand about how fast you
  work governs intake, not the product. Use “None stated.” rather than creating either.
- Do not add acceptance criteria, guardrail claims, supporting obligations, implementation direction, codebase facts, invented safeguards, or questions that delay intake.

For the failure pattern this skill prevents, read [references/baseline.md](references/baseline.md).
