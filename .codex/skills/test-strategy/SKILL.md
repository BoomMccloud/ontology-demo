---
name: test-strategy
description: Use when the human explicitly asks to diagnose or improve the testing and evidence strategy for a proposal, plan, diff, or completed candidate.
---

# Test Strategy

Review whether the chosen tests prove the intended behavior with proportionate,
durable evidence. This is an explicitly human-invoked, read-only diagnostic; the
proposal pipeline continues to own framing, RED/GREEN execution, building, and
acceptance.

## Input and evidence boundary

Accept a proposal ledger, plan, diff, candidate, or a combination of them. Inspect
the cited tests and production boundaries, and run deterministic test commands
when their result is needed to judge the strategy. Do not edit the ledger, tests,
code, configuration, or generated evidence.

Distinguish missing evidence from a failing implementation. Recommend strategy
changes only; do not implement them or silently turn this review into another
pipeline stage.

## Review procedure

Evaluate each concern against cited repository evidence:

1. **Claims:** Map the primary and guardrail claims to decisive assertions. Name
   any claim with no test capable of disproving it.
2. **Layer and ownership:** Select the lowest sufficient test layer and check that
   each witness extends its permanent test owner rather than creating a temporary
   or redundant home.
3. **Assertion quality:** Prefer behavior over implementation details. Keep mocks
   at external boundaries and require assertions on observable results, not calls
   made to a test double.
4. **RED integrity:** Confirm RED was observed before implementation and failed
   because of the intended production defect, not setup, import, fixture, or
   unrelated failures.
5. **Coverage shape:** Check whether unit, integration, browser, and live-provider
   tests are proportionate to the exposure. Look specifically for missing edge
   cases, lifecycle, concurrency, and failure paths.
6. **Reliability and cost:** Identify nondeterminism, false positives, duplicated
   tests, and redundant broad gates that add runtime without adding evidence.
7. **Witness integrity:** Where the route requires it, verify that protected
   witnesses remain unchanged and independently authored through Audit.

## Test layers

Judge layer choice and ownership against these definitions. Unit tests catch
logic, integration tests catch wiring, and end-to-end tests catch reachability.

- **Unit:** covers what is inside one file. Owned by whoever writes that code, in
  the same change. No later stage retrofits them. A test that crosses a module
  boundary to check one module's logic is a misplaced unit test.
- **Integration:** covers a series of components working together. The proposal
  pipeline decides which wiring needs a witness.
- **End-to-end:** covers the whole application running. Owned apart from any one
  change, and never a byproduct of finishing a feature. Some repositories call
  this layer "journey".

The end-to-end layer goes missing silently. Its defect class, such as a button
wired to nothing, a route that never renders, or a payload the client drops,
lives in exactly the part an integration test replaced with a function call, so
nothing below it can see the loss. Before accepting that an Outcome is witnessed,
check whether a browser test in this repository can reach the API at all. Treat
an end-to-end case folded into a domain suite as `BLOCKING`: the fold is a
deletion that leaves every suite green.

## Verdict rules

Classify every applicable concern:

| Verdict | Meaning |
| --- | --- |
| `PASS` | The strategy has direct evidence at a proportionate layer. |
| `CONCERN` | Evidence exists, but its layer, durability, cost, or failure signal can be improved. |
| `BLOCKING` | A required claim is unproved, RED is invalid, or the witness cannot catch the named defect. |

Do not lower a verdict because implementation appears correct. A strategy is
judged by the defect it can expose.

## Output contract

Return:

1. A claim-to-test map with test path, command, layer, permanent owner, and what
   the assertion proves.
2. One `PASS`, `CONCERN`, or `BLOCKING` finding for each applicable review concern,
   citing the proposal, test, command result, and production boundary.
3. Gaps ordered by the consequence of a false green.
4. The smallest strategy correction for every `CONCERN` or `BLOCKING` finding,
   without writing the correction.

Example finding: `BLOCKING — checkout retry guardrail has no witness that fails
when duplicate writes occur; add one concurrency assertion to the existing
checkout integration owner before implementation.`
