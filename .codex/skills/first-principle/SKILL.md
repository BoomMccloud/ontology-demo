---
name: first-principle
description: Evaluate a feature's architecture from first principles — state ownership, side-effect control flow, dumb drivers, lifecycle and concurrency, testability — and settle them with the litmus test. Use when planning a complex feature, choosing a state-management approach, reviewing an architecture, or debugging tangled state.
---

# First Principles

Five universal questions about where state lives, what moves it, and whether the
result can be run without its UI or its network. They apply to a plan, a diff, or
code already shipped.

Bring the design under evaluation and access to the code it touches. A spec, plan,
issue, or spoken description all work. Verify assumptions against the code rather
than the description, and say where the two disagree.

## Vocabulary (adapt to your stack)

These terms are deliberately abstract. Translate to whatever the project uses:

| Concept | Frontend | Backend service | Data pipeline |
|---|---|---|---|
| **Source of Truth** | Store / state tree | Database / single state store | Owning table or stage |
| **Side Effects** | API calls, DOM, timers | External APIs, file I/O, queues | ETL steps with external deps |
| **Drivers** | API clients, WebSocket, audio | DB clients, HTTP clients, queue consumers | DB connections, API clients |
| **Lifecycle** | Mount/unmount, cleanup | Connection pools, graceful shutdown | Idempotent reruns, crash recovery |
| **Testability** | Test without rendering | Test without spinning up the server | Test transforms without live DB |

## The five principles

### 1. Source of truth topology

**Questions**: Is more than one component acting as the brain for this feature
(risk: split brain, conflicting state)? Can the complete feature state be
serialized (risk: hidden state in closures, untraceable bugs)?

**Analysis**: identify every place holding state for this feature; map which owner
is authoritative for each piece; look for duplicated or derived state living in
several places; confirm the whole state can be one serializable tree, such that
reloading from it restores the feature exactly.

**Red flags**: multiple components fetching the same data independently; state
mirrored across owners via props or context drilling; derived state computed in
several places; state living only in closures.

### 2. Side-effect control flow

**Questions**: Are side effects reactions to *history* (state changed → do thing)
or executions of *intent* (command → do thing)? Is business logic coupled to the
delivery mechanism — transport, framework, DOM?

**Goal**: prefer intent. "User clicked Save" → dispatch SAVE → execute. Avoid
reactive chains where setting a flag triggers an effect that fires the call.

**Analysis**: list every side effect (network, timer, listener, write); for each,
identify whether an explicit command or an implicit state-change reaction triggers
it; check whether business logic lives in pure functions of the shape
`State + Event → NewState + Commands` or is tangled with infrastructure.

**Red flags**: state-watching effects that fire network calls; several effects
watching the same state; business decisions inside transport code; loading and
error branching scattered across components.

### 3. Dumb drivers

**Questions**: Does an infrastructure layer — HTTP client, socket, audio device,
DB client — contain business logic? Does it hold its own lifecycle or connection
state separately from the application?

**Goal**: drivers expose methods and emit events. They never decide *what* to do,
only *how*.

**Analysis**: list every driver; for each, list the decisions it makes on its own
(retry, redirect, reconnect, pause); confirm lifecycle state lives in the business
layer rather than duplicated inside the driver.

**Red flags**: a client that decides when to retry; a socket manager with internal
connection state the UI also tracks; driver code branching on application state.

### 4. Lifecycle and concurrency

**Questions**: What happens if the feature is destroyed while active (risk: leaked
listeners, zombie connections, work continuing after its caller is gone)? What
happens under rapid repeated actions (risk: races, duplicate writes, inconsistent
state)?

**Goal**: deterministic teardown. Every driver has a synchronous dispose or abort,
and state-machine guardrails reject events invalid for the current state.

**Analysis**: list every async operation and listener; trace what runs on
teardown; confirm cleanup exists and is synchronous; walk rapid sequences such as
double-submit, spam, and cancel-then-retry; check that transitions guard against
invalid concurrent events.

**Red flags**: missing cleanup; calls without cancellation; listeners never
removed; no guards for concurrent actions; timers never cleared.

### 5. Testability

**Question**: Can the entire flow be exercised without the UI, the framework, or
the network?

**Goal**: instantiate the logic plus a mock driver and run the whole journey in
milliseconds.

**Analysis**: identify the core logic; check it can be tested independently of the
framework; confirm drivers can be replaced with simple stubs; confirm a complete
journey runs headlessly.

**Red flags**: logic glued to framework primitives; tests that must mount
components or boot the server; elaborate mocking needed to test small logic;
integration tests as the only verification.

## The litmus test

**If I delete the UI layer and replace the network and IO layer with a mock, can I
still run the entire business flow as a console script?**

Yes means the logic is decoupled from UI and infrastructure. No means it has
leaked into one of them and a refactor is required. This is the final arbiter.

## How to run it

0. **Recover intent.** Before designing anything, restate what each stated
   requirement is trying to achieve *as an outcome*, in your own words. A
   requirement naming an expression, binding, or call site is telling you the
   author's chosen mechanism, not their goal; design against the goal. Where no
   goal can be recovered — a mechanism is stated and nothing about why — record it
   as an intent gap rather than adopting the mechanism as the requirement. An
   inherited, unexamined mechanism is exactly the burden this analysis sheds.
1. **Walk** each principle in order: state the question, do the analysis, list the
   red flags found, and mark it `PASS`, `CONCERN`, or `BLOCKING`.
2. **Apply** the litmus test and give a one-paragraph rationale.
3. **Document** the decisions: state owner, command and event vocabulary, drivers
   and their interfaces, lifecycle and concurrency plan, and how the logic is
   exercised headlessly.
4. **Flag blocking issues** — anything making the design unimplementable cleanly,
   such as split-brain state with no resolution path, business logic that can only
   live in the driver layer, or lifecycle gaps in a long-running flow.

Close with the intent gaps, one line each, and the blocking issues numbered. Both
may be empty; say so rather than omitting them.
