"""
Database models using Tortoise ORM for trading persistence.
"""

from __future__ import annotations

try:
    from tortoise import fields
    from tortoise.models import Model as TortoiseModel

    TORTOISE_ORM_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency at runtime
    TortoiseModel = object
    fields = None
    TORTOISE_ORM_AVAILABLE = False


def require_tortoise_orm() -> None:
    if not TORTOISE_ORM_AVAILABLE:
        raise ImportError(
            "tortoise-orm is required to use trading persistence recorders"
        )


if TORTOISE_ORM_AVAILABLE:

    class TradeRecord(TortoiseModel):
        trade_id = fields.CharField(max_length=128, primary_key=True)
        session_id = fields.CharField(max_length=128, db_index=True)
        trade_date = fields.DatetimeField()
        symbol = fields.CharField(max_length=32)
        trade_type = fields.CharField(max_length=16)
        price = fields.FloatField()
        quantity = fields.IntField()
        amount = fields.FloatField()
        commission = fields.FloatField(default=0.0)
        slippage = fields.FloatField(default=0.0)
        total_cost = fields.FloatField()
        signal_reason = fields.TextField(null=True)
        order_id = fields.CharField(max_length=128, null=True)
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "trades"
            ordering = ["trade_date"]
            indexes = [("session_id", "trade_date")]

    class DailyPerformanceRecord(TortoiseModel):
        performance_id = fields.CharField(max_length=128, primary_key=True)
        session_id = fields.CharField(max_length=128, db_index=True)
        trade_date = fields.DateField()
        portfolio_value = fields.FloatField()
        cash_balance = fields.FloatField()
        position_value = fields.FloatField()
        daily_return = fields.FloatField(null=True)
        cumulative_return = fields.FloatField(null=True)
        daily_pnl = fields.FloatField(null=True)
        num_positions = fields.IntField(default=0)
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "daily_performances"
            ordering = ["trade_date"]
            unique_together = (("session_id", "trade_date"),)
            indexes = [("session_id", "trade_date")]

    class PositionSnapshotRecord(TortoiseModel):
        snapshot_id = fields.CharField(max_length=128, primary_key=True)
        session_id = fields.CharField(max_length=128, db_index=True)
        trade_date = fields.DatetimeField()
        symbol = fields.CharField(max_length=32)
        quantity = fields.IntField()
        avg_cost = fields.FloatField()
        current_price = fields.FloatField()
        market_value = fields.FloatField()
        pnl = fields.FloatField(null=True)
        pnl_pct = fields.FloatField(null=True)
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "positions_snapshot"
            ordering = ["trade_date"]
            indexes = [("session_id", "trade_date")]

    class SessionStateRecord(TortoiseModel):
        id = fields.IntField(primary_key=True)
        session_id = fields.CharField(max_length=128, db_index=True)
        state_data = fields.JSONField()
        export_time = fields.DatetimeField()
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "session_states"
            ordering = ["-export_time"]
            unique_together = (("session_id", "export_time"),)
            indexes = [("session_id", "export_time")]

    class RuntimeStateRecord(TortoiseModel):
        session_id = fields.CharField(max_length=128, primary_key=True)
        state_data = fields.JSONField()
        export_time = fields.DatetimeField()
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "session_runtime_states"
            indexes = [("session_id", "export_time")]

    class SessionConfigRecord(TortoiseModel):
        id = fields.IntField(primary_key=True)
        session_id = fields.CharField(max_length=128, db_index=True)
        config_md5 = fields.CharField(max_length=32)
        config_bundle = fields.JSONField()
        source = fields.CharField(max_length=64, default="runtime_update")
        export_time = fields.DatetimeField()
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "session_config_records"
            unique_together = (("session_id", "config_md5"),)
            indexes = [("session_id", "export_time"), ("session_id", "source")]

    class RuntimeEventRecord(TortoiseModel):
        id = fields.IntField(primary_key=True)
        session_id = fields.CharField(max_length=128, db_index=True)
        event_type = fields.CharField(max_length=128, db_index=True)
        state_data = fields.JSONField()
        event_time = fields.DatetimeField()
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "session_runtime_events"
            ordering = ["event_time"]
            indexes = [("session_id", "event_time"), ("session_id", "event_type")]

else:

    class TradeRecord:  # pragma: no cover - import fallback
        pass

    class DailyPerformanceRecord:  # pragma: no cover - import fallback
        pass

    class PositionSnapshotRecord:  # pragma: no cover - import fallback
        pass

    class SessionStateRecord:  # pragma: no cover - import fallback
        pass

    class RuntimeStateRecord:  # pragma: no cover - import fallback
        pass

    class SessionConfigRecord:  # pragma: no cover - import fallback
        pass

    class RuntimeEventRecord:  # pragma: no cover - import fallback
        pass


__all__ = [
    "TORTOISE_ORM_AVAILABLE",
    "DailyPerformanceRecord",
    "PositionSnapshotRecord",
    "RuntimeStateRecord",
    "SessionConfigRecord",
    "RuntimeEventRecord",
    "SessionStateRecord",
    "TradeRecord",
    "require_tortoise_orm",
]
