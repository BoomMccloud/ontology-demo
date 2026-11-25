# Scenarios & Prediction

## Outcome

An analyst can record a conditional prediction in the claim graph and link it to the thesis, candidate membership, catalyst, and ontology records it concerns. As evidence arrives, the analyst can submit news to `predict` and review an editable diff against a recorded graph baseline. The diff can propose a new entity, a new relationship, or a change to a relationship facet. Saved scenarios retain the author, assumptions, and forecast horizon in the claim graph.

## Benefits

Analysts can turn news into a specific research hypothesis and check which assumptions drive the expected changes. A saved baseline and time horizon let them revisit the prediction as evidence comes in.

## Phasing

**Phase 1 establishes the claim graph.** The [Theme Catalysts](theme-catalysts.md#phase-1-establish-the-claim-graph) epic captures analyst-authored theses, candidate companies, catalysts, and predictions linked to existing ontology records.

**Phase 2 establishes the feedback loop.** Use `predict` to propose an editable diff against a recorded baseline and link it to the relevant claim, catalyst, and evidence. Review proposed live graph changes before applying them, and save conditional diffs as scenarios. As outcomes become observable, revisit the original assumptions and record what the evidence supported or contradicted. Phase 2 can extend this workflow to multiple outcomes with coarse probability estimates and track calibration across resolved forecasts.

## Probability updates and calibration

**Probabilities.** Each prediction can carry a probability. The scenarios for one catalyst are mutually exclusive, and their probabilities sum to 100%. The analyst sets a starting probability when saving the scenario.

**Log-odds updates.** When new evidence arrives, the analyst rates how much more likely that evidence is under one scenario than the other, using a fixed set of buckets: weak (1.5 times as likely), moderate (3 times), or strong (10 times). The update adds the log of that ratio to the scenario's log-odds and converts the result back to a probability. For example, a 40% scenario that receives moderate supporting evidence moves to about 67%. `predict` can suggest a bucket, but the analyst confirms it. Evidence about the same underlying event counts once, following the corroboration rules in [Theme Catalysts](theme-catalysts.md). The analyst can override the computed probability with a written reason, and each update keeps its evidence, bucket, and date.

**Brier scores.** When a prediction resolves as followed or did not follow, record its Brier score: the squared difference between the last probability before resolution and the outcome (1 if it followed, 0 if not). Lower is better. A 70% prediction that followed scores 0.09, and one that did not scores 0.49. Open predictions are not scored, and a prediction whose catalyst did not occur is not scored, because its mechanism was never tested. Show the average score by analyst and by thesis, plus a calibration view that compares predicted probabilities with how often predictions in each probability range followed.

## Draft user journey

### Turn a qualification announcement into weighted scenarios

This journey continues the Supplier X example from [Theme Catalysts](theme-catalysts.md#draft-user-journey). Supplier X is a candidate for the data center rollout thesis, and the team is watching for it to complete qualification with a hyperscaler by the end of Q2.

1. In May, Supplier X announces that its 1.6T modules have qualified with a hyperscaler. An analyst marks the catalyst as occurred, submits the press release to `predict`, and asks how the qualification might change Supplier X's place in the thesis over the next two quarters.
2. `predict` proposes a diff against the recorded graph baseline: a new relationship showing Supplier X as a qualified supplier to the hyperscaler. It also proposes the membership effect, Supplier X moving from candidate to in. The analyst sees the current values, the proposed values, and the evidence `predict` used.
3. The analyst saves two scenarios against that baseline. In the first, volume orders follow within two quarters and Supplier X enters the thesis, at 60%. In the second, the hyperscaler keeps sourcing volume from incumbents and Supplier X stays a candidate, at 40%. The analyst records what would separate them: a first volume order. The live graph is unchanged.
4. A month later, a channel check finds the hyperscaler has placed only sample orders with Supplier X. The analyst rates this as moderate evidence for the second scenario. The first scenario drops from 60% to 33%, and the update keeps the channel check, the rating, and the date.
5. At the end of the two quarters, no volume order has come. The analyst resolves the first scenario as did not follow, and it records a Brier score of 0.11. The analyst applies the qualified-supplier relationship to the live ontology, because the qualification did happen. They reject the membership change, so Supplier X stays a candidate. The team can see the original scenarios, each probability update, and the evidence behind them.
