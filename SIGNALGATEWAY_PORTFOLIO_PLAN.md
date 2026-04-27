# SignalGateway Portfolio Analysis & Optimization Plan

## Goal

Add an optional, configuration-driven portfolio analysis and optimization capability to `jh_quant.signalgateway.service` with minimal disruption to the current strategy-driven trading flow.

Core requirements:

1. Portfolio optimization and analysis must be optional.
2. It must be configuration-driven.
3. Prefer `Riskfolio-Lib` for optimization.
4. Price / return inputs must come from `MarketDataProvider`.
5. Add service/API support for portfolio analysis, optimization, and historical holdings analysis for later visualization.

## Todo Checklist

- [x] Phase 0: planning document added
- [x] Phase 1: portfolio config/spec models added
- [x] Phase 1: optional service constructor/config support added
- [x] Phase 1: portfolio optimizer registry metadata added
- [x] Phase 2: price/return matrix helpers added to `SignalGateway`
- [x] Phase 2: Riskfolio preview optimizer adapter added
- [x] Phase 3: target-weight to target-quantity allocator
- [x] Phase 3: rebalance order builder
- [x] Phase 3: rebalance policy decision engine
- [x] Phase 4: integrate optional portfolio path into `run_once()`
- [x] Phase 5: current portfolio analysis helpers added
- [x] Phase 5: historical weight history helpers added
- [x] Phase 6: portfolio config API endpoints
- [x] Phase 6: portfolio optimize preview API endpoint
- [x] Phase 6: portfolio analysis/history API endpoints
- [x] Phase 6: manual rebalance API endpoint
- [x] Phase 7: manual root-level portfolio smoke test file added
- [ ] Phase 7: automated tests for portfolio paths
- [ ] Phase 7: docs refresh after implementation stabilizes

## Guiding Principles

### 1. Non-invasive by default

Current behavior should remain unchanged unless portfolio features are explicitly enabled.

That means:

- existing `selection_spec + strategy_specs + position_sizer` flow remains valid
- current `execute_cycle()` behavior remains the default
- no portfolio optimization is run unless enabled in service config

### 2. Config-first

Portfolio behavior should be controlled through explicit config/spec objects rather than hard-coded branches.

### 3. Separation of concerns

We should separate:

- signal generation
- candidate ranking
- portfolio optimization
- order sizing / execution
- post-trade analysis

### 4. Progressive rollout

The first version should add a usable and safe portfolio layer without forcing a full rewrite of `SignalGateway`.

## Current State Summary

Today the flow is:

1. `selection_provider.select()` returns `top_selections`
2. `SignalGateway.execute_cycle()` loads price data
3. strategies generate buy/sell scores
4. `PositionSizer` converts candidate scores into `target_qty`
5. orders are executed

Key limitation:

- portfolio construction is implicit and local
- there is no first-class concept of target weights or portfolio policy
- `strategy weight` affects signal score aggregation, not final portfolio allocation policy

## Proposed Architecture

## New Portfolio Layer

Introduce a new optional portfolio module, likely under:

```text
jh_quant/signalgateway/portfolio/
  __init__.py
  config.py
  optimizer.py
  allocator.py
  analysis.py
  registry.py
```

### Responsibilities

- `config.py`
  - portfolio config/spec models
  - optimizer config models
  - rebalance policy config

- `optimizer.py`
  - Riskfolio-Lib adapter
  - convert market data to returns matrix
  - run optimization and output target weights

- `allocator.py`
  - translate target weights into tradable target quantities
  - account for cash, lot size, existing positions, max weight, etc.

- `analysis.py`
  - historical portfolio analysis
  - realized/target weight drift
  - concentration / turnover / risk contribution / performance decomposition

- `registry.py`
  - optional registry for portfolio optimizers, similar to strategy/selection registries

## Service Integration Design

### New Service-Level Concept

Add a portfolio feature switch and spec to `SignalGatewayService`.

Candidate shape:

- `portfolio_enabled: bool`
- `portfolio_spec: Optional[PortfolioSpec]`

Service behavior:

- if disabled: keep current sizing path
- if enabled: build a target portfolio proposal before final order sizing/execution

## When to Apply Portfolio Optimization

This is the key design decision.

### Option A: Re-optimize every cycle

Pros:

- always aligned with latest market state
- simplest mental model

Cons:

- can cause high turnover
- may fight strategy intent if signals fluctuate
- expensive and noisy in practical trading

### Option B: Only optimize on first entry

Pros:

- stable holdings
- low turnover

Cons:

- portfolio drifts over time
- strategy updates may not propagate well

### Option C: Policy-driven rebalance

Recommended.

Add a rebalance policy with modes such as:

- `disabled`
- `initial_only`
- `every_cycle`
- `drift_threshold`
- `schedule`
- `manual_only`

Recommended V1 default:

- portfolio feature enabled
- rebalance mode = `manual_only` or `drift_threshold`

