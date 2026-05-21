from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import ClockMode, ExecutionMode, SessionConfig
from .models import SessionRuntimeProfile

if TYPE_CHECKING:
    from ..service.core import SessionService


@dataclass
class SessionRunner:
    profile: SessionRuntimeProfile

    def bootstrap(self, service: "SessionService") -> None:
        raise NotImplementedError

    def run_cycle(
        self,
        service: "SessionService",
        *,
        as_of_date: str | None = None,
    ):
        return service._build_session_cycle_coordinator().run_cycle(
            as_of_date=as_of_date
        )

    def run_backfill(self, service: "SessionService"):
        return service._build_session_cycle_coordinator().run_backfill()


class PaperRealtimeRunner(SessionRunner):
    def bootstrap(self, service: "SessionService") -> None:
        service._log_execution_branch("session", "paper+realtime started")


class PaperBackfillRunner(SessionRunner):
    def bootstrap(self, service: "SessionService") -> None:
        service._log_execution_branch("session", "paper+backfill started")
        self.run_backfill(service)


class LiveRealtimeRunner(SessionRunner):
    def bootstrap(self, service: "SessionService") -> None:
        service._log_execution_branch("session", "live+realtime started")


def build_session_runner(config: SessionConfig) -> SessionRunner:
    profile = SessionRuntimeProfile.from_session(config)
    mapping = {
        (ExecutionMode.PAPER, ClockMode.REALTIME): PaperRealtimeRunner,
        (ExecutionMode.PAPER, ClockMode.BACKFILL): PaperBackfillRunner,
        (ExecutionMode.LIVE, ClockMode.REALTIME): LiveRealtimeRunner,
    }
    runner_cls = mapping.get((profile.execution_mode, profile.clock_mode))
    if runner_cls is None:
        raise ValueError(f"Unsupported session runtime profile: {profile.key}")
    return runner_cls(profile=profile)
