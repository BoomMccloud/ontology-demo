# Baseline: Smart interview retries

## Scenario

The founder said: “Add smart interview retries. Users sometimes get bad AI questions, so automatically retry with a better model and improve the prompts. We need it for launch tomorrow. Keep it simple and don’t slow me down with questions.”

## No-skill response

The baseline proposal turned the request into an implementation-ready specification. It invented all of the following commitments:

- A clearly-unusable detector taxonomy: empty, malformed, duplicate, off-topic, or validation failure.
- Exactly one retry for each question turn.
- A higher-quality, configured model.
- A timeout budget and a fallback path after retry exhaustion.
- Structured monitoring of failures, retries, models, and outcomes.
- Multiple success criteria plus a test plan for success after retry, exhaustion, and duplicate prevention.

Those details exceeded the request. Some may later be appropriate, but they are technical or product decisions for Frame and the human owner to verify and choose; they are not facts supplied by the founder.

## Minimal prevention rules

- Emit the Proposal section only; do not supply implementation direction or acceptance criteria.
- Keep one tentative primary claim phrased as an observable outcome, using the founder's uncertain terms without defining them.
- Record only stated deadlines and constraints.
- Put genuine unresolved product decisions in Open choices; leave technical unknowns for Frame rather than turning them into blockers or commitments.
