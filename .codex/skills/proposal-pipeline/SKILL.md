---
name: proposal-pipeline
description: Use when a vague product or engineering proposal needs a single durable Markdown ledger for framing, evidence, implementation, and independent audit, especially when handoffs or reruns have been lost.
---

# Proposal Pipeline

Use one proposal-identified ledger as the human-facing record. Copy
[assets/proposal-ledger.md](assets/proposal-ledger.md) to start. Native code,
tests, and logs stay outside it: cite only path, exact command, concise result,
and candidate identity. Never use a feature-ID convention.

Give the ledger one stable, version-controlled home so every rerun and handoff
finds the same file: `docs/proposals/<proposal_id>.md`, unless the repository
documents another location. Never open a second ledger for one `proposal_id`.

## Run it

This is the primary workflow for making a change. Reach for it by default; another
pipeline runs only when a human names one.

The orchestrator is the agent session the human is talking to. It creates the
ledger, invokes each stage, writes returned sections verbatim, and updates `state`.
Stages never write the file.

1. Copy [assets/proposal-ledger.md](assets/proposal-ledger.md) to
   `docs/proposals/<proposal_id>.md` and set `proposal_id` to a human-chosen slug.
2. Draft **Proposal** with `proposal-intake`, or let the human write it. Either way
   the human approves it before Frame.
3. Invoke `proposal-frame`. Write its return over **Frame**, set `witness` and
   `state: FRAMED`. Stop here if `Decisions required` is not `None.`
4. On `independent`, invoke `proposal-prove` in a fresh context, write **Proof**,
   set `state: PROVED`. On `builder`, record the deferred witness in **Proof**.
5. Invoke `proposal-build`. Write **Build**, set `state: BUILT`.
6. Invoke `proposal-audit` in a context that did not build. Write **Audit** and set
   `state` from its verdict. On `REVISE`, append the outgoing verdict to
   **Revisions** first, then rerun from the stage that failed. Rerun at most
   twice per human go-ahead. If the next Audit still returns `REVISE`, stop and
   give the human its Packet and the Revisions entries; another rerun waits on
   their go-ahead.

Go from one stage to the next in the same turn. Stop only at these gates: the
human's approval of Proposal, `Decisions required` that is not `None.`, a Build
deviation, an Audit `REJECT`, or the rerun cap. A summary that names the next
stage, or an offer to continue, is not a stop; run the stage instead.

A stage running in another context is done only when its return arrives. Wait
for it before writing its section or changing `state`.

Write `candidate` as the commit plus where it lives, such as
`a1b2c3d @ worktree/proposal-foo`. Refresh it after any code or test change; a
return whose candidate no longer matches the ledger is stale.

## Ownership and returns

- `proposal-intake` may draft **Proposal**, but the human approves and owns it.
  Never infer or rewrite it.
- The orchestrator maintains YAML state, writes generated sections only from
  stage returns, and owns **Revisions**.
- `proposal-frame`, `proposal-prove`, `proposal-build`, and `proposal-audit`
  each return a complete replacement for its own section. Downstream stages
  never alter upstream sections.
- Stages never merge, push, deploy, migrate live data, call a production or
  external mutation, or perform any other irreversible action. That authority is
  human-owned on every route, and an audit `ACCEPT` never confers it.

Every return states candidate identity, affected native paths, exact commands,
concise results, and protected witnesses. A candidate identity must name one
exact source tree (commit plus worktree or run identity); refresh it after any
code or test change. Write a return only when its input and candidate identities
match the current ledger. Never paste a log, diff, or generated artifact.

## Route

Frame assigns one `witness` and states in prose why.

| Exposure | witness | Route |
|---|---|---|
| Contained and reversible | `builder` | Proposal → Frame → Build → Audit |
| Crosses a component or service boundary, or reaches the core product lifecycle, authentication, payment, or stored user data | `independent` | Proposal → Frame → Proof → Build → Audit |

Exposure is what the change can break, not what it renders; a surface a user
merely passes through is not exposure. When the change leads to a human-owned
irreversible action, Frame names it. The pipeline still builds and audits only
the reversible candidate, because no stage may execute that action on any route.

