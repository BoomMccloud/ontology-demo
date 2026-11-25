# Theme Catalysts

## Outcome

An analyst can record a company as a candidate for an investment thesis, along with the catalyst event that would move it into the thesis. When evidence arrives, the team can see whether the event happened, whether the company then entered the thesis, and which part of the call was right or wrong.

## How the two systems work together

The **ontology** holds the team's live research graph, including companies, people, themes, relationships, and sourced observations. The **claim graph** holds the team's theses, candidate memberships, catalysts, and predictions. Claim records link to the ontology entities they concern. The theme page and the company page each show the claims that touch them.

## Benefits

The team gets a shared list of companies it is watching for each thesis, the event it is waiting for, and why that event should matter. Recording the event and its expected effect separately lets the team learn whether a miss came from the event not happening or from the event not having the expected effect.

## Model

A catalyst does not tie a company to a thesis directly. Four linked records do.

- **Thesis.** The investment idea, such as "data center rollout benefits optical suppliers." It is its own claim record with an author, anchored to an ontology theme. One theme can hold several theses, including competing ones.
- **Candidate membership.** The link between a company and a thesis, with a status of candidate, in, or out. Every status change records a reason. A change comes either from a resolved prediction or from a direct analyst decision. A direct decision requires a written reason, such as "already ships 1.6T modules in volume to two hyperscalers," so the team can seed companies it already considers part of the thesis without inventing a catalyst.
- **Catalyst.** A future event on a company, its expected date or window, and what would count as occurrence. It resolves as occurred, did not occur, or open.
- **Prediction.** The conditional claim that if the catalyst occurs, the company's membership moves in a stated direction, and the reason the event should have that effect. Entry predictions move a candidate to in. Exit predictions move a member to out, such as a supplier losing its only hyperscaler customer. It resolves as followed, did not follow, or open.

The catalyst and the prediction are separate claims because an event can happen without moving the company.

| Catalyst | Prediction | What the team learns |
| --- | --- | --- |
| Occurred | Followed | The call was right. |
| Occurred | Did not follow | The event happened, but the stated reason was wrong or not enough. |
| Did not occur | Not tested | The event or timing call was wrong. The company's fit is still untested. |
| Open | Open | The team is still watching. |

A catalyst is attached to the company the event happens to. It reaches the thesis through its prediction, so one company page shows every catalyst the team is watching on that company, and one thesis page shows every catalyst that could add a company to it. One catalyst can carry predictions for more than one thesis.

## Scope

This epic is analyst-driven. Membership is the analyst's recorded decision, not a probability. Probability distributions over outcomes, automated impact-diff proposals, and forecast calibration are out of scope here. [Scenarios & Prediction](scenarios-and-prediction.md) covers proposed diffs, weighted outcomes, and calibration. A later probability on a prediction can be added without changing the thesis, membership, or catalyst records.

## Phasing

### Phase 1. Establish the claim graph

On the theme page, an analyst records a thesis, adds companies as candidates or as members with a reason, and records catalysts with entry or exit predictions. On the company page, the analyst sees the theses the company is a candidate for and the catalysts that bear on it.

The phase is complete when a teammate can start from either the thesis or the company and reach the candidate membership, its catalyst, its prediction, and what would resolve each. Recording these analyst-authored expectations is the full scope of Phase 1.

### Phase 2. Establish the feedback loop

Link sourced observations from the ontology to the catalyst or prediction they resolve. The analyst marks whether the catalyst occurred and, separately, whether the predicted membership change followed. Each can have a different outcome and date. Keep an item open when the evidence is insufficient. When a catalyst's window passes without the event, record it as did not occur and leave the company a candidate.

When a prediction resolves, the analyst updates the membership status and records the reasoning. Retain the original expectation and a dated history of evidence, decisions, and status changes. When the evidence warrants a change to the live ontology, such as a new relationship between the company and the theme, review the sourced diff before applying it through the existing write workflow. [Scenarios & Prediction](scenarios-and-prediction.md) covers proposals for graph changes and forecasts. Count repeated coverage of the same underlying event as one piece of evidence, and corroborate material changes prompted by rumors.

## Draft user journey

### Track a supplier qualification against a thesis

1. In Phase 1, an analyst opens the data center rollout theme and records the thesis that the rollout benefits optical module suppliers.
2. The analyst adds Supplier X as a candidate. Its 1.6T modules are not yet qualified at any hyperscaler, so it has no meaningful exposure to the rollout today.
3. The analyst records a catalyst on Supplier X: it completes qualification with a hyperscaler by the end of Q2. They add the prediction that qualification moves Supplier X into the thesis, because it would unlock volume orders tied to the rollout. They note that the prediction is supported by a first volume order within two quarters of qualification.
4. A teammate opens Supplier X's company page, sees that it is a candidate for the data center rollout thesis, and follows the link to the qualification catalyst and its prediction.
5. In Phase 2, Supplier X announces the qualification in May. The analyst links the press release and marks the catalyst as occurred. The prediction stays open, and Supplier X stays a candidate.
6. Two quarters later, channel checks show the hyperscaler has placed only sample orders, because it is sourcing volume from incumbents. The analyst links the evidence, marks the prediction as did not follow, and keeps Supplier X a candidate with a note that qualification alone was not enough. The team can see the original expectation, the event that happened, and why the company did not enter the thesis.
