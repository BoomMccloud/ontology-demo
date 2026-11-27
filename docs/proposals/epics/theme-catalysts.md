# Theme Catalysts

## Outcome

An analyst can record a company as a candidate for an investment thesis, along with the catalyst event that would move it into the thesis. When evidence arrives, the team can see whether the event happened, whether the company then entered the thesis, and which part of the call was right or wrong.

## How the two systems work together

The **ontology** holds facts that come from sources: companies, themes, events, the sources that report them, and the relationships between them. Facts only accumulate. They enter the ontology through ingestion or through a reviewed apply, and the ontology never refers to a claim.

The **claim graph** holds the team's beliefs: theses, memberships, catalysts, and predictions. Beliefs have an author, a status, and a reason, and they change over time. Claim records point into the ontology by ID. The theme page and the company page each show the claims that touch them.

Keeping the two apart lets the team plan scenarios and score predictions without changing the facts. A belief can be wrong. A fact can only be added to.

## Benefits

The team gets a shared list of companies it is watching for each thesis, the event it is waiting for, and why that event should matter. Recording the event and its expected effect separately lets the team learn whether a miss came from the event not happening or from the event not having the expected effect.

## Model

### Ontology

- **Company.** An entity the team researches.
- **Theme.** A topic, such as the data center rollout. Competing theses share a theme.
- **Event.** Something that happened to a company, with a date.
- **Source.** A note or document. Sources report events.

A company belongs to a theme only through a thesis membership. Sources that link a company to a theme suggest it as a candidate. They do not make it a member.

### Claim graph

- **Thesis.** The investment idea, such as "data center rollout benefits optical suppliers," with an author, anchored to a theme. One theme can hold several theses, including competing ones.
- **Membership.** The link between a company and a thesis, with a status of candidate, in, or out. Every status change records a reason. A change comes either from a resolved prediction or from a direct analyst decision. A direct decision requires a written reason, such as "already ships 1.6T modules in volume to two hyperscalers," so the team can seed companies it already considers part of the thesis without inventing a catalyst.
- **Catalyst.** An expected event on a company, its expected window, and what would count as occurrence. It resolves as occurred when an analyst links it to an ontology event, as did not occur when the window passes, or stays open.
- **Prediction.** The conditional claim that if the catalyst occurs, a membership moves in a stated direction, and the reason the event should have that effect. Entry predictions move a candidate to in. Exit predictions move a member to out, such as a supplier losing its only hyperscaler customer. It resolves as followed, did not follow, or open. A catalyst can carry more than one prediction, including predictions for different theses or, in [Scenarios & Prediction](scenarios-and-prediction.md), mutually exclusive outcomes with probabilities.
- **Proposed fact.** A change to the ontology that a scenario or a resolved prediction suggests, such as Supplier X becoming a qualified supplier to a hyperscaler. It stays in the claim graph until an analyst reviews it and applies it through the existing write workflow.

The catalyst and the prediction are separate records because an event can happen without moving the company, and because scenario planning needs several predictions on one catalyst.

| Catalyst | Prediction | What the team learns |
| --- | --- | --- |
| Occurred | Followed | The call was right. |
| Occurred | Did not follow | The event happened, but the stated reason was wrong or not enough. |
| Did not occur | Not tested | The event or timing call was wrong. The company's fit is still untested. |
| Open | Open | The team is still watching. |

A catalyst is attached to the company the event happens to. It reaches a thesis through its predictions, so one company page shows every catalyst the team is watching on that company, and one thesis page shows every catalyst that could add or remove a company.

## Data entry

The analyst works with theses and companies. Company and theme pages are distinct entry points for different workflows:

- **Company page (primary entry point for creating a thesis).** When watching a company, the analyst starts from that company's page (tapping `+` → **Add a thesis**), anchors the thesis to the company under a theme (such as `Apple` under `Edge AI`), and configures it in a one-page builder:
  1. State the thesis and optionally add any custom drivers already in mind.
  2. Populate with ontology findings (what is already priced in, plus supporting drivers and detracting risks, each carrying its merged observable watch event and window).
  3. Tap `+` on the relevant drivers to attach their watch events to the thesis, then save to monitor incoming news against them on the live thesis view.
