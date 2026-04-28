"""
PersistenceCoordinator - bridges OMS runtime data to persistence layer.

Acts as a facade implementing all five persistence protocols,
delegating to an underlying OrderRecorder (or doing nothing if None).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from ..performance import build_performance_report

if TYPE_CHECKING:
    import pandas as pd

    from ..models import DailyPerformance, PositionSnapshot, Trade
    from .recorder import OrderRecorder
    from .protocols import (
        PerformancePersistence,
        PositionPersistence,
        ServiceStatePersistence,
        SessionStatePersistence,
        TradePersistence,
    )


class PersistenceCoordinator:
    """
    Coordinates persistence of OMS and service runtime data.

    Implements all five persistence protocols, delegating to an
    underlying OrderRecorder. If no recorder is configured, all
    operations are no-ops (graceful degradation).
    """

    def __init__(self, recorder: Optional["OrderRecorder"] = None):
        self.recorder = recorder

    def has_persistence(self) -> bool:
        return self.recorder is not None

    # --- TradePersistence ---

    def save_trade(self, trade: "Trade") -> None:
        if self.recorder is None:
            return
        self.recorder.save_trade(trade)

    def query_trades(self, session_id: str) -> "pd.DataFrame":
        import pandas as pd

        if self.recorder is None:
            return pd.DataFrame()
        return self.recorder.query_trades(session_id)

    # --- PerformancePersistence ---

    def save_daily_snapshot(self, perf: "DailyPerformance") -> None:
        if self.recorder is None:
            return
        self.recorder.save_daily_snapshot(perf)

    def query_daily_performance(self, session_id: str) -> "pd.DataFrame":
        import pandas as pd

        if self.recorder is None:
            return pd.DataFrame()
        return self.recorder.query_daily_performance(session_id)

    # --- PositionPersistence ---

    def save_position_snapshot(self, snapshot: "PositionSnapshot") -> None:
        if self.recorder is None:
            return
        self.recorder.save_position_snapshot(snapshot)

    def query_position_snapshots(self, session_id: str) -> "pd.DataFrame":
        import pandas as pd

        if self.recorder is None:
            return pd.DataFrame()
        return self.recorder.query_position_snapshots(session_id)

    # --- SessionStatePersistence ---

    def save_session_state(self, state: dict) -> None:
        if self.recorder is None:
            return
        self.recorder.save_session_state(state)

    def load_latest_session_state(self, session_id: str) -> Optional[dict]:
        if self.recorder is None:
            return None
        return self.recorder.load_latest_session_state(session_id)

    # --- ServiceStatePersistence ---

    def save_service_state(self, state: dict) -> None:
        if self.recorder is None:
            return
        self.recorder.save_service_state(state)

    def load_latest_service_state(self, session_id: str) -> Optional[dict]:
        if self.recorder is None:
            return None
        return self.recorder.load_latest_service_state(session_id)

    def save_user_config(
        self,
        session_id: str,
        config_bundle: dict,
        *,
        source: str = "runtime_update",
    ) -> None:
        if self.recorder is None:
            return
        self.recorder.save_user_config(session_id, config_bundle, source=source)

    def load_latest_user_config(self, session_id: str) -> Optional[dict]:
        if self.recorder is None:
            return None
        return self.recorder.load_latest_user_config(session_id)

    def query_service_events(self, session_id: str) -> "pd.DataFrame":
        import pandas as pd

        if self.recorder is None:
            return pd.DataFrame()
        return self.recorder.query_service_events(session_id)

    # --- Convenience ---

    def persist_daily_metrics(
        self,
        perf: "DailyPerformance",
        snapshots: List["PositionSnapshot"],
    ) -> None:
        """
        Persist a daily performance record and all its position snapshots.

        Args:
            perf: DailyPerformance record
            snapshots: List of PositionSnapshot records for the same day
        """
        self.save_daily_snapshot(perf)
        for snap in snapshots:
            self.save_position_snapshot(snap)

    def persist_trade(self, trade: "Trade") -> None:
        """Alias for save_trade for API clarity."""
        self.save_trade(trade)

    def get_performance_report(self, session_id: str) -> dict[str, Any]:
        import pandas as pd

        if self.recorder is None:
            return {
                "summary": {},
                "holding_returns": pd.DataFrame(),
                "turnover": pd.DataFrame(),
                "equity_curve": pd.DataFrame(),
                "trade_activity": pd.DataFrame(),
                "position_exposure": {},
                "latest_portfolio": {},
            }
        return build_performance_report(self, session_id)

    def close(self) -> None:
        if self.recorder is None:
            return
        close = getattr(self.recorder, "close", None)
        if callable(close):
            close()
