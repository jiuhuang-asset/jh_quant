# Portfolio + Strategy Redesign Plan

## Goal

Make `portfolio_spec.enabled=True` behave like a portfolio overlay on top of
selection + strategy, instead of becoming a separate path that weakens the role
of `Strategy`.

Target execution model:

`Selection Universe -> Strategy Scores -> Portfolio Optimization -> Rebalance`

## Current Problems

1. The portfolio branch bypasses `gateway.execute_cycle`, so the behavior feels
   like a second trading mode instead of an enhancement to the main strategy flow.
2. Strategy scores are only used as a soft input to the optimizer and do not
   strongly control the target universe.
3. The resulting UX is counterintuitive: users usually expect strategy to be the
   primary decision layer, while portfolio optimization should be a sizing and
   risk-allocation layer.

## Design Decision

1. Keep `SelectionProvider` as the universe generator.
2. Keep `Strategy` as the primary alpha / ranking engine.
3. Use portfolio optimization only after strategy has produced scored candidates.
4. In portfolio mode:
   - optimize only on strategy-approved symbols when possible;
   - fall back to the raw selection universe only when strategy produces no
     positive buy scores, and log that fallback explicitly;
   - continue to rebalance current holdings toward the optimizer target.
5. Preserve T+1 sell protection in the rebalance path.

## Implementation Steps

1. Add service-layer helpers to build strategy-aware portfolio inputs.
2. Change `optimize_portfolio` to use a strategy-filtered optimization universe.
3. Enrich optimizer payload/diagnostics so the selected universe and fallback
   behavior are visible.
4. Update `run_once` / portfolio logs to clearly state that strategy remains the
   primary signal layer and portfolio is acting as an overlay.
5. Run syntax/import validation after refactor.

## Expected Outcome

- `portfolio_spec.enabled=False`
  uses the classic signal execution path.
- `portfolio_spec.enabled=True`
  still respects selection + strategy, but delegates sizing / allocation /
  rebalance to the portfolio engine.
- The branch split becomes intuitive rather than surprising.