Why:

- safer than re-optimizing every run
- keeps current execution chain stable
- supports explicit API-triggered adjustment

## Recommended V1 Execution Model

When portfolio mode is enabled:

1. selection provides eligible universe
2. strategies still produce scores
3. service forms candidate set
4. optimizer computes target weights for eligible symbols
5. allocator converts target weights to target quantities
6. execution compares current holdings vs target quantities
7. service only rebalances when rebalance policy says yes

Important:

Strategy score should remain relevant.

Recommended way:

- use strategy score to filter / rank / constrain the candidate universe
- use optimizer to decide final capital allocation inside that universe

This avoids replacing strategies entirely with optimizer output.

## Config Model Proposal

Add new config/spec models, likely in `signalgateway/config.py` or `signalgateway/portfolio/config.py`.

### PortfolioSpec

Possible fields:

- `enabled: bool = False`
- `optimizer: str = "riskfolio"`
- `objective: str = "sharpe"`
- `risk_measure: str = "MV"`
- `model: str = "Classic"`
- `historical_lookback_days: int = 252`
- `max_assets: Optional[int] = None`
- `min_weight: float = 0.0`
- `max_weight: float = 0.2`
- `cash_reserve_ratio: float = 0.0`
- `lot_size: int = 100`
- `allow_partial_rebalance: bool = True`
- `rebalance_policy: RebalancePolicySpec`
- `analysis: PortfolioAnalysisSpec`

### RebalancePolicySpec

Possible fields:

- `mode: str`
- `drift_threshold: Optional[float]`
- `min_rebalance_interval_seconds: Optional[int]`
- `schedule_cron: Optional[str]`
- `on_selection_change: bool = True`
- `on_strategy_change: bool = True`

### PortfolioAnalysisSpec

Possible fields:

- `enabled: bool = True`
- `benchmark_symbol: Optional[str]`
- `risk_free_rate: float = 0.0`
- `rolling_window: int = 60`

## Market Data / Returns Design

Optimizer input must come from `MarketDataProvider`.

Design:

1. fetch historical close prices from `SignalGateway.get_price_data()`
2. pivot to `date x symbol`
3. compute returns
4. clean missing values
5. pass returns to optimizer adapter

Potential helper methods:

- `build_price_matrix(symbols, start_date, end_date) -> pd.DataFrame`
- `build_return_matrix(price_df) -> pd.DataFrame`

## Riskfolio-Lib Integration

### Preferred integration

Create an adapter that:

- lazily imports `riskfolio`
- fails gracefully if missing and portfolio optimization is requested
- exposes a normalized interface to service code

Possible adapter interface:

```python
class PortfolioOptimizer(Protocol):
    def optimize(
        self,
        returns: pd.DataFrame,
        signals: Optional[pd.DataFrame],
        config: PortfolioSpec,
    ) -> pd.DataFrame:
        ...
```

Output:

- DataFrame with at least:
  - `symbol`
  - `target_weight`
  - maybe `score`
  - maybe diagnostics like `marginal_risk`, `risk_contribution`

### Fallback behavior

If `Riskfolio-Lib` is unavailable:

- do not affect current flow when portfolio is disabled
- raise a clear error only when the user explicitly requests riskfolio optimization

## Allocation / Execution Design

Today `PositionSizer` returns `target_qty` only.

Portfolio mode introduces target weights first.

### Recommended V1 approach

Do not remove `PositionSizer`.

Instead:

- keep current `PositionSizer` path for non-portfolio mode
- add a portfolio allocator path that converts `target_weight -> target_qty`

Possible new abstraction:

- `PortfolioAllocator`

Inputs:

- target weights
- latest prices
- available balance
- total equity
- current holdings

Outputs:

- target shares
- delta shares
- buy list
- sell list

### Why not force everything through `PositionSizer`

Because:

- current `PositionSizer` assumes candidate score-based sizing
- portfolio rebalancing needs current holding awareness and target-weight deltas
- mixing both responsibilities will make the current API awkward

## Historical Portfolio Analysis

Add service/API support for analytics based on:

- trade history
- daily performance snapshots
- position snapshots

### V1 analysis capabilities

1. historical weight trajectory
2. concentration analysis
3. turnover analysis
4. realized vs target allocation drift
5. holding contribution summary
6. basic risk/return summary from portfolio history

### V2 analysis capabilities

1. optimizer diagnostics
2. rolling volatility / Sharpe / drawdown
3. benchmark-relative analysis
4. factor / sector / style decomposition if metadata becomes available

## API Plan

Add a portfolio API surface under `/service/portfolio`.

### Config endpoints

- `GET /service/portfolio/config`
- `POST /service/portfolio/config`

### Optimization endpoints

- `POST /service/portfolio/optimize`
  - run optimization on demand
  - return target weights and diagnostics

- `POST /service/portfolio/rebalance`
  - execute or preview rebalance

### Analysis endpoints

