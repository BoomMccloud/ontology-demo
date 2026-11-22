# Baseline: single-file proposal workflow

## Scenario

A solo maintainer has spent six hours designing a workflow for agents to take a
vague proposal through framing, tests, implementation, and review. They insist on
one Markdown file because multi-file pipelines have lost handoffs, want to begin
today, and do not want more discovery questions.

## No-skill response observed

The initial response proposed a `docs/proposals/FEAT-###-slug.md` record with an
append-only attempt history. It put full test stdout/stderr inside collapsed
Markdown blocks, described code evidence through a diff summary, and treated the
workflow as a broad acceptance-contract/checklist exercise.

## Why those choices fail

| Baseline choice | Failure | Rule that addresses it |
|---|---|---|
| FEAT identity | A proposal can exist before, outside, or without a feature ID. | Use `proposal_id`, never a FEAT convention. |
| Append-only attempts | The current handoff is buried and stale downstream work can look valid. | Replace the rerun section and clear all downstream generated sections. |
| Embedded logs and diffs | The ledger becomes a second, stale copy of native evidence. | Reference path, exact command, concise result, and candidate identity only. |
| Oversized acceptance contract | It blurs outcome, invariants, and necessary implementation work. | Frame one primary claim, guardrail claims, and supporting obligations. |

## Pressure to preserve

Speed, sunk design time, and the desire for a single file tempt an agent to retain
history and paste proof into it. The correct shape is a compact current-state
ledger: Git/host history preserves prior states, while native code, tests, and logs
remain their own sources of truth.
