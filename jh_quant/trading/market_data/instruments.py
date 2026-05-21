from __future__ import annotations

from typing import Dict, List

from .models import InstrumentMeta


class AkShareInstrumentProvider:
    def infer_exchange(self, symbol: str) -> str:
        symbol = str(symbol)
        if symbol.startswith(("5", "6", "9")):
            return "SH"
        if symbol.startswith(("0", "1", "2", "3")):
            return "SZ"
        if symbol.startswith(("4", "8")):
            return "BJ"
        return "UNKNOWN"

    def infer_security_type(self, symbol: str) -> str:
        symbol = str(symbol)
        if symbol.startswith(("51", "56", "58", "15", "16")):
            return "fund"
        if symbol.startswith(("11", "12")):
            return "bond"
        return "stock"

    def infer_lot_size(self, symbol: str) -> int:
        return 100

    def infer_price_tick(self, symbol: str) -> float:
        return 0.01

    def get_instruments(self, symbols: List[str]) -> Dict[str, InstrumentMeta]:
        result: Dict[str, InstrumentMeta] = {}
        for symbol in symbols:
            result[symbol] = InstrumentMeta(
                symbol=symbol,
                exchange=self.infer_exchange(symbol),
                lot_size=self.infer_lot_size(symbol),
                price_tick=self.infer_price_tick(symbol),
                security_type=self.infer_security_type(symbol),
                is_t0=False,
                allow_short=False,
            )
        return result

    def normalize_order_volume(self, symbol: str, volume: int) -> int:
        lot_size = self.infer_lot_size(symbol)
        return max(0, int(volume) // lot_size * lot_size)


__all__ = ["AkShareInstrumentProvider"]
