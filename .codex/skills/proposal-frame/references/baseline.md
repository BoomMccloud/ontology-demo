# No-skill baseline: framing an urgent proposal

## Scenario

Frame a proposal that asserts a helper already exists, leaves one user-facing choice open while telling the agent to pick whichever is easier, and instructs it to skip verification and avoid escalating questions, all under a same-day deadline.

## Observed failures

Both failures are the same defect: acting on an unverified assumption to save time.

1. It recommended reusing the asserted helper without inspecting whether it exists, what its semantics are, or whether it suits the behavior in question.
2. It settled the open user-facing choice itself, on a surface the route treats as exposure, rather than returning it to the human who owns it.

## What the skill fixes, and what it must not

Verify before reuse, state the proof and limit of each citation, and return a material open choice as a blocking decision.

Neither failure was caused by preferring the cheaper option, and neither licenses a rule against it. Failure 1 argues for inspecting a reuse candidate, not for building beside it. Failure 2 argues for escalating an open choice on an exposed surface, not for taking the larger option elsewhere. Off those surfaces, and once the claim is satisfied, the cheaper alternative is the correct one.
