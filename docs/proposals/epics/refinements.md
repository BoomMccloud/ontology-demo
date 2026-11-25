# Claim Graph Refinements

## Outcome

When new evidence arrives, an analyst can see what it adds, which forecasts may need revisiting, and how those forecasts compare with market expectations. These refinements build on the research workflow in [Theme Catalysts](theme-catalysts.md) and [Scenarios & Prediction](scenarios-and-prediction.md).

## Benefits

Analysts can review evidence without counting repeated coverage twice, find the assumptions behind a forecast, and trace changes to the original source.

## Possible epics

### Evidence Intake & Corroboration

When a note enters the existing ingestion flow, show the relevant passage and suggest whether it adds a new observation, repeats an existing source, independently corroborates a claim, or challenges it. The analyst reviews the suggestion and confirms which claim, if any, the evidence belongs to. Keep each citation and count repeated coverage of the same underlying event once.

### Research Variables & Market Expectations

Let analysts compare their forecast with a dated, sourced market consensus estimate for the same company, metric, unit, and period. Start with one metric, such as annual 1.6T optical module shipments, and let analysts enter the market estimate manually. External feeds and expectations implied by the share price could follow.

### Forecast Dependencies

Let analysts link a saved forecast to an assumption it depends on. Start with explicit links, such as second-supplier qualification timing to shipment and gross-margin forecasts. When new evidence affects that assumption, flag the linked forecasts for review and show the evidence that prompted the flag.

### Research Source Integrations

Bring one frequently used source, such as meeting transcripts or research email, into the existing note workflow. Keep a reference to the original passage wherever the source supports it. Later integrations could add filings, chat, market data, or spreadsheet assumptions with cell references.

## Draft user journey

1. A supplier meeting transcript enters the note workflow with a reference to the qualification update.
2. The analyst confirms that the transcript adds new evidence of a delay. The shipment and margin forecasts that depend on the original qualification timing are flagged for review.
3. The analyst revisits the shipment forecast and compares it with the dated market estimate for the same product and year. A teammate can open the cited passage and see which assumption prompted the review.