**Independent means a context that has not authored what it judges.** A subagent,
a separate session, or a different harness each satisfy it. It is a property of
the context, not of any tool, so it holds in a runtime with no subagent mechanism;
moving to a later stage of the same run never satisfies it. Hand the stage only
the ledger path, the candidate identity, and the repository.

This governs Proof on the `independent` route and Audit on every route. An agent
forbidden from starting another context must not silently skip the stage: run it
in place and let Audit record `Independence: same-context`, so a reader can tell a
structurally independent verdict from a self-assessment.

For `builder`, **Proof** records that the builder-owned witness is deferred to
Build. The `independent` route needs independently authored Proof before Build.

## Claims

Frame states one **primary claim** (outcome), **guardrail claims** (what stays
true), and **supporting obligations** (necessary work, not outcomes). Frame also
records the reuse it extends and the cheaper alternative it rejected, so a reader
can see that the framed scope was the smallest one considered. Do not turn any of
this into a broad acceptance checklist.

## Reruns and state

Replace, never append, a stage section. Git and host history preserve prior
versions. **Revisions** is the one exception: append-only, never rewritten.

| Rerun | State | Replace | Clear |
|---|---|---|---|
| Human changes Proposal | `PROPOSAL` | Proposal | Frame, Proof, Build, Audit |
| Frame | `FRAMED` | Frame | Proof, Build, Audit |
| Proof | `PROVED` | Proof | Build, Audit |
| Build | `BUILT` | Build | Audit |
| Audit | `REVISING` or `ACCEPTED` | Audit | nothing |

Clearing never touches **Revisions**. An audit `ACCEPT` sets `ACCEPTED`, `REVISE`
sets `REVISING`, and `REJECT` leaves the human to set `ABANDONED` or change the
Proposal. Allowed `state` values are `PROPOSAL`, `FRAMED`, `PROVED`, `BUILT`,
`REVISING`, `ACCEPTED`, `ABANDONED`; allowed `witness` values are `builder` and
`independent`.

### Ledgers are snapshots

An `ACCEPTED` or `ABANDONED` ledger is a record of intent at that time. Never edit
it, and never mark it superseded. When a later proposal changes what an earlier one
established, the later ledger lists each overridden README invariant or test under
Frame's `Invariants changed`, and the human's approval of its Proposal approves them.
The current rule lives in the directory README and the test it names; git history on
that entry leads to the proposal that last changed it.

A protected witness is protected for one run only: from its Proof until that
ledger's Audit verdict. Record protection in Proof, never as a banner or comment in
the test file. After the verdict it is an ordinary test that a later proposal may
change through `Invariants changed`.

### The revise loop

Before replacing **Audit** with a rerun's verdict, append the outgoing verdict to
**Revisions** as one entry. This is the only record of why the candidate changed,
so a later reader and a re-auditing context can tell which verdict governs.

```markdown
### R<n> — <date> — <claim the audit found unproved, or the duty it found violated>
- Verdict: REVISE — <the audit's stated reason>
- Changed: `<paths>` — <what changed and why it answers the verdict>
- Re-audit: ACCEPT|REVISE — <result>; candidate `<identity>`
```

Never open a second `## Audit` heading, and never keep a superseded audit under an
improvised heading. One Audit section holds the current verdict; Revisions holds
every superseded one.

## Common mistakes

| Mistake | Correction |
|---|---|
| FEAT/task identity | Use a human-chosen `proposal_id`. |
| Attempt ledger | Replace sections and clear downstream work. |
| Second `## Audit` heading | Append the superseded verdict to Revisions. |
| Copied evidence | Cite its native location and result. |
| Build changes Proof | Protect independently authored witnesses. |
| Routing a rendered surface as exposure | Route by what the change can break. |
| Editing or superseding an accepted ledger | List the overridden rule under the new ledger's `Invariants changed`. |
| Treating an earlier run's witness as permanently protected | Protection ends at that run's Audit verdict. |

Read [references/baseline.md](references/baseline.md) when a single file tempts you into an
append-only attempt history or pasted logs.
