from __future__ import annotations

from dataclasses import dataclass

from ..config import ClockMode, ExecutionMode, SessionConfig


@dataclass(frozen=True)
class SessionRuntimeProfile:
    execution_mode: ExecutionMode
    clock_mode: ClockMode

    @property
    def key(self) -> str:
        return f"{self.execution_mode.value}+{self.clock_mode.value}"

    @property
    def is_paper(self) -> bool:
        return self.execution_mode == ExecutionMode.PAPER

    @property
    def is_live(self) -> bool:
        return self.execution_mode == ExecutionMode.LIVE

    @property
    def is_backfill(self) -> bool:
        return self.clock_mode == ClockMode.BACKFILL

    @classmethod
    def from_session(cls, session: SessionConfig) -> "SessionRuntimeProfile":
        return cls(
            execution_mode=session.execution_mode,
            clock_mode=session.clock_mode,
        )
