from __future__ import annotations

import atexit
import os
import signal
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from threading import Event, RLock, Thread
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from jh_quant.backtest.backtest import (
    evaluate_strategies as backtest_evaluate_strategies,
)

from ..config import (
    ClockMode,
    ExecutionMode,
    PortfolioSpec,
    RiskRuleSpec,
    SELECTION_PROVIDER_REGISTRY,
    STRATEGY_REGISTRY,
    SelectionProvider,
    SelectionSpec,
    SessionServiceConfig,
    StrategySpec,
    build_risk_rules,
    build_selection_provider,
    list_risk_rule_definitions,
    list_selection_definitions,
    list_strategy_definitions,
    normalize_risk_rule_spec,
    normalize_strategy_spec,
)
from ..models import Order
from ..persistence import PersistenceCoordinator
from ..portfolio import (
    build_current_portfolio_snapshot,
    build_portfolio_history,
    list_portfolio_optimizer_definitions,
    PortfolioRuntimeCoordinator,
)
from ..broker import PaperBroker, create_broker
from ..engine import TradingEngine
from ..session import (
    SessionAnalyticsCoordinator,
    SessionCycleCoordinator,
    SessionLifecycleCoordinator,
    SessionRuntimeProfile,
    build_session_runner,
)
from ..utils import rprint
from .schemas import (
    CloseAllPositionsResponse,
    ConfigChangeItem,
    DEFAULT_TRENDS_LIMIT,
    SchedulerConfigSnapshotResponse,
    SchedulerConfigUpdateResponse,
    SchedulerStatus,
    SessionConfigHistoryEntry,
    SessionConfigHistoryResponse,
    SessionConfigResponse,
    SessionConfigUpdateResponse,
    SessionEventHistoryResponse,
    SessionInfoResponse,
    SessionListResponse,
    SessionStatusResponse,
    SessionTrendPoint,
    SessionTrendItem,
    SessionTrendsResponse,
    SingleSymbolTradeResponse,
    TradingCycleResult,
    TradingCycleResultResponse,
)

