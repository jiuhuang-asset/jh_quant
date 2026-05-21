from __future__ import annotations

import traceback
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

from ..config import ClockMode, Frequency
from ..market_data.protocols import ReferenceTimeAware
from ..service.schemas import TradingCycleResult

if TYPE_CHECKING:
    from ..service.core import SessionService


class SessionCycleCoordinator:
    """Owns cycle execution and backfill time progression for a session."""

    def __init__(self, service: "SessionService"):
        self.service = service

    def _normalize_selection_metadata(
        self,
        selection: Any,
        *,
        cycle_date: str,
    ) -> Dict[str, Any]:
        if hasattr(selection, "metadata") and selection.metadata:
            return selection.metadata

        metadata: Dict[str, Any] = {"as_of_date": cycle_date}
        known = {"top_selections", "bottom_selections", "metadata"}
        for key in dir(selection):
            if key.startswith("_") or key in known:
                continue
            value = getattr(selection, key, None)
            if not callable(value):
                metadata[key] = value
        return metadata

    def run_cycle(self, as_of_date: Optional[str] = None) -> TradingCycleResult:
        service = self.service
        if service._scheduler_stop_event.is_set():
            raise RuntimeError("Session is shutting down, run_once rejected")

        with service._lock:
            cycle_date = service._as_of_date(as_of_date)
            trade_calendar = service._get_trade_calendar()
            if trade_calendar and cycle_date not in trade_calendar:
                service._log_execution_branch(
                    "run_once",
                    f"{cycle_date} is not a trading day, cycle skipped",
                )
                return TradingCycleResult(
                    session_id=service.config.session_id,
                    mode=service._runtime_mode_key(),
                    cycle_time=datetime.now().isoformat(),
                    selection_count=0,
                    long_candidate_count=0,
                    short_candidate_count=0,
                    executed_buy_count=0,
                    executed_sell_count=0,
                    status="skipped",
                    error=f"non-trading day: {cycle_date}",
                )

            price_start = service._price_start_date(cycle_date)
            selection = service.selection_provider.select(as_of_date=cycle_date)
            top_selections = selection.top_selections
            selection_meta = self._normalize_selection_metadata(
                selection,
                cycle_date=cycle_date,
            )

            executed_buy_count = 0
            executed_sell_count = 0
            long_candidates = pd.DataFrame()
            short_candidates = pd.DataFrame()
            portfolio_cycle_payload: Optional[Dict[str, Any]] = None

            if service.portfolio_spec.enabled:
                service._log_execution_branch(
                    "portfolio",
                    (
                        "run_once detected portfolio mode; selection and strategy "
                        "decide the universe, and portfolio runtime owns sizing "
                        "and rebalance execution"
                    ),
                )
                if top_selections:
                    portfolio_cycle_payload = service.rebalance_portfolio(
                        as_of_date=cycle_date,
                        symbols=top_selections,
                        preview_only=False,
                        force=False,
                    )
                else:
                    portfolio_cycle_payload = service._empty_portfolio_cycle_payload(
                        cycle_date,
                        "no selected symbols for portfolio rebalance",
                    )

                long_candidates = pd.DataFrame(
                    portfolio_cycle_payload.get("buy_orders", [])
                )
                short_candidates = pd.DataFrame(
                    portfolio_cycle_payload.get("sell_orders", [])
                )
                executed_buy_count = int(
                    portfolio_cycle_payload.get("executed_buy_count", 0)
                )
                executed_sell_count = int(
                    portfolio_cycle_payload.get("executed_sell_count", 0)
                )
            else:
                service._log_execution_branch(
                    "signals",
                    (
                        "run_once detected signal-execution mode; "
                        "delegating to gateway.execute_cycle"
                    ),
                )
                executed_buys, executed_sells, long_candidates, short_candidates = (
                    service.gateway.execute_cycle(
                        top_selections=top_selections,
                        price_start=price_start,
                        cycle_date=cycle_date,
                        frequency=service.config.frequency,
                        max_candidates=service.config.max_candidates,
                        price_slippage=service.config.price_slippage,
                    )
                )

                service._persist_trades(executed_sells)
                service._persist_trades(executed_buys)
                executed_buy_count = len(executed_buys)
                executed_sell_count = len(executed_sells)

            if hasattr(service.gateway.broker, "compute_daily_metrics"):
                cycle_dt = datetime.strptime(cycle_date, "%Y-%m-%d")
                latest_price_symbols = list(top_selections)
                current_holds = getattr(service.gateway.broker.get_positions(), "holds", [])
                latest_price_symbols.extend(
                    hold.symbol
                    for hold in current_holds
                    if getattr(hold, "symbol", None)
                )
                latest_price_symbols = list(dict.fromkeys(latest_price_symbols))
                latest_prices = (
                    service.gateway.get_latest_prices(latest_price_symbols)
                    if hasattr(service.gateway, "get_latest_prices")
                    else pd.Series(dtype=float)
                )
                close_prices = (
                    latest_prices.to_dict() if not latest_prices.empty else None
                )
                perf, snapshots = service.gateway.broker.compute_daily_metrics(
                    trade_date=cycle_dt,
                    close_prices=close_prices,
                )
                service.persistence.persist_daily_metrics(perf, snapshots)

            result = TradingCycleResult(
                session_id=service.config.session_id,
                mode=service._runtime_mode_key(),
                cycle_time=datetime.now().isoformat(),
                selection_count=len(top_selections),
                long_candidate_count=len(long_candidates),
                short_candidate_count=len(short_candidates),
                executed_buy_count=executed_buy_count,
                executed_sell_count=executed_sell_count,
                selected_symbols=top_selections,
                long_symbols=(
                    []
                    if long_candidates.empty or "symbol" not in long_candidates.columns
                    else long_candidates["symbol"].tolist()
                ),
                short_symbols=(
                    []
                    if short_candidates.empty
                    or "symbol" not in short_candidates.columns
                    else short_candidates["symbol"].tolist()
                ),
            )
            service._last_result = result
            service._last_error = None
            extra = {"selection_metadata": selection_meta}
            if portfolio_cycle_payload is not None:
                extra["portfolio_rebalance"] = portfolio_cycle_payload
            service._persist_runtime_state(extra=extra)
            return result

    def _is_frequency_suitable_for_backfill(self) -> bool:
        return self.service.config.frequency in {Frequency.DAILY}

    def run_backfill(self) -> Optional[TradingCycleResult]:
        service = self.service
        if service.config.clock_mode != ClockMode.BACKFILL:
            raise ValueError("clock_mode is not backfill")
        if service.config.backfill_start is None:
            raise ValueError("backfill_start must be set when clock_mode=backfill")
        if not self._is_frequency_suitable_for_backfill():
            raise ValueError(
                "Backfill only supports Daily or coarser frequencies, "
                f"got {service.config.frequency.value}"
            )

        config_from = datetime.strptime(service.config.backfill_start, "%Y-%m-%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        backfill_end = today - timedelta(days=1)
        if config_from >= today:
            raise ValueError(
                f"backfill_start ({service.config.backfill_start}) must be before today"
            )

        backfill_start = config_from
        existing = None
        try:
            existing = service.persistence.query_daily_performance(
                service.config.session_id
            )
            if existing is not None and not existing.empty:
                last_date_val = existing["trade_date"].max()
                if hasattr(last_date_val, "strftime"):
                    last_date_str = last_date_val.strftime("%Y-%m-%d")
                else:
                    last_date_str = str(last_date_val)[:10]
                last_dt = datetime.strptime(last_date_str, "%Y-%m-%d")

                config_count = service.persistence.count_session_configs(
                    service.config.session_id
                )
                if config_count >= 2:
                    service._log_execution_branch(
                        "backfill",
                        (
                            f"session has {config_count} persisted config versions; "
                            f"resuming from {max(last_dt, config_from).strftime('%Y-%m-%d')} "
                            "may mix outputs from multiple config revisions"
                        ),
                    )
                if last_dt >= config_from:
                    backfill_start = last_dt + timedelta(days=1)
                    service._log_execution_branch(
                        "backfill",
                        (
                            f"resuming backfill after persisted daily_performance on "
                            f"{last_date_str}; next day is {backfill_start.strftime('%Y-%m-%d')}"
                        ),
                    )
        except Exception as exc:
            service._log_execution_branch(
                "backfill",
                f"daily_performance lookup failed, falling back to broker history: {exc}",
            )
        else:
            if existing is None or existing.empty:
                service._log_execution_branch(
                    "backfill",
                    "no persisted daily_performance found, checking broker history",
                )

        broker = getattr(service.gateway, "broker", None)
        broker_trades = getattr(broker, "trades", None) if broker is not None else None
        if broker_trades:
            broker_last_trade_dt: Optional[datetime] = None
            for trade in broker_trades:
                td = getattr(trade, "trade_date", None)
                if td is None:
                    continue
                if hasattr(td, "to_pydatetime"):
                    dt = td.to_pydatetime()
                elif hasattr(td, "strftime"):
                    dt = datetime.strptime(td.strftime("%Y-%m-%d"), "%Y-%m-%d")
                else:
                    dt = datetime.strptime(str(td)[:10], "%Y-%m-%d")
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                if broker_last_trade_dt is None or dt > broker_last_trade_dt:
                    broker_last_trade_dt = dt
            if broker_last_trade_dt is not None and broker_last_trade_dt >= backfill_start:
                broker_next = broker_last_trade_dt + timedelta(days=1)
                service._log_execution_branch(
                    "backfill",
                    (
                        f"resuming backfill after broker trade history on "
                        f"{broker_last_trade_dt.strftime('%Y-%m-%d')}; "
                        f"next day is {broker_next.strftime('%Y-%m-%d')}"
                    ),
                )
                backfill_start = broker_next
        else:
            service._log_execution_branch(
                "backfill",
                "broker has no restored trade history; backfill will start from the configured date",
            )

        md_provider = getattr(service.gateway, "market_data_provider", None)
        if md_provider is None:
            raise RuntimeError("No market_data_provider available for backfill")
        if not isinstance(md_provider, ReferenceTimeAware):
            raise RuntimeError(
                "market_data_provider does not support reference-time backfill"
            )

        total_days = (backfill_end - backfill_start).days + 1
        if total_days <= 0:
            service._log_execution_branch(
                "backfill",
                f"backfill is already up to date for {service.config.session_id}",
            )
            return None

        service._log_execution_branch(
            "backfill",
            (
                f"starting backfill for {service.config.session_id}, "
                f"start={backfill_start.strftime('%Y-%m-%d')}, "
                f"end={backfill_end.strftime('%Y-%m-%d')}, days={total_days}"
            ),
        )

        try:
            pre_selection = service.selection_provider.select(
                as_of_date=backfill_start.strftime("%Y-%m-%d")
            )
            pre_symbols = pre_selection.top_selections
            if pre_symbols:
                service._log_execution_branch(
                    "backfill",
                    (
                        f"prefetching historical price data for {len(pre_symbols)} symbols, "
                        f"{backfill_start.strftime('%Y-%m-%d')}~{backfill_end.strftime('%Y-%m-%d')}"
                    ),
                )
                _ = service.gateway.get_price_data(
                    symbols=pre_symbols,
                    start_date=backfill_start.strftime("%Y-%m-%d"),
                    end_date=backfill_end.strftime("%Y-%m-%d"),
                )
        except Exception:
            pass

        last_result: Optional[TradingCycleResult] = None
        current = backfill_start
        day_count = 0

        try:
            while current <= backfill_end:
                current_str = current.strftime("%Y-%m-%d")
                try:
                    md_provider.set_reference_time(current_str)
                    service.gateway.broker.set_simulation_date(current)
                    last_result = self.run_cycle(as_of_date=current_str)
                    day_count += 1
                    if day_count % 30 == 0 or day_count == 1:
                        service._log_execution_branch(
                            "backfill",
                            (
                                f"progress {day_count}/{total_days}, current={current_str}, "
                                f"executed_buys={last_result.executed_buy_count}, "
                                f"executed_sells={last_result.executed_sell_count}"
                            ),
                        )
                except Exception:
                    service._log_execution_branch(
                        "backfill",
                        f"backfill failed on {current_str}: {traceback.format_exc()}",
                    )
                    day_count += 1
                finally:
                    current += timedelta(days=1)
        finally:
            md_provider.set_reference_time(None)
            service.gateway.broker.set_simulation_date(None)

        service._log_execution_branch(
            "backfill",
            (
                f"backfill completed, processed {day_count} days, "
                f"configured_start={service.config.backfill_start}"
            ),
        )
        return last_result
