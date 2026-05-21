from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from .models import MarketStatus, TradingPhase


class AkShareMarketStatusProvider:
    def get_market_status(self, now: Optional[datetime] = None) -> MarketStatus:
        now = now or datetime.now()
        current_time = now.time()
        phase = self._resolve_phase(current_time)
        return MarketStatus(
            trading_day=now.strftime("%Y-%m-%d"),
            is_open=phase in (TradingPhase.CALL_AUCTION.value, TradingPhase.CONTINUOUS.value),
            phase=phase,
            timestamp=now,
        )

    def _resolve_phase(self, current_time: time) -> str:
        if current_time < time(9, 15):
            return TradingPhase.PRE_OPEN.value
        if current_time < time(9, 30):
            return TradingPhase.CALL_AUCTION.value
        if current_time <= time(11, 30):
            return TradingPhase.CONTINUOUS.value
        if current_time < time(13, 0):
            return TradingPhase.LUNCH_BREAK.value
        if current_time <= time(15, 0):
            return TradingPhase.CONTINUOUS.value
        if current_time <= time(15, 30):
            return TradingPhase.AFTER_HOURS.value
        return TradingPhase.CLOSED.value


__all__ = ["AkShareMarketStatusProvider"]
