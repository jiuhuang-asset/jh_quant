from __future__ import annotations

import importlib
import random
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pandas as pd

from ..models import Order, Positions, StockHoldRecord, Trade
from .paper import PaperBroker


class XtQuantBroker(PaperBroker):
    """Broker adapter backed by xtquant / MiniQMT.

    The current trading engine expects synchronous ``Trade`` objects from
    ``signal_buy`` / ``signal_sell``. xtquant natively returns an order ID
    first and the real fill lifecycle via callbacks. To keep the current
    broker contract stable, this adapter records an optimistic trade object once the
    broker accepts the order request, attaching the xtquant order ID to
    ``Trade.order_id``.
    """

    def __init__(
        self,
        miniqmt_path: str,
        stock_account: str,
        *,
        session_id: Optional[str] = None,
        trader_session_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
        restore_from: Optional[str] = None,
        state_dict: Optional[Dict[str, Any]] = None,
        auto_connect: bool = True,
        verify_trade_permissions: bool = True,
    ) -> None:
        self._validate_platform()
        self.miniqmt_path = self._normalize_miniqmt_path(miniqmt_path)
        self.stock_account = str(stock_account)
        self.trader_session_id = trader_session_id or random.randint(100000, 999999)
        self.verify_trade_permissions = verify_trade_permissions
        self._xt = self._load_xt_modules()
        self._trader = None
        self._account = None
        self._connected = False
        self._can_use_volume_by_symbol: dict[str, int] = {}

        super().__init__(
            initial_capital=0.0,
            session_id=session_id,
            start_time=start_time,
            restore_from=restore_from,
            state_dict=state_dict,
        )

        if auto_connect:
            self.connect()

    @staticmethod
    def _validate_platform() -> None:
        if sys.platform == "darwin":
            raise RuntimeError(
                "XtQuantBroker requires a Windows MiniQMT runtime. macOS is not an "
                "officially supported xtquant trading platform. Recommended setup: "
                "run the broker on Windows and keep the strategy / API layer remote."
            )
        if sys.platform.startswith("linux"):
            raise RuntimeError(
                "XtQuantBroker requires Windows MiniQMT for trading. The official "
                "xtquant Linux package supports xtdata only and does not support "
                "xttrade."
            )
        if not sys.platform.startswith("win"):
            raise RuntimeError(
                f"XtQuantBroker requires Windows MiniQMT. Current platform: {sys.platform}."
            )

    @staticmethod
    def _normalize_miniqmt_path(miniqmt_path: str) -> Path:
        path = Path(miniqmt_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(
                "MiniQMT path does not exist: "
                f"{path}. Expected the MiniQMT 'userdata_mini' directory."
            )
        if not path.is_dir():
            raise NotADirectoryError(
                f"MiniQMT path must be a directory, got: {path}"
            )
        return path

    @staticmethod
    def _load_xt_modules() -> SimpleNamespace:
        try:
            xttrader = importlib.import_module("xtquant.xttrader")
            xttype = importlib.import_module("xtquant.xttype")
            xtconstant = importlib.import_module("xtquant.xtconstant")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "xtquant is not installed or not available in the current Python "
                "environment. Install xtquant in the same interpreter that runs "
                "jh_quant, and make sure MiniQMT / QMT has already provided the "
                "matching runtime files."
            ) from exc
        return SimpleNamespace(
            XtQuantTrader=xttrader.XtQuantTrader,
            StockAccount=xttype.StockAccount,
            xtconstant=xtconstant,
        )

    def connect(self) -> None:
        self._assert_path_hint()
        self._account = self._build_stock_account(self.stock_account)
        self._trader = self._xt.XtQuantTrader(
            str(self.miniqmt_path),
            self.trader_session_id,
        )
        self._trader.start()
        connect_result = self._trader.connect()
        if connect_result != 0:
            raise RuntimeError(self._build_connect_failure_message(connect_result))
        subscribe_result = self._trader.subscribe(self._account)
        if subscribe_result not in (None, 0):
            raise RuntimeError(
                "XtQuantBroker connected to MiniQMT but failed to subscribe the stock "
                f"account {self.stock_account}. subscribe() returned {subscribe_result}."
            )
        self._connected = True
        self._sync_from_broker()

    def disconnect(self) -> None:
        if self._trader is not None:
            try:
                self._trader.stop()
            except Exception:
                pass
        self._connected = False

    def _assert_path_hint(self) -> None:
        if self.miniqmt_path.name.lower() != "userdata_mini":
            raise RuntimeError(
                "XtQuantBroker expects the MiniQMT 'userdata_mini' directory. "
                f"Current path: {self.miniqmt_path}"
            )

    def _build_stock_account(self, stock_account: str):
        try:
            return self._xt.StockAccount(stock_account)
        except TypeError:
            return self._xt.StockAccount(stock_account, "STOCK")

    def _build_connect_failure_message(self, connect_result: int) -> str:
        hints = [
            f"XtQuantBroker failed to connect to MiniQMT, connect() returned {connect_result}.",
            f"MiniQMT path: {self.miniqmt_path}",
            "Check that MiniQMT is already started and logged in with 'extreme simple mode' / 'MiniQMT mode'.",
            "Check that the path points to the 'userdata_mini' directory rather than the install root.",
            "If MiniQMT was installed on C:, try running with administrator privileges or reinstall outside C:.",
            "If you reconnect from a new Python process, try a different trader_session_id or wait a few seconds before reconnecting.",
        ]
        queue_file = self.miniqmt_path / "up_queue_xtquant"
        if self.verify_trade_permissions and not queue_file.exists():
            hints.append(
                "MiniQMT trade permission file 'up_queue_xtquant' was not found in "
                "userdata_mini. This usually means the broker-side xtquant trading "
                "permission has not been enabled yet."
            )
        return " ".join(hints)

    def _ensure_connected(self) -> None:
        if not self._connected or self._trader is None or self._account is None:
            raise RuntimeError(
                "XtQuantBroker is not connected. Call connect() after MiniQMT has been "
                "started and logged in."
            )

    def _sync_from_broker(self) -> None:
        self._ensure_connected()
        previous_holds = {hold.symbol: hold for hold in self.holds}
        asset = self._trader.query_stock_asset(self._account)
        positions = self._trader.query_stock_positions(self._account) or []

        holds: list[StockHoldRecord] = []
        can_use_map: dict[str, int] = {}
        for position in positions:
            symbol = self._strip_market_suffix(getattr(position, "stock_code", ""))
            volume = int(getattr(position, "volume", 0) or 0)
            if volume <= 0:
                continue
            can_use_volume = int(getattr(position, "can_use_volume", volume) or 0)
            avg_cost = float(getattr(position, "avg_price", 0.0) or 0.0)
            market_value = float(getattr(position, "market_value", 0.0) or 0.0)
            if avg_cost <= 0 and volume > 0 and market_value > 0:
                avg_cost = market_value / volume
            entry_time = previous_holds.get(symbol, None)
            holds.append(
                StockHoldRecord(
                    symbol=symbol,
                    volume=volume,
                    sellable_volume=can_use_volume,
                    avg_cost=avg_cost,
                    market_value=market_value,
                    entry_time=entry_time.entry_time if entry_time else self._now(),
                )
            )
            can_use_map[symbol] = max(0, min(can_use_volume, volume))

        total_asset = float(getattr(asset, "total_asset", 0.0) or 0.0)
        cash = float(getattr(asset, "cash", 0.0) or 0.0)

        self.holds = holds
        self._can_use_volume_by_symbol = can_use_map
        self.available_balance = cash
        self.total = total_asset if total_asset > 0 else cash + sum(
            hold.market_value for hold in holds
        )
        if self.initial_capital <= 0 and self.total > 0:
            self.initial_capital = self.total
            self._prev_portfolio_value = self.total
        self.total_profit = self.total - self.initial_capital

    @staticmethod
    def _strip_market_suffix(stock_code: str) -> str:
        stock_code = str(stock_code).upper()
        return stock_code.split(".", 1)[0]

    @staticmethod
    def _normalize_symbol_for_xtquant(symbol: str) -> str:
        symbol = str(symbol).upper()
        if "." in symbol:
            return symbol
        if symbol.startswith(("5", "6", "9")):
            return f"{symbol}.SH"
        if symbol.startswith(("0", "1", "2", "3")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
        raise ValueError(
            f"Unable to infer exchange suffix for symbol '{symbol}'. "
            "Use a full xtquant code such as 600519.SH or 000001.SZ."
        )

    def get_positions(self) -> Positions:
        self._sync_from_broker()
        return Positions(
            total=self.total,
            available_balance=self.available_balance,
            total_profit=self.total_profit,
            daily_profit=self.daily_profit,
            holds=self.holds,
        )

    def get_available_balance(self) -> float:
        self._sync_from_broker()
        return self.available_balance

    def update_position_market_value(self, price_dict: dict) -> None:
        for hold in self.holds:
            if hold.symbol in price_dict:
                hold.market_value = hold.volume * float(price_dict[hold.symbol])

    @property
    def executable_holds(self):
        self._sync_from_broker()
        result = []
        for hold in self.holds:
            can_use = self._can_use_volume_by_symbol.get(hold.symbol, 0)
            if can_use <= 0:
                continue
            result.append(
                StockHoldRecord(
                    symbol=hold.symbol,
                    volume=can_use,
                    sellable_volume=can_use,
                    avg_cost=hold.avg_cost,
                    market_value=(hold.market_value / hold.volume * can_use)
                    if hold.volume > 0
                    else 0.0,
                    entry_time=hold.entry_time,
                )
            )
        return result

    def signal_buy(self, order: Order) -> Trade:
        return self._submit_order(order, trade_type="BUY")

    def signal_sell(self, order: Order) -> Trade:
        return self._submit_order(order, trade_type="SELL")

    def _submit_order(self, order: Order, *, trade_type: str) -> Trade:
        self._ensure_connected()
        if int(order.volume) <= 0:
            raise ValueError(f"Order volume must be positive, got {order.volume}.")

        xt_symbol = self._normalize_symbol_for_xtquant(order.symbol)
        order_type = (
            self._xt.xtconstant.STOCK_BUY
            if trade_type == "BUY"
            else self._xt.xtconstant.STOCK_SELL
        )
        order_id = self._trader.order_stock(
            account=self._account,
            stock_code=xt_symbol,
            order_type=order_type,
            order_volume=int(order.volume),
            price_type=self._xt.xtconstant.FIX_PRICE,
            price=float(order.price),
            strategy_name=self.session_id,
            order_remark=(order.signal_reason or "")[:24],
        )
        if int(order_id) <= 0:
            raise RuntimeError(
                f"xtquant rejected the {trade_type} order for {xt_symbol}, "
                f"order_stock returned {order_id}."
            )

        self._sync_from_broker()
        trade = Trade(
            trade_id=self._generate_id("T"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(self._now()),
            symbol=self._strip_market_suffix(xt_symbol),
            trade_type=trade_type,
            price=float(order.price),
            quantity=int(order.volume),
            amount=float(order.price) * int(order.volume),
            commission=0.0,
            slippage=0.0,
            total_cost=float(order.price) * int(order.volume),
            signal_reason=order.signal_reason,
            order_id=str(order_id),
        )
        self.trades.append(trade)
        return trade
