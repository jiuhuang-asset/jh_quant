from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from jh_quant.backtest.strategy import Strategy
from jh_quant.trading.market_data.models import QuoteSnapshot
from jh_quant.trading import (
    PaperBroker,
    PersistenceCoordinator,
    SelectionSnapshot,
    SessionService,
    SessionServiceConfigBuilder,
    StrategySpec,
    TradingEngine,
    register_selection_provider,
    register_strategy,
)
from jh_quant.trading.config import ClockMode, ExecutionMode, PortfolioSpec
from jh_quant.trading.persistence.recorder import OrderRecorder
from jh_quant.trading.position_sizer import FixedWeightPositionSizer


def unique_session_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class StaticSelectionProvider:
    symbols: list[str]
    source: str = "static"

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self.symbols),
            metadata={"as_of_date": as_of_date, "source": self.source},
        )

    @property
    def config(self) -> dict[str, Any]:
        return {"symbols": list(self.symbols), "source": self.source}


register_selection_provider("test_static_selector_v2", StaticSelectionProvider)


class DeterministicMarketDataProvider:
    def __init__(
        self,
        latest_prices: dict[str, float],
        *,
        history_days: int = 120,
    ):
        self.latest_prices = {
            str(symbol): float(price) for symbol, price in latest_prices.items()
        }
        self.history_days = history_days
        self._reference_time: Optional[pd.Timestamp] = None

    def set_reference_time(self, value) -> None:
        self._reference_time = None if value is None else pd.Timestamp(value)

    def get_latest_prices(
        self,
        symbols: list[str],
        as_of_date: Optional[str] = None,
    ) -> dict[str, float]:
        return {
            symbol: self.latest_prices[symbol]
            for symbol in symbols
            if symbol in self.latest_prices
        }

    def get_latest_quotes(
        self,
        symbols: list[str],
        as_of_date: Optional[str] = None,
    ) -> dict[str, QuoteSnapshot]:
        timestamp = (
            pd.Timestamp(as_of_date).to_pydatetime()
            if as_of_date is not None
            else (
                self._reference_time.to_pydatetime()
                if self._reference_time is not None
                else datetime.now()
            )
        )
        return {
            symbol: QuoteSnapshot(
                symbol=symbol,
                last_price=self.latest_prices[symbol],
                timestamp=timestamp,
            )
            for symbol in symbols
            if symbol in self.latest_prices
        }

    def get_price_data(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        frequency=None,
    ) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()

        end_ts = pd.Timestamp(end_date)
        start_ts = pd.Timestamp(start_date)
        effective_start = max(start_ts, end_ts - pd.Timedelta(days=self.history_days))
        dates = pd.date_range(effective_start, end_ts, freq="D")

        rows: list[dict[str, Any]] = []
        for symbol_index, symbol in enumerate(symbols):
            latest_price = float(self.latest_prices.get(symbol, 10.0 + symbol_index))
            base_price = max(1.0, latest_price - len(dates) * 0.1)
            for day_index, trade_date in enumerate(dates):
                close = base_price + day_index * 0.1
                rows.append(
                    {
                        "symbol": symbol,
                        "date": trade_date,
                        "open": close - 0.1,
                        "high": close + 0.2,
                        "low": close - 0.2,
                        "close": close,
                        "volume": 100000 + day_index,
                        "amount": close * (100000 + day_index),
                    }
                )
        return pd.DataFrame(rows)

    def get_trade_calendar(
        self,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ) -> set[str]:
        end_ts = pd.Timestamp(end_date or datetime.now().strftime("%Y-%m-%d"))
        dates = pd.date_range(pd.Timestamp(start_date), end_ts, freq="B")
        return {trade_date.strftime("%Y-%m-%d") for trade_date in dates}


class LastBarBuyStrategy(Strategy):
    def _execute_one(self, price: pd.DataFrame) -> pd.DataFrame:
        if price.empty:
            return pd.DataFrame(columns=["symbol", "date", "buy_signal", "sell_signal"])
        signal = price.copy()
        signal["buy_signal"] = 0
        signal["sell_signal"] = 0
        signal.iloc[-1, signal.columns.get_loc("buy_signal")] = 1
        return signal


class LastBarSellStrategy(Strategy):
    def _execute_one(self, price: pd.DataFrame) -> pd.DataFrame:
        if price.empty:
            return pd.DataFrame(columns=["symbol", "date", "buy_signal", "sell_signal"])
        signal = price.copy()
        signal["buy_signal"] = 0
        signal["sell_signal"] = 0
        signal.iloc[-1, signal.columns.get_loc("sell_signal")] = 2
        return signal


register_strategy("test_last_bar_buy", LastBarBuyStrategy)
register_strategy("test_last_bar_sell", LastBarSellStrategy)


