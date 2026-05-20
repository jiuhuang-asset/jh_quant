from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BrokerSpec(BaseModel):
    """Broker adapter configuration for live trading sessions."""

    name: str = Field(description="Registered broker name, e.g. 'xtquant'.")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Broker-specific initialization parameters.",
    )
    alias: Optional[str] = Field(
        default=None,
        description="Optional user-facing alias for the broker instance.",
    )


__all__ = ["BrokerSpec"]