class SessionService:
    def __init__(
        self,
        gateway: TradingEngine,
        config: SessionServiceConfig,
        selection_provider: Optional[SelectionProvider] = None,
        persistence: Optional[PersistenceCoordinator] = None,
    ):
        self.gateway = gateway
        self.session_config = config
        self.config = config.session
        self.selection_specs = config.selection_spec
        self.strategy_specs = list(config.strategy_specs)
        self.portfolio_spec = config.portfolio_spec
        self.persistence = persistence or PersistenceCoordinator()
        self._latest_portfolio_optimization: Optional[Dict[str, Any]] = None
        self._latest_portfolio_rebalance: Optional[Dict[str, Any]] = None
        self._last_portfolio_rebalance_at: Optional[datetime] = None
        self.selection_provider: Optional[SelectionProvider] = None
        self._config_source = "bootstrap"
        self._persisted_session_config_available = False
        self._persisted_session_config_updated_at: Optional[str] = None
        self._suspend_session_config_persistence = True

        broker_session_id = getattr(self.gateway.broker, "session_id", None)
        if self.config.session_id is None:
            self.config.session_id = broker_session_id or str(uuid.uuid4())
        elif not broker_session_id:
            self.gateway.broker.session_id = self.config.session_id

        self._lock = RLock()
        self._scheduler_stop_event = Event()
        self._scheduler_thread: Optional[Thread] = None
        self._scheduler_running = False
        self._last_result: Optional[TradingCycleResult] = None
        self._last_error: Optional[str] = None
        self._trade_calendar: Optional[set] = None
        self.runtime_profile: Optional[SessionRuntimeProfile] = None
        self.session_runner = None

        self._restore_session_config()
        self._restore_session_state()
        self._initialize_selection_provider(selection_provider)
        self._normalize_live_runtime_constraints()
        self.runtime_profile = SessionRuntimeProfile.from_session(self.config)
        self.session_runner = build_session_runner(self.config)
        self._restore_broker_state()
        if self.strategy_specs:
            self.configure_strategies(self.strategy_specs)
        if config.risk_rule_specs:
            self.configure_risk_rules(list(config.risk_rule_specs))

        self._suspend_session_config_persistence = False
        self._persist_session_config(source="bootstrap")

        if self.session_runner is not None:
            self.session_runner.bootstrap(self)

        if self.config.auto_start:
            self.start_scheduler()

    def _normalize_live_runtime_constraints(self) -> None:
        if self.config.execution_mode == ExecutionMode.LIVE:
            self.config.clock_mode = ClockMode.REALTIME
            self.session_config.session = self.config

    def _runtime_mode_key(self) -> str:
        if self.runtime_profile is not None:
            return self.runtime_profile.key
        return SessionRuntimeProfile.from_session(self.config).key

    def _restore_broker_state(self):
        if self.config.execution_mode != ExecutionMode.PAPER:
            return
        try:
            saved = self.persistence.load_latest_session_state(self.config.session_id)
            if saved:
                self.gateway.broker.import_state(saved)
        except Exception:
            pass

    def _apply_config_bundle(
        self,
        config_bundle: SessionServiceConfig | Dict[str, Any],
        *,
        source: str,
    ) -> None:
        restored_bundle = (
            config_bundle
            if isinstance(config_bundle, SessionServiceConfig)
            else SessionServiceConfig.model_validate(config_bundle)
        )
        restored_session_id = self.config.session_id
        restored_restore_flag = self.config.restore_persisted_state
        restored_auto_start = self.config.auto_start
        restored_execution_mode = self.config.execution_mode
        restored_clock_mode = self.config.clock_mode
        restored_backfill_start = self.config.backfill_start
        self.session_config = restored_bundle
        self.config = self.session_config.session
        self.config.session_id = restored_session_id or self.config.session_id
        self.config.restore_persisted_state = restored_restore_flag
        self.config.auto_start = restored_auto_start
        self.config.execution_mode = restored_execution_mode
        self.config.clock_mode = restored_clock_mode
        self.config.backfill_start = restored_backfill_start
        self.session_config.session = self.config
        self._normalize_live_runtime_constraints()
        self.runtime_profile = SessionRuntimeProfile.from_session(self.config)
        self.session_runner = build_session_runner(self.config)
        self.selection_specs = self.session_config.selection_spec
        self.strategy_specs = list(self.session_config.strategy_specs)
        self.portfolio_spec = self.session_config.portfolio_spec
        self._config_source = source

    def _restore_session_config(self) -> None:
        if not self.config.restore_persisted_state:
            return

        try:
            saved = self.persistence.load_latest_session_config(self.config.session_id)
            if not saved:
                return
            config_bundle = saved.get("config_bundle")
            if not config_bundle:
                return
            self._persisted_session_config_available = True
            self._persisted_session_config_updated_at = saved.get("export_time")
            self._apply_config_bundle(config_bundle, source="persisted_session_config")
        except Exception:
            pass

    def _restore_session_state(self) -> None:
        try:
            saved = self.persistence.load_latest_runtime_state(self.config.session_id)
            if not saved:
                return
            self._apply_session_state(saved)
        except Exception:
            pass

    def _apply_session_state(self, state: Dict[str, Any]) -> None:
        session_state = state.get("session") or {}
        config_bundle = session_state.get("config_bundle")
        if (
            config_bundle
            and self.config.restore_persisted_state
            and not self._persisted_session_config_available
        ):
            self._apply_config_bundle(config_bundle, source="persisted_session_config")
            self._persisted_session_config_available = True
            self._persisted_session_config_updated_at = state.get("export_time")

        last_result = session_state.get("last_result")
        if last_result:
            self._last_result = TradingCycleResult(**last_result)
        self._last_error = None
        self._latest_portfolio_optimization = session_state.get(
            "latest_portfolio_optimization"
        )
        self._latest_portfolio_rebalance = session_state.get(
            "latest_portfolio_rebalance"
        )

        last_rebalance_at = session_state.get("last_portfolio_rebalance_at")
        if last_rebalance_at:
            self._last_portfolio_rebalance_at = datetime.fromisoformat(
                last_rebalance_at
            )

    def _initialize_selection_provider(
        self,
        selection_provider: Optional[SelectionProvider],
    ) -> None:
        if self.selection_specs is not None:
            self.selection_specs, self.selection_provider = build_selection_provider(
                self.selection_specs,
                getattr(self.gateway, "market_data_provider", None),
            )
            self.session_config.selection_spec = self.selection_specs
            return
        if selection_provider is not None:
            self.selection_provider = selection_provider
            self.selection_specs = None
            return
        raise ValueError("Either selection_provider or selection_spec must be provided")

    def _build_strategy_instance(self, spec: StrategySpec) -> dict:
        normalized_spec = normalize_strategy_spec(spec)
        strategy_cls = STRATEGY_REGISTRY[normalized_spec.name]
        strategy = strategy_cls(**normalized_spec.params)
        return {
            "name": normalized_spec.alias or normalized_spec.name,
            "strategy": strategy,
            "weight": normalized_spec.weight,
        }

    def configure_strategies(self, strategy_specs: List[StrategySpec]):
        with self._lock:
            normalized_specs = [
                normalize_strategy_spec(spec) for spec in strategy_specs
            ]
            built = [self._build_strategy_instance(spec) for spec in normalized_specs]
            self.gateway.replace_strategies(built)
            self.strategy_specs = normalized_specs
            self.session_config.strategy_specs = list(normalized_specs)
            self._persist_session_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "strategy_config_updated"})

    def configure_risk_rules(self, risk_rule_specs: List[RiskRuleSpec]):
        """配置风险规则。

        Args:
            risk_rule_specs: 风险规则配置列表
        """
        with self._lock:
            normalized_specs = [
                normalize_risk_rule_spec(spec) for spec in risk_rule_specs
            ]
            rules = build_risk_rules(normalized_specs)
            self.gateway.configure_risk_rules(risk_rules=rules)
            self.session_config.risk_rule_specs = list(normalized_specs)
            self._persist_session_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "risk_rule_config_updated"})

    def _build_selection_instance(self, spec: SelectionSpec) -> SelectionProvider:
        normalized_spec, provider = build_selection_provider(
            spec,
            getattr(self.gateway, "market_data_provider", None),
        )
        self.selection_specs = normalized_spec
        return provider

    def configure_selection(self, selection_spec: SelectionSpec):
        with self._lock:
            provider = self._build_selection_instance(selection_spec)
            self.selection_provider = provider
            self.session_config.selection_spec = self.selection_specs
            self._persist_session_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "selection_config_updated"})

    def configure_portfolio(self, portfolio_spec):
        with self._lock:
            self.portfolio_spec = portfolio_spec
            self.session_config.portfolio_spec = portfolio_spec
            self._persist_session_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "portfolio_config_updated"})

    def _validate_scheduler_inputs(
        self,
        *,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> None:
        self._build_session_lifecycle_coordinator().validate_scheduler_inputs(
            cron_expression=cron_expression,
            timezone=timezone,
        )

    def _build_scheduler_status(self) -> SchedulerStatus:
        return self._build_session_lifecycle_coordinator().build_scheduler_status()

    def update_scheduler_config(
        self,
        *,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
        auto_start: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._validate_scheduler_inputs(
            cron_expression=cron_expression,
            timezone=timezone,
        )

        was_scheduler_running = self._scheduler_running
        if was_scheduler_running:
            self.stop_scheduler()

        with self._lock:
            self.config.cron_expression = cron_expression
            if timezone is not None:
                self.config.timezone = timezone
            if auto_start is not None:
                self.config.auto_start = auto_start
            self._persist_session_config(source="runtime_update")

            self._persist_runtime_state(
                extra={
                    "event": "scheduler_config_updated",
                    "scheduler": {
                        "cron_expression": self.config.cron_expression,
                        "timezone": self.config.timezone,
                        "auto_start": self.config.auto_start,
                    },
                }
            )

        should_start = was_scheduler_running or self.config.auto_start
        if should_start:
            self.start_scheduler()

        return SchedulerConfigUpdateResponse(
            status="updated",
            running=self._scheduler_running,
            scheduler=self._build_scheduler_status(),
            auto_start=self.config.auto_start,
        ).model_dump()

    def replace_session_config(
        self, config_bundle: SessionServiceConfig
    ) -> Dict[str, Any]:
        was_scheduler_running = self._scheduler_running
        if was_scheduler_running:
            self.stop_scheduler()

        with self._lock:
            self._apply_config_bundle(
                config_bundle.model_copy(deep=True), source="runtime_update"
            )
            self._initialize_selection_provider(None)
            if self.strategy_specs:
                normalized_specs = [
                    normalize_strategy_spec(spec) for spec in self.strategy_specs
                ]
                built = [
                    self._build_strategy_instance(spec) for spec in normalized_specs
                ]
                self.gateway.replace_strategies(built)
                self.strategy_specs = normalized_specs
                self.session_config.strategy_specs = list(normalized_specs)
            else:
                self.gateway.replace_strategies([])

            risk_specs = list(self.session_config.risk_rule_specs)
            if risk_specs:
                self.configure_risk_rules(risk_specs)
            else:
                self.gateway.configure_risk_rules(risk_rules=[])

            self._persist_session_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "service_config_replaced"})

        if was_scheduler_running or self.config.auto_start:
            self.start_scheduler()

        return SessionConfigUpdateResponse(
            status="updated",
            session_id=self.config.session_id,
            config_bundle=self.session_config,
        ).model_dump()

    def get_scheduler_config_snapshot(self) -> Dict[str, Any]:
        return SchedulerConfigSnapshotResponse(
            running=self._scheduler_running,
            auto_start=self.config.auto_start,
            scheduler=self._build_scheduler_status(),
        ).model_dump()

    def _get_trade_calendar(self) -> set:
        if self._trade_calendar is not None:
            return self._trade_calendar
        md_provider = getattr(self.gateway, "market_data_provider", None)
        if md_provider is not None and hasattr(md_provider, "get_trade_calendar"):
            self._trade_calendar = md_provider.get_trade_calendar()
        else:
            self._trade_calendar = set()
        return self._trade_calendar

    def _get_jhdata(self):
        md_service = getattr(self.gateway, "market_data_provider", None)
        jhd = getattr(md_service, "jhd", None)
        if jhd is None:
            raise RuntimeError("Current session has no JH-backed market-data service")
        return jhd

    def _as_of_date(self, as_of_date: Optional[str] = None) -> str:
        return as_of_date or datetime.now().strftime("%Y-%m-%d")

    def _price_start_date(self, as_of_date: str) -> str:
        dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        return (dt - timedelta(days=self.config.price_lookback_days)).strftime(
            "%Y-%m-%d"
        )

    def _records_from_frame(self, frame: pd.DataFrame) -> List[Dict[str, Any]]:
        if frame is None or frame.empty:
            return []

        normalized = frame.copy()
        for column in normalized.columns:
            if pd.api.types.is_datetime64_any_dtype(normalized[column]):
                normalized[column] = normalized[column].apply(
                    lambda value: value.isoformat() if pd.notna(value) else None
                )
        records = normalized.to_dict(orient="records")
        for r in records:
            for k, v in r.items():
                if isinstance(v, float) and pd.isna(v):
                    r[k] = None
        return records

    def _normalize_jsonable(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._normalize_jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_jsonable(item) for item in value]
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _apply_slippage(self, price: float, trade_type: str) -> float:
        if self.config.price_slippage <= 0:
            return price
        if trade_type == "BUY":
            return price * (1 + self.config.price_slippage)
        return price * (1 - self.config.price_slippage)

    def _log_execution_branch(self, branch: str, message: str) -> None:
        rprint(label=f"Session:{branch}", content=message)

    def _build_session_analytics_coordinator(self) -> SessionAnalyticsCoordinator:
        return SessionAnalyticsCoordinator(self)

    def _build_session_cycle_coordinator(self) -> SessionCycleCoordinator:
        return SessionCycleCoordinator(self)

    def _build_session_lifecycle_coordinator(self) -> SessionLifecycleCoordinator:
        return SessionLifecycleCoordinator(self)

    def _build_portfolio_runtime(self) -> PortfolioRuntimeCoordinator:
        return PortfolioRuntimeCoordinator(
            gateway=self.gateway,
            selection_provider=self.selection_provider,
            session_config=self.config,
            portfolio_spec=self.portfolio_spec,
            log=self._log_execution_branch,
            strategy_registered=lambda: bool(getattr(self.gateway, "strategy_pool", [])),
            last_rebalance_at=lambda: self._last_portfolio_rebalance_at,
        )

    def _filter_sell_orders_by_executable_holdings(
        self,
        sell_orders: pd.DataFrame,
        latest_prices: pd.Series,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], float]:
        return self._build_portfolio_runtime().filter_sell_orders_by_executable_holdings(
            sell_orders,
            latest_prices,
        )

    def _cap_buy_orders_to_cash_budget(
        self,
        buy_orders: pd.DataFrame,
        latest_prices: pd.Series,
        cash_budget: float,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], float]:
        return self._build_portfolio_runtime().cap_buy_orders_to_cash_budget(
            buy_orders,
            latest_prices,
            cash_budget,
        )

    def _build_portfolio_strategy_context(
        self,
        *,
        cycle_date: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self._build_portfolio_runtime().build_strategy_context(
            cycle_date=cycle_date,
            symbols=symbols,
        )

    def _persist_runtime_state(self, extra: Optional[Dict[str, Any]] = None):
        payload = {
            "session_id": self.config.session_id,
            "export_time": datetime.now().isoformat(),
            "session": {
                "config_bundle": self.session_config.model_dump(mode="json"),
                "config": self.config.model_dump(),
                "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
                "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
                "config_source": self._config_source,
                "persisted_session_config_available": self._persisted_session_config_available,
                "persisted_session_config_updated_at": self._persisted_session_config_updated_at,
                "running": self._scheduler_running,
                "last_error": self._last_error,
                "last_result": asdict(self._last_result) if self._last_result else None,
                "latest_portfolio_optimization": self._latest_portfolio_optimization,
                "latest_portfolio_rebalance": self._latest_portfolio_rebalance,
                "last_portfolio_rebalance_at": (
                    self._last_portfolio_rebalance_at.isoformat()
                    if self._last_portfolio_rebalance_at is not None
                    else None
                ),
            },
        }
        if extra:
            payload["session"]["extra"] = extra
        self.persistence.save_runtime_state(payload)
        if (
            self.config.execution_mode == ExecutionMode.PAPER
            and hasattr(self.gateway.broker, "export_state")
        ):
            self.persistence.save_session_state(self.gateway.broker.export_state())

    def _persist_session_config(self, *, source: str = "runtime_update") -> None:
        if self._suspend_session_config_persistence:
            return
        export_time = datetime.now().isoformat()
        config_bundle = self.session_config.model_dump(mode="json")
        config_bundle["export_time"] = export_time
        self.persistence.save_session_config(
            self.config.session_id,
            config_bundle,
            source=source,
        )
        self._persisted_session_config_available = True
        self._persisted_session_config_updated_at = export_time
        self._config_source = source

    def _persist_trades(self, trades: List[Any]) -> None:
        for trade in trades:
            self.persistence.persist_trade(trade)

    def _serialize_result(
        self, result: Optional[TradingCycleResult]
    ) -> Optional[TradingCycleResultResponse]:
        if result is None:
            return None
        return TradingCycleResultResponse(**asdict(result))

    def get_config_snapshot(self) -> Dict[str, Any]:
        return SessionConfigResponse(
            session_id=self.config.session_id,
            config_bundle=self.session_config.model_dump(mode="json"),
            session=self.config.model_dump(),
            broker_spec=self.session_config.broker_spec,
            selection_spec=(
                self.selection_specs.model_dump()
                if self.selection_specs is not None
                else None
            ),
            selection_provider=self._normalize_jsonable(
                getattr(self.selection_provider, "config", {})
            ),
            strategy_specs=[spec.model_dump() for spec in self.strategy_specs],
            portfolio_spec=self.portfolio_spec.model_dump(mode="json"),
            config_source=self._config_source,
            persisted_session_config_available=self._persisted_session_config_available,
            persisted_session_config_updated_at=self._persisted_session_config_updated_at,
        ).model_dump()

    @staticmethod
    def _diff_configs(
        old: Optional[Dict[str, Any]],
        new: Dict[str, Any],
        *,
        prefix: str = "",
    ) -> List[ConfigChangeItem]:
        if old is None:
            return [
                ConfigChangeItem(
                    field_path=prefix or "(root)",
                    old_value=None,
                    new_value=new,
                    change_type="added",
                )
            ]

        changes: List[ConfigChangeItem] = []
        all_keys = set(old.keys()) | set(new.keys())

        for key in sorted(all_keys):
            field_path = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)

            if key not in old:
                changes.append(
                    ConfigChangeItem(
                        field_path=field_path,
                        old_value=None,
                        new_value=new_val,
                        change_type="added",
                    )
                )
            elif key not in new:
                changes.append(
                    ConfigChangeItem(
                        field_path=field_path,
                        old_value=old_val,
                        new_value=None,
                        change_type="removed",
                    )
                )
            elif isinstance(old_val, dict) and isinstance(new_val, dict):
                changes.extend(
                    SessionService._diff_configs(old_val, new_val, prefix=field_path)
                )
            elif old_val != new_val:
                changes.append(
                    ConfigChangeItem(
                        field_path=field_path,
                        old_value=old_val,
                        new_value=new_val,
                        change_type="modified",
                    )
                )

        return changes

    def get_session_config_history(self) -> Dict[str, Any]:
        records = self.persistence.query_session_configs(self.config.session_id)
        if not records:
            return SessionConfigHistoryResponse(
                session_id=self.config.session_id,
                count=0,
                versions=[],
            ).model_dump()

        versions: List[SessionConfigHistoryEntry] = []
        previous_bundle: Optional[Dict[str, Any]] = None

        for record in records:
            current_bundle = record.get("config_bundle", {})
            current_bundle.pop("export_time", None)

            changes = self._diff_configs(previous_bundle, current_bundle)
            versions.append(
                SessionConfigHistoryEntry(
                    export_time=record.get("export_time", ""),
                    source=record.get("source", "unknown"),
                    config_bundle=current_bundle,
                    changes=changes,
                )
            )
            previous_bundle = current_bundle

        return SessionConfigHistoryResponse(
            session_id=self.config.session_id,
            count=len(versions),
            versions=versions,
        ).model_dump()

    def get_strategy_config_snapshot(self) -> Dict[str, Any]:
        return {
            "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
            "available_strategies": list_strategy_definitions(),
        }

    def get_risk_rule_config_snapshot(self) -> Dict[str, Any]:
        return {
            "risk_rule_specs": [
                spec.model_dump() for spec in self.session_config.risk_rule_specs
            ],
            "available_risk_rules": list_risk_rule_definitions(),
        }

    def get_selection_config_snapshot(self) -> Dict[str, Any]:
        return {
            "selection_spec": (
                self.selection_specs.model_dump()
                if self.selection_specs is not None
                else None
            ),
            "active_selection_config": self._normalize_jsonable(
                getattr(self.selection_provider, "config", {})
            ),
            "available_selections": list_selection_definitions(),
        }

    def get_portfolio_config_snapshot(self) -> Dict[str, Any]:
        return {
            "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
            "available_optimizers": list_portfolio_optimizer_definitions(),
        }

    def optimize_portfolio(
        self,
        *,
        as_of_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        preview_only: bool = True,
    ) -> Dict[str, Any]:
        if not self.portfolio_spec.enabled:
            raise ValueError(
                "Portfolio optimization is disabled in the current portfolio spec"
            )

        cycle_date = self._as_of_date(as_of_date)
        payload = self._build_portfolio_runtime().optimize(
            cycle_date=cycle_date,
            symbols=symbols,
            preview_only=preview_only,
        )
        self._latest_portfolio_optimization = payload
        self._persist_runtime_state(extra={"event": "portfolio_optimized"})
        return payload

    def should_rebalance_portfolio(
        self,
        drift: Dict[str, Any],
        *,
        force: bool = False,
        as_of_time: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        return self._build_portfolio_runtime().should_rebalance(
            drift,
            force=force,
            as_of_time=as_of_time,
        )

    def rebalance_portfolio(
        self,
        *,
        as_of_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        preview_only: bool = True,
        force: bool = False,
    ) -> Dict[str, Any]:
        if not self.portfolio_spec.enabled:
            raise ValueError(
                "Portfolio rebalance is disabled in the current portfolio spec"
            )

        with self._lock:
            cycle_date = self._as_of_date(as_of_date)
            self._log_execution_branch(
                "portfolio",
                (
                    f"Portfolio rebalance started, cycle_date={cycle_date}, "
                    f"force={force}, preview_only={preview_only}"
                ),
            )
            optimization = self.optimize_portfolio(
                as_of_date=cycle_date,
                symbols=symbols,
                preview_only=True,
            )
            payload = self._build_portfolio_runtime().build_rebalance_preview(
                cycle_date=cycle_date,
                optimization_payload=optimization,
                force=force,
            )
            payload["status"] = "preview" if preview_only else "pending"
            payload["preview_only"] = preview_only

            if preview_only or not payload["should_rebalance"]:
                self._latest_portfolio_rebalance = payload
                self._persist_runtime_state(
                    extra={"event": "portfolio_rebalance_preview"}
                )
                return payload

            sell_orders = pd.DataFrame(payload["sell_orders"])
            buy_orders = pd.DataFrame(payload["buy_orders"])
            executed_sells = (
                self.gateway.execute_short(sell_orders, self.config.price_slippage)
                if not sell_orders.empty
                else []
            )
            executed_buys = (
                self.gateway.execute_long(buy_orders, self.config.price_slippage)
                if not buy_orders.empty
                else []
            )
            self._persist_trades(executed_sells)
            self._persist_trades(executed_buys)

            payload["status"] = "rebalanced"
            payload["preview_only"] = False
            payload["executed_buy_count"] = len(executed_buys)
            payload["executed_sell_count"] = len(executed_sells)
            self._latest_portfolio_rebalance = payload
            self._last_portfolio_rebalance_at = datetime.now()
            self._persist_runtime_state(extra={"event": "portfolio_rebalanced"})
            self._log_execution_branch(
                "portfolio",
                (
                    "Portfolio rebalance completed, "
                    f"executed_sells={len(executed_sells)}, "
                    f"executed_buys={len(executed_buys)}"
                ),
            )
            return payload

    def get_portfolio_analysis_snapshot(self) -> Dict[str, Any]:
        runtime = self.get_runtime_state()
        target_weights = None
        if (
            self._latest_portfolio_optimization
            and self._latest_portfolio_optimization.get("weights")
        ):
            target_weights = pd.DataFrame(
                self._latest_portfolio_optimization["weights"]
            )
        current = build_current_portfolio_snapshot(
            runtime["positions"],
            target_weights=target_weights,
        )
        return {
            "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
            "current_portfolio": current,
            "drift": current.get("drift", {}),
            "latest_optimization": self._latest_portfolio_optimization,
            "latest_rebalance": self._latest_portfolio_rebalance,
        }

    def get_portfolio_history(self) -> Dict[str, Any]:
        snapshots = self.persistence.query_position_snapshots(self.config.session_id)
        daily_perf = self.persistence.query_daily_performance(self.config.session_id)
        return build_portfolio_history(snapshots, daily_perf=daily_perf)

    def get_trade_history(
        self, symbol: Optional[str] = None, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        df = self.persistence.query_trades(self.config.session_id)
        if df is None or df.empty:
            return {
                "session_id": self.config.session_id,
                "symbol": symbol,
                "count": 0,
                "trades": [],
            }
        if symbol:
            df = df[df["symbol"] == symbol]
        if limit is not None and limit > 0:
            df = df.tail(limit)
        records = self._records_from_frame(df)
        return {
            "session_id": self.config.session_id,
            "symbol": symbol,
            "count": len(records),
            "trades": records,
        }

    def get_positions(self) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_positions()

    def get_position_history(
        self, symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_position_history(
            symbol=symbol
        )

    def get_session_event_history(self) -> Dict[str, Any]:
        records = self.persistence.query_runtime_events(self.config.session_id)
        events = self._records_from_frame(records)
        return SessionEventHistoryResponse(
            session_id=self.config.session_id,
            count=len(events),
            events=events,
        ).model_dump()

    def _empty_portfolio_cycle_payload(
        self, cycle_date: str, reason: str
    ) -> Dict[str, Any]:
        payload = {
            "status": "skipped",
            "as_of_date": cycle_date,
            "preview_only": False,
            "should_rebalance": False,
            "reason": reason,
            "target_allocations": [],
            "buy_orders": [],
            "sell_orders": [],
            "projected_buy_cost": 0.0,
            "projected_sell_value": 0.0,
            "projected_cash_after": float(
                self.gateway.broker.get_positions().available_balance
            ),
            "drift": {"total_abs_drift": 0.0, "max_abs_drift": 0.0, "rows": []},
            "executed_buy_count": 0,
            "executed_sell_count": 0,
        }
        self._latest_portfolio_rebalance = payload
        return payload

    def get_status(self) -> Dict[str, Any]:
        return SessionStatusResponse(
            session_id=self.config.session_id,
            mode=self._runtime_mode_key(),
            running=self._scheduler_running,
            scheduler=self._build_scheduler_status(),
            last_error=self._last_error,
            last_result=self._serialize_result(self._last_result),
        ).model_dump()

    def _build_current_position_rows(self, positions=None) -> List[Dict[str, Any]]:
        return self._build_session_analytics_coordinator().build_current_position_rows(
            positions
        )

    def _build_current_runtime_bundle(
        self,
        *,
        generated_at: Optional[str] = None,
        positions=None,
    ) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().build_current_runtime_bundle(
            generated_at=generated_at,
            positions=positions,
        )

    def _build_current_portfolio_snapshot(
        self,
        runtime_bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().build_current_portfolio_snapshot(
            runtime_bundle
        )

    def _build_current_position_exposure(
        self,
        runtime_bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().build_current_position_exposure(
            runtime_bundle
        )

    def _build_current_performance_summary(
        self,
        *,
        report: Optional[Dict[str, Any]] = None,
        runtime_bundle: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().build_current_performance_summary(
            report=report,
            runtime_bundle=runtime_bundle,
        )

    def get_runtime_state(self) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_runtime_state()

    def get_performance_snapshot(self) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_performance_snapshot()

    def get_performance_history(self) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_performance_history()

    def get_pnl_source_history(self) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_pnl_source_history()

    def get_analysis_snapshot(self) -> Dict[str, Any]:
        return self._build_session_analytics_coordinator().get_analysis_snapshot()

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        return self.get_runtime_state()

    def run_once(self, as_of_date: Optional[str] = None) -> TradingCycleResult:
        return self.session_runner.run_cycle(self, as_of_date=as_of_date)

    def run_backfill(self) -> TradingCycleResult:
        return self.session_runner.run_backfill(self)

    def _run_scheduler_loop(self):
        return self._build_session_lifecycle_coordinator().run_scheduler_loop()

    def start_scheduler(self):
        return self._build_session_lifecycle_coordinator().start_scheduler()

    def stop_scheduler(self):
        return self._build_session_lifecycle_coordinator().stop_scheduler()

    def shutdown_session(self) -> None:
        return self._build_session_lifecycle_coordinator().shutdown_session()

    def close_all_positions(self, slippage: float = 0.0) -> CloseAllPositionsResponse:
        with self._lock:
            holdings = self.gateway.broker.executable_holds
            if not holdings:
                return CloseAllPositionsResponse(
                    status="no_holdings",
                    closed_count=0,
                    executed_trades=[],
                )

            trades = self.gateway.close_all_positions(slippage=slippage)
            self._persist_trades(trades)

            return CloseAllPositionsResponse(
                status="success",
                closed_count=len(trades),
                executed_trades=[trade.model_dump(mode="json") for trade in trades],
            )

    def signal_buy_symbol(
        self,
        symbol: str,
        target_qty: Optional[int] = None,
        slippage: float = 0.0,
    ) -> SingleSymbolTradeResponse:
        with self._lock:
            latest_prices = self.gateway.get_latest_prices([symbol])
            if latest_prices.empty or symbol not in latest_prices.index:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_buy",
                    symbol=symbol,
                    executed=False,
                    message=f"Unable to get latest price for {symbol}",
                )

            price = latest_prices[symbol]
            exec_price = self._apply_slippage(price, "BUY") if slippage > 0 else price

            if target_qty is None:
                positions = self.gateway.broker.get_positions()
                available_balance = positions.available_balance
                if available_balance <= 0:
                    return SingleSymbolTradeResponse(
                        status="error",
                        action="signal_buy",
                        symbol=symbol,
                        executed=False,
                        message=f"Insufficient available balance: {available_balance}",
                    )
                target_qty = int(available_balance // exec_price)
                if target_qty <= 0:
                    return SingleSymbolTradeResponse(
                        status="error",
                        action="signal_buy",
                        symbol=symbol,
                        executed=False,
                        message=f"Available balance is too low to buy a single share at {exec_price}",
                    )

            try:
                order = Order(
                    symbol=symbol,
                    price=exec_price,
                    volume=target_qty,
                    trade_type="BUY",
                )
                trade = self.gateway.broker.signal_buy(order)
                self._persist_trades([trade])

                return SingleSymbolTradeResponse(
                    status="success",
                    action="signal_buy",
                    symbol=symbol,
                    executed=True,
                    trade=trade.model_dump(mode="json"),
                    message=f"Bought {symbol} {target_qty} shares @ {exec_price:.2f}",
                )
            except Exception as exc:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_buy",
                    symbol=symbol,
                    executed=False,
                    message=f"Buy failed: {exc}",
                )

    def signal_sell_symbol(
        self,
        symbol: str,
        target_qty: Optional[int] = None,
        slippage: float = 0.0,
    ) -> SingleSymbolTradeResponse:
        with self._lock:
            positions = self.gateway.broker.get_positions()
            holdings_map = {h.symbol: h for h in positions.holds}

            if symbol not in holdings_map:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_sell",
                    symbol=symbol,
                    executed=False,
                    message=f"No holdings found for {symbol}",
                )

            holding = holdings_map[symbol]
            latest_prices = self.gateway.get_latest_prices([symbol])
            if latest_prices.empty or symbol not in latest_prices.index:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_sell",
                    symbol=symbol,
                    executed=False,
                    message=f"Unable to get latest price for {symbol}",
                )

            price = latest_prices[symbol]
            exec_price = self._apply_slippage(price, "SELL") if slippage > 0 else price

            sell_qty = target_qty if target_qty else holding.volume
            if sell_qty > holding.volume:
                sell_qty = holding.volume

            try:
                order = Order(
                    symbol=symbol,
                    price=exec_price,
                    volume=sell_qty,
                    trade_type="SELL",
                )
                trade = self.gateway.broker.signal_sell(order)
                self._persist_trades([trade])

                pnl = (exec_price - holding.avg_cost) * sell_qty
                pnl_pct = (
                    (pnl / (holding.avg_cost * sell_qty) * 100)
                    if holding.avg_cost > 0
                    else 0
                )

                return SingleSymbolTradeResponse(
                    status="success",
                    action="signal_sell",
                    symbol=symbol,
                    executed=True,
                    trade=trade.model_dump(mode="json"),
                    message=f"Sold {symbol} {sell_qty} shares @ {exec_price:.2f}, PnL: {pnl:.2f} ({pnl_pct:.2f}%)",
                )
            except Exception as exc:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_sell",
                    symbol=symbol,
                    executed=False,
                    message=f"Sell failed: {exc}",
                )


class MultiSessionService:
    """Manages multiple SessionService instances in a single process.

    Each service gets its own broker instance (isolated by session_id) and scheduler
    thread, while sharing a common PersistenceCoordinator and
    MarketDataService.

    Registers ``atexit`` and ``SIGINT``/``SIGTERM`` handlers so that all
    scheduler threads are stopped and persistence connections are closed
    when the process receives an interrupt signal.
    """

    _signal_registered = False
    _instances: "list[MultiSessionService]" = []

    def __init__(
        self,
        max_sessions: int = 4,
        persistence: Optional[PersistenceCoordinator] = None,
        market_data_provider=None,
    ):
        self._max_sessions = max(max_sessions, 1)
        self._shared_persistence = persistence or PersistenceCoordinator()
        self._shared_md_provider = market_data_provider
        self._sessions: Dict[str, SessionService] = {}
        self._lock = RLock()
        self._shutting_down = False

        self.__class__._instances.append(self)
        MultiSessionService._register_global_shutdown()

    def __del__(self) -> None:
        try:
            self.__class__._instances.remove(self)
        except (ValueError, AttributeError):
            pass

    # ── service lifecycle ──────────────────────────────────────

    def _build_broker(
        self,
        *,
        config: SessionServiceConfig,
        session_id: str,
        initial_capital: float,
    ):
        if config.session.execution_mode == ExecutionMode.PAPER:
            return PaperBroker(session_id=session_id, initial_capital=initial_capital)

        if config.broker_spec is None:
            raise ValueError("live mode requires an explicit broker_spec")

        return create_broker(config.broker_spec, session_id=session_id)

    def create_session(
        self,
        config: SessionServiceConfig,
        initial_capital: float = 100000,
    ) -> str:
        """Create and register a new service from config.

        Returns the session_id of the created service.
        """
        with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise ValueError(
                    f"Maximum number of sessions reached ({self._max_sessions}). "
                    f"Remove an existing session before creating a new one."
                )

            session_id = config.session.session_id or str(uuid.uuid4())
            if session_id in self._sessions:
                raise ValueError(
                    f"Session with session_id '{session_id}' already exists."
                )

            config.session.session_id = session_id
            broker = self._build_broker(
                config=config,
                session_id=session_id,
                initial_capital=initial_capital,
            )
            gateway = TradingEngine(
                broker=broker,
                market_data_provider=self._shared_md_provider,
            )
            service = SessionService(
                gateway=gateway,
                config=config,
                persistence=self._shared_persistence,
            )
            self._sessions[session_id] = service
            return session_id

    def wrap_session(self, service: SessionService) -> str:
        """Register an already-constructed service instance.

        Returns the service's session_id.
        """
        session_id = service.config.session_id
        if not session_id:
            raise ValueError("Session must have a non-empty session_id")
        with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise ValueError(
                    f"Maximum number of sessions reached ({self._max_sessions}). "
                    f"Remove an existing session before creating a new one."
                )
            if session_id in self._sessions:
                raise ValueError(
                    f"Session with session_id '{session_id}' already exists."
                )
            self._sessions[session_id] = service
        return session_id

    def remove_session(self, session_id: str) -> None:
        """Shutdown and remove a service by session_id."""
        with self._lock:
            service = self._sessions.pop(session_id, None)
        if service is not None:
            service.shutdown_session()

    def get_session(self, session_id: str) -> SessionService:
        """Get a service by session_id.

        Raises KeyError if not found.
        """
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session with session_id '{session_id}' not found")
            return self._sessions[session_id]

    def stop_all(self) -> None:
        """Shutdown all managed services, then close shared persistence."""
        self.shutdown()

    def shutdown(self) -> None:
        """Gracefully stop all scheduler threads and close persistence.

        Idempotent — safe to call multiple times.
        """
        if self._shutting_down:
            return
        self._shutting_down = True

        with self._lock:
            services = list(self._sessions.values())
            self._sessions.clear()

        for service in services:
            try:
                service.shutdown_session()
            except Exception:
                pass

        close = getattr(self._shared_persistence, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    @classmethod
    def _shutdown_all_instances(cls) -> None:
        """Call ``shutdown()`` on every registered instance."""
        for instance in list(cls._instances):
            try:
                instance.shutdown()
            except Exception:
                pass

    @classmethod
    def _register_global_shutdown(cls) -> None:
        """Register atexit and signal handlers once per process."""
        if cls._signal_registered:
            return
        cls._signal_registered = True

        atexit.register(cls._shutdown_all_instances)

        def _signal_handler(signum: int, frame: Any) -> None:
            cls._shutdown_all_instances()
            raise KeyboardInterrupt

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _signal_handler)
            except ValueError:
                pass

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    # ── data access ────────────────────────────────────────────

    def _resolve_jhdata(self):
        """Resolve JHData from the shared market-data service or first session."""
        if self._shared_md_provider is not None and hasattr(
            self._shared_md_provider, "jhd"
        ):
            return self._shared_md_provider.jhd

        with self._lock:
            for svc in self._sessions.values():
                try:
                    return svc._get_jhdata()
                except Exception:
                    continue
        raise RuntimeError("No JH-backed market-data service available in any managed session")

    # ── query ──────────────────────────────────────────────────

    def list_sessions(self) -> SessionListResponse:
        """Return metadata for all managed services."""
        items: list[SessionInfoResponse] = []
        with self._lock:
            for session_id, svc in self._sessions.items():
                items.append(self._build_session_info(session_id, svc))
        return SessionListResponse(
            sessions=items,
            count=len(items),
            max_sessions=self._max_sessions,
        )

    def get_session_trends(
        self,
        session_ids: Optional[List[str]] = None,
        limit: int = DEFAULT_TRENDS_LIMIT,
        days: Optional[int] = None,
    ) -> SessionTrendsResponse:
        """Return time-series trend data for multiple sessions.

        Args:
            session_ids: Specific sessions to return. If None, returns the
                latest sessions up to *limit*.
            limit: Max sessions when session_ids is not specified.
            days: If set, return only the most recent N calendar days of trends.
        """
        with self._lock:
            all_ids = list(self._sessions.keys())
            if session_ids is not None:
                target_ids = [sid for sid in session_ids if sid in self._sessions]
            elif len(all_ids) > limit:
                target_ids = all_ids[-limit:]
            else:
                target_ids = list(all_ids)

        items: list[SessionTrendItem] = []
        note: Optional[str] = None
        if session_ids is None and len(all_ids) > limit:
            note = (
                f"Showing latest {len(target_ids)} of {len(all_ids)} sessions. "
                f"Use ?session_ids=... to select specific sessions."
            )

        for sid in target_ids:
            with self._lock:
                svc = self._sessions.get(sid)
            if svc is None:
                continue
            items.append(self._build_session_trend_item(sid, svc, days=days))

        return SessionTrendsResponse(
            generated_at=datetime.now().isoformat(),
            count=len(items),
            sessions=items,
            note=note,
        )

    def _build_session_trend_item(
        self,
        session_id: str,
        svc: SessionService,
        days: Optional[int] = None,
    ) -> SessionTrendItem:
        selection_name = getattr(svc.selection_specs, "alias", None) or getattr(
            svc.selection_specs, "name", None
        )
        initial_capital = float(getattr(svc.gateway.broker, "initial_capital", 0.0))

        report = self._shared_persistence.get_performance_report(session_id)
        equity_curve = report.get("equity_curve")

        trend_points: list[SessionTrendPoint] = []
        if equity_curve is not None and not equity_curve.empty:
            curve = equity_curve.copy()
            if days is not None and days > 0:
                curve = curve.tail(days)
            for _, row in curve.iterrows():
                trend_points.append(
                    SessionTrendPoint(
                        trade_date=str(row.get("trade_date", "")),
                        portfolio_value=float(row.get("portfolio_value", 0.0)),
                        total_return=(
                            float(row["total_return"])
                            if row.get("total_return") is not None
                            and not pd.isna(row["total_return"])
                            else None
                        ),
                        drawdown=float(row.get("drawdown", 0.0)),
                        daily_pnl=(
                            float(row["daily_pnl"])
                            if row.get("daily_pnl") is not None
                            and not pd.isna(row["daily_pnl"])
                            else None
                        ),
                        num_positions=int(row.get("num_positions", 0)),
                    )
                )

        return SessionTrendItem(
            session_id=session_id,
            mode=svc._runtime_mode_key(),
            initial_capital=initial_capital,
            strategy_names=[spec.alias or spec.name for spec in svc.strategy_specs],
            selection_name=str(selection_name) if selection_name else None,
            trends=trend_points,
        )

    # ── helpers ────────────────────────────────────────────────

    def _build_session_info(
        self, session_id: str, svc: SessionService
    ) -> SessionInfoResponse:
        positions = svc.gateway.broker.get_positions()
        current_value = float(positions.total) if positions else None
        selection_name = getattr(svc.selection_specs, "alias", None) or getattr(
            svc.selection_specs, "name", None
        )
        portfolio_enabled = bool(getattr(svc.portfolio_spec, "enabled", False))

        # Read from persisted daily_performance — the broker daily_profit is
        # reset to zero after every compute_daily_metrics call, so the live
        # attribute is unusable as a public-facing "daily PnL" value.
        daily_pnl = None
        if self._shared_persistence is not None:
            daily_perf_df = self._shared_persistence.query_daily_performance(session_id)
            if not daily_perf_df.empty:
                latest = daily_perf_df.sort_values("trade_date").iloc[-1]
                raw = latest.get("daily_pnl")
                if raw is not None and not pd.isna(raw):
                    daily_pnl = float(raw)
        position_count = len(getattr(positions, "holds", []))
        strategy_names = [spec.alias or spec.name for spec in svc.strategy_specs]

        report = self._shared_persistence.get_performance_report(session_id)
        runtime_bundle = svc._build_current_runtime_bundle(positions=positions)
        summary = svc._build_current_performance_summary(
            report=report,
            runtime_bundle=runtime_bundle,
        )
        initial_capital = float(summary.get("initial_capital", 0.0))
        total_return = summary.get("total_return")
        max_drawdown = float(summary.get("max_drawdown", 0.0))
        win_rate = summary.get("win_rate")
        total_trades = int(summary.get("total_trades", 0))
        total_pnl = float(summary.get("total_pnl", 0.0))

        return SessionInfoResponse(
            session_id=session_id,
            mode=svc._runtime_mode_key(),
            running=svc._scheduler_running,
            strategy_count=len(svc.strategy_specs),
            strategy_names=strategy_names,
            selection_name=str(selection_name) if selection_name else None,
            portfolio_enabled=portfolio_enabled,
            initial_capital=initial_capital,
            current_value=current_value,
            total_return=total_return,
            daily_pnl=daily_pnl,
            position_count=position_count,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=total_trades,
            total_pnl=total_pnl,
            last_error=svc._last_error,
            last_result=svc._serialize_result(svc._last_result),
            created_at=(
                self._shared_persistence.load_earliest_session_config(session_id) or {}
            ).get("created_at"),
        )
