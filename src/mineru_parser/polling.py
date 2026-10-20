"""轮询策略与循环。

这一层只回答“什么时候再查、什么时候放弃”，不解释任务的成败；
终态语义由 :class:`~mineru_parser.task.MinerUTask` 处理。
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from ._telemetry import Telemetry
from ._time import elapsed_ms
from ._validation import (
    is_finite_number,
    validate_max_errors,
    validate_non_negative,
    validate_positive,
)
from .errors import (
    MinerUConfigurationError,
    MinerUExecutionError,
    MinerUTimeoutError,
    MinerUTransientError,
)
from .models import MinerUTaskStatus


@dataclass(frozen=True, slots=True)
class PollPolicy:
    """轮询退避策略。

    ``jitter`` 是延迟因子下界的比例：实际延迟为
    ``interval * uniform(1 - jitter, 1)``。``initial_interval`` 是每次
    状态变化后的基数，循环会先推进 interval 再计算本次延迟（保留原有
    行为）。
    """

    initial_interval: float = 3.0
    max_interval: float = 30.0
    backoff: float = 1.5
    jitter: float = 0.5
    max_consecutive_errors: int = 3
    max_retry_after: float = 60.0

    def __post_init__(self) -> None:
        initial = validate_positive(self.initial_interval, "initial_interval")
        maximum = validate_positive(self.max_interval, "max_interval")
        if maximum < initial:
            raise MinerUConfigurationError("max_interval must be >= initial_interval.")
        backoff = validate_positive(self.backoff, "backoff")
        if backoff < 1.0:
            raise MinerUConfigurationError("backoff must be >= 1.0.")
        if (
            isinstance(self.jitter, bool)
            or not isinstance(self.jitter, (int, float))
            or not is_finite_number(self.jitter)
            or not 0.0 <= float(self.jitter) < 1.0
        ):
            raise MinerUConfigurationError("jitter must be a number in [0, 1).")
        validate_max_errors(self.max_consecutive_errors)
        validate_non_negative(self.max_retry_after, "max_retry_after")

    def next_interval(self, interval: float) -> float:
        return min(interval * self.backoff, self.max_interval)

    def delay(
        self,
        interval: float,
        *,
        retry_after: float | None,
        random_value: float,
    ) -> float:
        if retry_after is not None:
            # 服务端明确给出的等待时间优先，且不再叠加随机抖动。
            return max(0.0, min(retry_after, self.max_retry_after))
        factor = 1.0 - self.jitter + self.jitter * random_value
        return interval * factor


DEFAULT_POLL_POLICY = PollPolicy()


@dataclass(frozen=True, slots=True)
class PollRuntime:
    """可注入的时间 / 随机源，便于测试与调度器集成。"""

    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    random_fn: Callable[[], float] = random.random


@dataclass(frozen=True, slots=True)
class PollOutcome:
    status: MinerUTaskStatus
    poll_count: int


class Poller:
    def __init__(
        self,
        *,
        policy: PollPolicy,
        runtime: PollRuntime,
        telemetry: Telemetry,
    ) -> None:
        self._policy = policy
        self._runtime = runtime
        self._telemetry = telemetry

    def run(
        self,
        fetch: Callable[[], MinerUTaskStatus],
        *,
        timeout: float | None,
        on_update: Callable[[MinerUTaskStatus], None] | None,
        task_id: str,
    ) -> PollOutcome:
        """反复调用 ``fetch`` 直到终态、超时或连续错误耗尽。"""
        interval = self._policy.initial_interval
        consecutive_errors = 0
        poll_count = 0
        last_status: MinerUTaskStatus | None = None
        started = time.perf_counter()
        deadline = None if timeout is None else self._runtime.monotonic() + timeout

        while True:
            self._check_deadline(deadline, task_id, last_status, started)

            poll_started = time.perf_counter()
            try:
                status = fetch()
            except MinerUTransientError as exc:
                poll_ms = elapsed_ms(poll_started)
                consecutive_errors += 1
                self._telemetry.metric(
                    "mineru.poll.duration_ms", poll_ms, {"state": "error"}
                )
                self._telemetry.metric(
                    "mineru.poll.errors",
                    1,
                    {"type": type(exc).__name__},
                )
                self._telemetry.log(
                    "mineru.poll.error",
                    level=logging.WARNING,
                    provider_task_id=task_id,
                    error_type=type(exc).__name__,
                    consecutive_errors=consecutive_errors,
                    retry_after=exc.retry_after,
                )
                if consecutive_errors >= self._policy.max_consecutive_errors:
                    raise MinerUExecutionError(
                        "MinerU polling failed "
                        f"{consecutive_errors} consecutive times: {exc}"
                    ) from exc
                # 瞬态错误也推进退避；Retry-After 优先且不叠加抖动。
                interval = self._policy.next_interval(interval)
                delay = self._policy.delay(
                    interval,
                    retry_after=exc.retry_after,
                    random_value=self._random_value(),
                )
                self._sleep_until(delay, deadline, task_id, last_status, started)
                continue

            poll_ms = elapsed_ms(poll_started)
            consecutive_errors = 0
            poll_count += 1
            self._telemetry.metric(
                "mineru.poll.total", 1, {"state": status.state.value}
            )
            self._telemetry.metric(
                "mineru.poll.duration_ms",
                poll_ms,
                {"state": status.state.value},
            )

            state_changed = last_status is None or status.state is not last_status.state
            progress_changed = _progress_changed(last_status, status)
            progress = status.progress
            self._telemetry.log(
                "mineru.poll",
                level=logging.INFO if state_changed else logging.DEBUG,
                provider_task_id=task_id,
                provider_state=status.raw_state,
                state=status.state.value,
                extracted_pages=(
                    progress.extracted_pages if progress is not None else None
                ),
                total_pages=(progress.total_pages if progress is not None else None),
                consecutive_errors=consecutive_errors,
            )

            if state_changed:
                # 状态变化重置间隔；进度变化不重置，避免轮询被拖回高频。
                interval = self._policy.initial_interval
            if state_changed or progress_changed:
                self._notify(on_update, status)
            last_status = status

            if status.state.is_terminal:
                return PollOutcome(status=status, poll_count=poll_count)

            interval = self._policy.next_interval(interval)
            delay = self._policy.delay(
                interval,
                retry_after=None,
                random_value=self._random_value(),
            )
            self._sleep_until(delay, deadline, task_id, last_status, started)

    # --- 内部 -------------------------------------------------------------

    def _random_value(self) -> float:
        value = float(self._runtime.random_fn())
        return min(1.0, max(0.0, value))

    def _timeout_error(
        self,
        task_id: str,
        last_status: MinerUTaskStatus | None,
        started: float,
    ) -> MinerUTimeoutError:
        last_state = last_status.state.value if last_status is not None else "unknown"
        self._telemetry.log(
            "mineru.timeout",
            level=logging.WARNING,
            provider_task_id=task_id,
            last_state=last_state,
            elapsed_ms=elapsed_ms(started),
        )
        return MinerUTimeoutError(
            f"MinerU task {task_id} exceeded its deadline; "
            f"last known state: {last_state}.",
            task_id=task_id,
            last_status=last_status,
        )

    def _check_deadline(
        self,
        deadline: float | None,
        task_id: str,
        last_status: MinerUTaskStatus | None,
        started: float,
    ) -> None:
        if deadline is not None and self._runtime.monotonic() >= deadline:
            raise self._timeout_error(task_id, last_status, started)

    def _sleep_until(
        self,
        seconds: float,
        deadline: float | None,
        task_id: str,
        last_status: MinerUTaskStatus | None,
        started: float,
    ) -> None:
        if deadline is not None:
            remaining = deadline - self._runtime.monotonic()
            if remaining <= 0:
                raise self._timeout_error(task_id, last_status, started)
            seconds = min(seconds, remaining)
        self._runtime.sleep(seconds)
        self._check_deadline(deadline, task_id, last_status, started)

    def _notify(
        self,
        on_update: Callable[[MinerUTaskStatus], None] | None,
        status: MinerUTaskStatus,
    ) -> None:
        if on_update is None:
            return
        try:
            on_update(status)
        except Exception as exc:  # noqa: BLE001 - 回调失败不中断轮询
            self._telemetry.log(
                "mineru.on_update.failed",
                level=logging.WARNING,
                error_type=type(exc).__name__,
            )


def _progress_changed(
    previous: MinerUTaskStatus | None,
    current: MinerUTaskStatus,
) -> bool:
    previous_progress = previous.progress if previous is not None else None
    current_progress = current.progress
    if previous_progress is None or current_progress is None:
        return False
    previous_pages = previous_progress.extracted_pages
    current_pages = current_progress.extracted_pages
    if previous_pages is None or current_pages is None:
        return False
    return previous_pages != current_pages


__all__ = [
    "DEFAULT_POLL_POLICY",
    "PollOutcome",
    "PollPolicy",
    "PollRuntime",
    "Poller",
]