- `GET /service/portfolio/analysis`
  - return current portfolio analytics snapshot

- `GET /service/portfolio/history`
  - return historical holdings / weights / portfolio value timeline

- `GET /service/portfolio/drift`
  - return current vs target drift metrics

### Preview-oriented endpoints

Recommended V1 support:

- `preview_only: bool`

This is especially useful before live rebalance.

## Service Methods to Add

Potential additions to `SignalGatewayService`:

- `configure_portfolio(...)`
- `get_portfolio_config_snapshot()`
- `get_portfolio_analysis_snapshot()`
- `optimize_portfolio(...)`
- `rebalance_portfolio(...)`
- `should_rebalance_portfolio(...)`
- `get_portfolio_history(...)`

Potential additions to `SignalGateway`:

- helper methods for price matrix / latest prices / tradable portfolio proposal

## Persistence / State Plan

V1 should avoid schema churn unless needed.

Recommended:

- store portfolio config in service state payload
- store optimization results / rebalance decisions in service state payload first
- reuse position snapshots and daily performance for historical analysis

Optional later:

- add dedicated portfolio target history persistence model
- add optimizer diagnostic history persistence model

## Phased Implementation Plan

## Phase 0: Planning

- document the architecture
- define rebalance policy and default behavior
- map integration points in service and signalgateway

Deliverable:

- this markdown plan

## Phase 1: Config + Domain Layer

- add portfolio config/spec models
- add schema exposure similar to strategy/selection config
- add optional service constructor/config support
- add registry / adapter interface for portfolio optimizer

Deliverable:

- portfolio can be configured but not yet actively used

## Phase 2: Riskfolio Optimizer Adapter

- implement Riskfolio adapter
- fetch price data from `MarketDataProvider`
- compute returns matrix
- return target weights and optimization diagnostics

Deliverable:

- `optimize_portfolio()` works in preview mode

## Phase 3: Allocation + Rebalance Engine

- convert target weights into target quantities
- compare with current holdings
- build rebalance orders
- implement rebalance policy decision logic

Deliverable:

- optional rebalance path integrated with service

## Phase 4: Service Execution Integration

- integrate portfolio mode into `run_once()`
- preserve current flow when disabled
- add manual rebalance entry points
- ensure current strategy sizing path remains untouched for legacy mode

Deliverable:

- service supports both classic mode and portfolio mode

## Phase 5: Analytics

- add current portfolio analysis
- add historical holdings / weight / drift analysis
- build service snapshot methods

Deliverable:

- API-ready portfolio analytics

## Phase 6: API

- add portfolio config endpoints
- add optimize / preview / rebalance endpoints
- add analysis/history endpoints

Deliverable:

- external clients can inspect, configure, optimize, and analyze portfolio behavior

## Phase 7: Documentation + Smoke Tests

- update docs
- extend smoke runner
- add tests for:
  - config validation
  - portfolio disabled path
  - optimizer preview
  - rebalance policy
  - analytics snapshots

## Key Design Decisions

### Decision A: Optional feature gate

Portfolio features should be entirely inactive unless enabled.

### Decision B: Policy-driven rebalance

Do not rebalance every cycle by default.

Recommended default:

- portfolio enabled but rebalance policy = `manual_only` or conservative `drift_threshold`

### Decision C: Strategy scores remain upstream signals

Portfolio optimizer should refine allocation, not replace the strategy layer entirely.

### Decision D: Preview-first API

Optimization and rebalance should support preview mode before order execution.

## Risks and Mitigations

### Risk 1: Excessive turnover

Mitigation:

- rebalance policy
- drift threshold
- minimum rebalance interval
- preview endpoint

### Risk 2: Optimization instability from poor data

Mitigation:

- configurable lookback windows
- missing-data filtering
- max asset cap
- fallback constraints

### Risk 3: Tight coupling with current sizing logic

Mitigation:

- add a separate portfolio allocator path
- do not overload current `PositionSizer` contract

### Risk 4: Optional dependency failures

Mitigation:

- lazy import `Riskfolio-Lib`
- fail only when portfolio optimization is requested

## Suggested First Implementation Slice

The best first implementation slice is:

1. add portfolio config/spec models
2. add service snapshot/config API for portfolio
3. add Riskfolio preview optimizer
4. do not auto-rebalance yet
5. add manual optimize/rebalance endpoints

This gives users immediate value with low risk and keeps current execution stable.

## Open Questions to Revisit During Implementation

1. Should optimization run only on `top_selections`, or also include current holdings to reduce turnover?
2. Should sell decisions remain signal-driven, or can optimizer reduce/remove holdings even without explicit sell signals?
3. Should portfolio mode bypass `PositionSizer`, or optionally combine optimizer weights with a final sizing cap layer?
4. Do we want dedicated persistence for target weights in V1, or is service state enough?
5. Should portfolio analytics include benchmark comparison in V1, or defer that to V2?
