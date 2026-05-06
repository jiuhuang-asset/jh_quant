"""
Persistence module for the trading system.

Provides persistence layer components:
- recorder.py: Order recorder implementations (SQLite, Postgres, Tortoise)
- coordinator.py: PersistenceCoordinator
- protocols.py: Persistence protocols
"""

from .coordinator import PersistenceCoordinator
from .models import TORTOISE_ORM_AVAILABLE, require_tortoise_orm
from .protocols import (
    PerformancePersistence,
    PositionPersistence,
    RuntimeStatePersistence,
    SessionStatePersistence,
    TradePersistence,
    SessionConfigPersistence,
)
from .recorder import (
    MemFireCloudRecorder,
    OrderRecorder,
    PostgresOrderRecorder,
    SQLiteOrderRecorder,
    TortoiseOrderRecorder,
)

__all__ = [
    "PersistenceCoordinator",
    "TORTOISE_ORM_AVAILABLE",
    "PerformancePersistence",
    "PositionPersistence",
    "RuntimeStatePersistence",
    "SessionStatePersistence",
    "TradePersistence",
    "SessionConfigPersistence",
    "OrderRecorder",
    "TortoiseOrderRecorder",
    "SQLiteOrderRecorder",
    "PostgresOrderRecorder",
    "MemFireCloudRecorder",
    "require_tortoise_orm",
]
