# Scenarios & Prediction

## Outcome

An analyst can record a conditional prediction in the claim graph and link it to the hypothesis, catalyst, and ontology records it concerns. As evidence arrives, the analyst can submit news to `predict` and review an editable diff against a recorded graph baseline. The diff can propose a new entity, a new relationship, or a change to a relationship facet. Saved scenarios retain the author, assumptions, and forecast horizon in the claim graph.

## Benefits

Analysts can turn news into a specific research hypothesis and check which assumptions drive the expected changes. A saved baseline and time horizon let them revisit the prediction as evidence comes in.

## Phasing

**Phase 1 establishes the claim graph.** The [Theme Catalysts](theme-catalysts.md#phase-1-establish-the-claim-graph) epic captures analyst-authored hypotheses, catalyst criteria, and scenario predictions linked to existing ontology records.

**Phase 2 establishes the feedback loop.** Use `predict` to propose an editable diff against a recorded baseline and link it to the relevant claim, catalyst, and evidence. Review proposed live graph changes before applying them, and save conditional diffs as scenarios. As outcomes become observable, revisit the original assumptions and record what the evidence supported or contradicted. Phase 2 can extend this workflow to multiple outcomes with coarse probability estimates and track calibration across resolved forecasts.

## Draft user journey

### Turn a delay announcement into a proposed graph change

1. A data center operator announces a one-quarter deployment delay in its earnings release. An analyst submits the release to `predict` and asks how the delay might affect suppliers over the next two quarters.
2. The analyst sees the announced delay alongside the proposed change. One supplier's thematic exposure would move from positive to mixed if deferred deliveries push a material share of orders beyond that window. The prediction shows the current facet value, the proposed value, and the evidence it used.
3. The analyst reviews the assumption, adds a note about delivery timing, and saves the edited scenario against the graph baseline. They can reopen the saved diff while the live graph continues to show the existing exposure.
4. Once weighted outcomes are available, the analyst adds a second scenario in which deliveries recover within the window and exposure stays positive. They assign weights to the two outcomes and record what evidence would change their assessment.
