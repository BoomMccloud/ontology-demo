# Team Views & Reconciliation

## Outcome

Teammates can compare their saved scenarios side by side against a shared baseline. They can see where they differ on the change factor, the proposed graph diff, or the outcome weight, and record an agreed view while retaining individual views and dissent.

## Benefits

The team can focus its discussion on the specific assumption or expected change driving disagreement. Keeping the original views alongside the team decision makes it easier to revisit that decision when new evidence arrives.

## Phasing

Ship comparison once [Scenarios & Prediction](scenarios-and-prediction.md) supports saved scenarios with authors and comparable baselines. Start with change factors, assumptions, and diffs, then add weight reconciliation when weighted outcomes are available.

## Draft user journey

### Reconcile two views of the same delay

1. After a data center operator announces a one-quarter deployment delay, two analysts save their views against the same graph baseline and two-quarter horizon. One expects enough orders to slip for the supplier's exposure to turn mixed. The other expects deliveries to recover within the window and exposure to stay positive.
2. The portfolio manager opens the side-by-side comparison and sees that both analysts accept the announced delay. They differ on whether it will push supplier orders beyond the forecast window. When weights are available, the comparison also shows the weight each analyst assigned to the same outcome.
3. After discussing the evidence, the team records a shared view that exposure stays positive for now, with a second delay as the trigger for revisiting it. The decision cites the supporting evidence and retains the more cautious analyst's view.
4. At the next update, the team reopens the decision and checks whether delivery guidance changes the shared view or the weight it gives the downside outcome.
