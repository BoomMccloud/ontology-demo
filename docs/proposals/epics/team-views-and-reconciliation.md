# Team Views & Reconciliation

## Outcome

Teammates can compare their saved scenarios side by side against a shared baseline. They can see where they differ on the change factor, the proposed graph diff, or the outcome weight, and record an agreed view while retaining individual views and dissent.

## Benefits

The team can focus its discussion on the specific assumption or expected change driving disagreement. Keeping the original views alongside the team decision makes it easier to revisit that decision when new evidence arrives.

## Phasing

Ship comparison once [Scenarios & Prediction](scenarios-and-prediction.md) supports saved scenarios with authors and comparable baselines. Start with change factors, assumptions, and diffs, then add weight reconciliation when weighted outcomes are available.

## Draft user journey

### Reconcile two views of the same qualification

This journey continues the Supplier X example from [Scenarios & Prediction](scenarios-and-prediction.md#draft-user-journey).

1. After Supplier X qualifies its 1.6T modules with a hyperscaler, two analysts save their views against the same graph baseline and two-quarter horizon. One expects volume orders to follow and puts Supplier X's entry into the data center rollout thesis at 60%. The other puts entry at 30%, citing the hyperscaler's long-term supply agreements with incumbents.
2. The portfolio manager opens the side-by-side comparison. Both analysts accept the qualification and the proposed qualified-supplier relationship. They differ on whether qualification leads to volume orders within the window. The comparison shows each analyst's probability and the evidence behind it.
3. After discussing the evidence, the team records a shared view: Supplier X stays a candidate for now, with entry at 45% and a first volume order as the trigger for revisiting. The decision cites the supply agreements and keeps both individual views.
4. A month later, a channel check finds only sample orders. Each view takes the same moderate update toward Supplier X staying a candidate. The first analyst's entry probability drops to 33%, the second's to 13%, and the team's to 21%.
5. At the end of the window, no volume order has come and the entry prediction resolves as did not follow. Each view is scored separately: 0.11 for the first analyst, 0.02 for the second, and 0.05 for the team. The team can see that the dissenting view was better calibrated on this call.