- **Theme page (primary entry point for discovery and cross-company theses).** On the theme page, the analyst discovers and compares other companies that carry similar theses under the same theme, or starts a cross-company thesis spanning multiple companies.
- **Add a company to a thesis.** The analyst picks the company, then chooses *in* or *watching*.
  - *In* asks for the reason. It creates a membership with status in.
  - *Watching* asks what the team is waiting for, by when, and why it would move the company in. It creates a candidate membership, a catalyst, and an entry prediction in one save.
- **Add a risk.** On a company that is in, the same three questions create a catalyst and an exit prediction.
- **Suggested candidates.** The theme page lists companies that sources link to the theme but no thesis covers. Each has an action that opens *Add a company to a thesis* with the company filled in.

Adding a second thesis to an existing catalyst and adding competing outcomes are separate actions, kept off the main form. The word "prediction" does not appear in the form until scenario planning.

## Scope

This epic is analyst-driven. Membership is the analyst's recorded decision, not a probability. Probability distributions over outcomes, automated impact-diff proposals, and forecast calibration are out of scope here. [Scenarios & Prediction](scenarios-and-prediction.md) covers proposed diffs, weighted outcomes, and calibration. A later probability on a prediction can be added without changing the thesis, membership, or catalyst records.

## Phasing

### Phase 1. Establish the claim graph

On the theme page, an analyst records a thesis and adds companies through the data entry form above. On the company page, the analyst sees the theses the company belongs to or is a candidate for, and the catalysts that bear on it.

The phase is complete when a teammate can start from either the thesis or the company and reach the membership, its catalyst, its prediction, and what would resolve each. Recording these analyst-authored expectations is the full scope of Phase 1.

### Phase 2. Establish the feedback loop

Link ontology events to the catalyst they resolve, and to the prediction they support or contradict. The analyst marks whether the catalyst occurred and, separately, whether the predicted membership change followed. Each can have a different outcome and date. Keep an item open when the evidence is insufficient. When a catalyst's window passes without the event, record it as did not occur and leave the company a candidate.

When a prediction resolves, the analyst updates the membership status and records the reasoning. Retain the original expectation and a dated history of evidence, decisions, and status changes. When the evidence warrants a new fact, record it as a proposed fact and review it before applying it through the existing write workflow. [Scenarios & Prediction](scenarios-and-prediction.md) covers proposals for graph changes and forecasts. Count repeated coverage of the same underlying event as one piece of evidence, and corroborate material changes prompted by rumors.

### Later. Score the thesis against the world

The user's loop is: a catalyst occurs, the company enters the thesis, the team invests, and the team observes the outcome. Phase 2 grades only the first two steps: whether the event happened and whether the team moved the company. A later phase grades the thesis itself, so each call has three answers: did the catalyst occur, did the team act, and was the thesis right.

Open question: what makes a thesis right for a company?

- Market outcome: the stock beats a stated benchmark over a stated horizon after entry.
- Fundamental outcome: the mechanism shows up in reported numbers, such as rollout revenue growing.
- Both, recorded separately, which catches a right thesis on the wrong stock and the reverse.

Whatever the answer, the horizon and success test should be written down when a company moves in, so the grade is set before the outcome is known.

## Draft user journey

### Track a supplier qualification against a thesis

1. In Phase 1, an analyst opens the data center rollout theme and adds the thesis that the rollout benefits optical module suppliers.
2. The analyst adds Supplier A as *in*, with the reason that it already ships 1.6T modules in volume to two hyperscalers.
3. The analyst adds Supplier X as *watching*. Its 1.6T modules are not yet qualified at any hyperscaler. They are waiting for qualification with a hyperscaler by the end of Q2, because it would unlock volume orders tied to the rollout. Supplier X becomes a candidate with that catalyst and its entry prediction.
4. A teammate opens Supplier X's company page, sees that it is a candidate for the data center rollout thesis, and follows the link to the qualification catalyst and what the team expects it to do.
5. In Phase 2, Supplier X announces the qualification in May. Ingestion records the announcement as an event. The analyst links it to the catalyst, which becomes occurred. The prediction stays open, and Supplier X stays a candidate.
6. Two quarters later, channel checks show the hyperscaler has placed only sample orders, because it is sourcing volume from incumbents. The analyst links the evidence, marks the prediction as did not follow, and keeps Supplier X a candidate with a note that qualification alone was not enough. The team can see the original expectation, the event that happened, and why the company did not enter the thesis.
