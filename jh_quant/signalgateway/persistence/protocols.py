"""
Persistence protocol definitions for signalgateway components.

These protocols define the contract for persistence operations.
Components that need persistence should declare dependencies on these
Protocols rather than concretely depending on OrderRecorder.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd


@runtime_checkable
class TradePersistence(Protocol):
    """Protocol for trade record persistence."""

    def save_trade(self, trade) -> None:
        """Save a single trade record."""
        ...

    def query_trades(self, session_id: str) -> "pd.DataFrame":
        """Query all trades for a session."""
        ...


@runtime_checkable
class PerformancePersistence(Protocol):
    """Protocol for daily performance snapshot persistence."""

    def save_daily_snapshot(self, perf) -> None:
        """Save or upsert a daily performance record."""
        ...

    def query_daily_performance(self, session_id: str) -> "pd.DataFrame":
        """Query all daily performance records for a session."""
        ...


@runtime_checkable
class PositionPersistence(Protocol):
    """Protocol for position snapshot persistence."""

    def save_position_snapshot(self, snapshot) -> None:
        """Save a position snapshot record."""
        ...

    def query_position_snapshots(self, session_id: str) -> "pd.DataFrame":
        """Query all position snapshots for a session."""
        ...


@runtime_checkable
class SessionStatePersistence(Protocol):
    """Protocol for OMS session state persistence."""

    def save_session_state(self, state: dict) -> None:
        """Save a session state snapshot."""
        ...

    def load_latest_session_state(self, session_id: str) -> dict | None:
        """Load the most recent session state for a given session_id."""
        ...


@runtime_checkable
class ServiceStatePersistence(Protocol):
    """Protocol for service runtime state persistence."""

    def save_service_state(self, state: dict) -> None:
        """Save service runtime state."""
        ...

    def load_latest_service_state(self, session_id: str) -> dict | None:
        """Load the most recent service state for a given session_id."""
        ...

    def query_service_events(self, session_id: str) -> "pd.DataFrame":
        """Query service runtime event history for a session."""
        ...


@runtime_checkable
class UserConfigPersistence(Protocol):
    """Protocol for user-managed config bundle persistence."""

    def save_user_config(
        self,
        session_id: str,
        config_bundle: dict,
        *,
        source: str = "runtime_update",
    ) -> None:
        """Save the latest user-managed config bundle for a session."""
        ...

    def load_latest_user_config(self, session_id: str) -> dict | None:
        """Load the latest user-managed config bundle for a given session_id."""
        ...
