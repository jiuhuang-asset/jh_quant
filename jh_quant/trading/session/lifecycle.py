from __future__ import annotations

import traceback
from datetime import datetime
from threading import Thread
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from ..service.schemas import SchedulerStatus, TradingCycleResult

if TYPE_CHECKING:
    from ..service.core import SessionService


class CronScheduler:
    """Simple cron-based scheduler backed by croniter."""

    def __init__(self, cron_expression: str, timezone: str = "Asia/Shanghai"):
        from croniter import croniter

        self.cron_expr = cron_expression
        self.timezone = timezone
        self._tzinfo = ZoneInfo(timezone)
        self._iter = croniter(cron_expression, datetime.now(self._tzinfo))

    def get_next_timeout(self) -> float:
        next_tick = self._iter.get_next(datetime)
        return max(0.0, (next_tick - datetime.now(self._tzinfo)).total_seconds())

    def peek_next_ticks(self, count: int = 3) -> list[datetime]:
        from croniter import croniter

        preview_iter = croniter(self.cron_expr, datetime.now(self._tzinfo))
        return [preview_iter.get_next(datetime) for _ in range(max(0, count))]

    def wait(self, stop_event) -> bool:
        timeout = self.get_next_timeout()
        return not stop_event.wait(timeout=timeout)


class SessionLifecycleCoordinator:
    """Owns scheduler state transitions and lifecycle operations for a session."""

    def __init__(self, service: "SessionService"):
        self.service = service

    def validate_scheduler_inputs(
        self,
        *,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> None:
        if timezone is not None:
            ZoneInfo(timezone)

        if cron_expression:
            from croniter import croniter

            tzinfo = ZoneInfo(timezone or self.service.config.timezone)
            croniter(cron_expression, datetime.now(tzinfo))

    def build_scheduler_status(self) -> SchedulerStatus:
        schedule_type = "cron" if self.service.config.cron_expression else "none"
        next_run_at: Optional[str] = None
        next_run_in_seconds: Optional[float] = None
        next_runs: list[str] = []

        if self.service.config.cron_expression:
            try:
                scheduler = CronScheduler(
                    cron_expression=self.service.config.cron_expression,
                    timezone=self.service.config.timezone,
                )
                next_ticks = scheduler.peek_next_ticks(count=3)
                next_tick = next_ticks[0] if next_ticks else None
                next_runs = [tick.isoformat() for tick in next_ticks]
                if next_tick is None:
                    raise ValueError("cron preview returned no next tick")
                next_run_at = next_tick.isoformat()
                next_run_in_seconds = round(
                    max(
                        0.0,
                        (
                            next_tick
                            - datetime.now(ZoneInfo(self.service.config.timezone))
                        ).total_seconds(),
                    ),
                    2,
                )
            except Exception:
                next_run_at = None
                next_run_in_seconds = None
                next_runs = []

        return SchedulerStatus(
            cron_expression=self.service.config.cron_expression,
            timezone=self.service.config.timezone,
            schedule_type=schedule_type,
            next_run_at=next_run_at,
            next_run_in_seconds=next_run_in_seconds,
            next_runs=next_runs,
        )

    def run_scheduler_loop(self) -> None:
        if not self.service.config.cron_expression:
            self.service._log_execution_branch(
                "scheduler",
                "cron_expression is not configured; scheduler loop will exit",
            )
            self.service._scheduler_running = False
            return

        scheduler = CronScheduler(
            self.service.config.cron_expression,
            self.service.config.timezone,
        )

        while not self.service._scheduler_stop_event.is_set():
            if not scheduler.wait(self.service._scheduler_stop_event):
                break

            try:
                self.service.session_runner.run_cycle(self.service)
            except BaseException as exc:
                self.service._last_error = f"{type(exc).__name__}: {exc}"
                self.service._last_result = TradingCycleResult(
                    session_id=self.service.config.session_id,
                    mode=self.service._runtime_mode_key(),
                    cycle_time=datetime.now().isoformat(),
                    selection_count=0,
                    long_candidate_count=0,
                    short_candidate_count=0,
                    executed_buy_count=0,
                    executed_sell_count=0,
                    status="error",
                    error=traceback.format_exc(),
                )
                try:
                    self.service._persist_runtime_state(extra={"event": "cycle_error"})
                except Exception:
                    pass

    def start_scheduler(self) -> None:
        if self.service._scheduler_running:
            return
        if not self.service.config.cron_expression:
            self.service._log_execution_branch(
                "scheduler",
                "cron_expression is not configured; scheduler will not start",
            )
            return
        self.service._scheduler_stop_event.clear()
        self.service._scheduler_running = True
        self.service._scheduler_thread = Thread(
            target=self.service._run_scheduler_loop,
            daemon=True,
        )
        self.service._scheduler_thread.start()
        self.service._persist_runtime_state(extra={"event": "scheduler_started"})

    def stop_scheduler(self) -> None:
        if not self.service._scheduler_running:
            return
        self.service._scheduler_stop_event.set()
        if self.service._scheduler_thread is not None:
            self.service._scheduler_thread.join(timeout=5)
        self.service._scheduler_running = False
        self.service._persist_runtime_state(extra={"event": "scheduler_stopped"})

    def shutdown_session(self) -> None:
        if self.service._scheduler_running:
            self.stop_scheduler()
        self.service._persist_runtime_state(extra={"event": "service_shutdown"})
