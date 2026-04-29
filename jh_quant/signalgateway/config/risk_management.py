from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RiskManagementParamsConfig(BaseModel):
    """Per-strategy risk management parameters.

    Maps to the backtest module's RiskManagementParams dataclass.
    All fields are optional; unset fields disable the corresponding rule.
    """

    max_holding_days: Optional[int] = Field(
        default=None, ge=1,
        description="Maximum consecutive holding days before forced sale.",
    )
    stop_loss_pct: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Stop-loss threshold as a decimal (e.g. 0.05 = 5%).",
    )
    trailing_stop_pct: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Trailing stop threshold as a decimal.",
    )
    max_consecutive_rising_days: Optional[int] = Field(
        default=None, ge=1,
        description="Max consecutive rising days before forced sale.",
    )
    max_consecutive_falling_days: Optional[int] = Field(
        default=None, ge=1,
        description="Max consecutive falling days before forced sale.",
    )

    def to_backtest_rmp(self):
        """Convert to the backtest module's RiskManagementParams dataclass."""
        from jh_quant.backtest.risk_management import RiskManagementParams

        return RiskManagementParams(**self.model_dump(exclude_none=False))