class MemoryOrderRecorder(OrderRecorder):
    def __init__(self):
        self._trades: dict[str, dict[str, Any]] = {}
        self._daily_performance: dict[tuple[str, str], dict[str, Any]] = {}
        self._position_snapshots: dict[str, dict[str, Any]] = {}
        self._session_states: dict[str, list[dict[str, Any]]] = {}
        self._runtime_states: dict[str, dict[str, Any]] = {}
        self._runtime_events: dict[str, list[dict[str, Any]]] = {}
        self._session_configs: dict[str, list[dict[str, Any]]] = {}

    def create_schema(self):
        return None

    def save_trade(self, trade):
        self._trades[trade.trade_id] = trade.to_record_payload()

    def save_daily_snapshot(self, perf):
        payload = perf.to_record_payload()
        trade_date = pd.Timestamp(payload["trade_date"]).strftime("%Y-%m-%d")
        self._daily_performance[(payload["session_id"], trade_date)] = payload

    def save_position_snapshot(self, snapshot):
        self._position_snapshots[snapshot.snapshot_id] = snapshot.to_record_payload()

    def save_session_state(self, state: dict[str, Any]):
        session_id = state["session_id"]
        self._session_states.setdefault(session_id, []).append(state)
        self._session_states[session_id].sort(key=lambda item: item["export_time"])

    def load_latest_session_state(self, session_id: str) -> Optional[dict[str, Any]]:
        states = self._session_states.get(session_id, [])
        return states[-1] if states else None

    def save_runtime_state(self, state: dict[str, Any]):
        session_id = state["session_id"]
        self._runtime_states[session_id] = state
        event_type = (
            state.get("session", {})
            .get("extra", {})
            .get("event", "session_state_snapshot")
        )
        event_row = {
            "session_id": session_id,
            "event_type": event_type,
            "event_time": state.get("export_time"),
            "state_data": state,
        }
        self._runtime_events.setdefault(session_id, []).append(event_row)

    def load_latest_runtime_state(self, session_id: str) -> Optional[dict[str, Any]]:
        return self._runtime_states.get(session_id)

    def query_runtime_events(self, session_id: str) -> pd.DataFrame:
        rows = self._runtime_events.get(session_id, [])
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("event_time").reset_index(drop=True)

    def query_trades(self, session_id: str) -> pd.DataFrame:
        rows = [
            row for row in self._trades.values() if row["session_id"] == session_id
        ]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)

    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        rows = [
            row
            for row in self._daily_performance.values()
            if row["session_id"] == session_id
        ]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        rows = [
            row
            for row in self._position_snapshots.values()
            if row["session_id"] == session_id
        ]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)

    def save_session_config(
        self,
        session_id: str,
        config_bundle: dict[str, Any],
        *,
        source: str = "runtime_update",
    ):
        row = {
            "session_id": session_id,
            "config_bundle": config_bundle,
            "source": source,
            "export_time": config_bundle.get("export_time"),
        }
        self._session_configs.setdefault(session_id, []).append(row)

    def load_latest_session_config(self, session_id: str) -> Optional[dict[str, Any]]:
        rows = self._session_configs.get(session_id, [])
        return rows[-1] if rows else None

    def count_session_configs(self, session_id: str) -> int:
        return len(self._session_configs.get(session_id, []))

    def load_earliest_session_config(self, session_id: str) -> Optional[dict[str, Any]]:
        rows = self._session_configs.get(session_id, [])
        return rows[0] if rows else None

    def query_session_configs(self, session_id: str) -> list[dict[str, Any]]:
        return list(self._session_configs.get(session_id, []))


def sqlite_db_path(tmp_path: Path, session_id: str) -> str:
    return str((tmp_path / f"{session_id}.sqlite3").resolve())


def build_service(
    *,
    session_id: str,
    latest_prices: Optional[dict[str, float]] = None,
    selection_symbols: Optional[list[str]] = None,
    strategy_specs: Optional[list[dict[str, Any]]] = None,
    portfolio_spec: Optional[PortfolioSpec] = None,
    persistence: Optional[PersistenceCoordinator] = None,
    recorder: Optional[OrderRecorder] = None,
    auto_start: bool = False,
    cron_expression: Optional[str] = None,
    restore_persisted_state: bool = True,
) -> SessionService:
    latest_prices = latest_prices or {"AAA": 10.0, "BBB": 12.0, "CCC": 14.0}
    selection_symbols = selection_symbols or list(latest_prices.keys())
    recorder = recorder or MemoryOrderRecorder()
    persistence = persistence or PersistenceCoordinator(recorder=recorder)

    gateway = TradingEngine(
        broker=PaperBroker(session_id=session_id, initial_capital=100000.0),
        market_data_provider=DeterministicMarketDataProvider(latest_prices),
        position_sizer=FixedWeightPositionSizer(max_stocks=max(1, len(selection_symbols))),
        strict_mode=False,
    )

    builder = (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id=session_id,
            execution_mode=ExecutionMode.PAPER,
            clock_mode=ClockMode.REALTIME,
            auto_start=auto_start,
            cron_expression=cron_expression,
            restore_persisted_state=restore_persisted_state,
            price_lookback_days=180,
            max_candidates=20,
        )
        .with_selection(
            name="test_static_selector_v2",
            params={"symbols": selection_symbols, "source": "fixture"},
            alias="fixture_selector",
        )
    )

    for spec in strategy_specs or [
        {"name": "test_last_bar_buy", "alias": "last_bar_buy", "weight": 1.0}
    ]:
        builder = builder.add_strategy(**spec)

    if portfolio_spec is not None:
        builder = builder.with_portfolio_spec(portfolio_spec)

    config = builder.build()
    return SessionService(
        gateway=gateway,
        config=config,
        persistence=persistence,
    )
