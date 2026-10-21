"""``AsyncResult``：任务身份、状态缓存与终态解释。

结果句柄只持有 ``task_id``、可选的 ``data_id`` 和服务端最近一次状态；
真正的轮询节奏由 :mod:`mineru_parser._client.polling` 决定。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from ._time import elapsed_ms
from ._validation import (
    validate_data_id,
    validate_deadline_epoch,
    validate_non_negative,
    validate_task_id,
)
from .errors import (
    MinerUConfigurationError,
    MinerUExecutionError,
    MinerUTimeoutError,
)
from .models import (
    MinerUTaskResult,
    MinerUTaskState,
    MinerUTaskStatus,
)
from .polling import PollPolicy

if TYPE_CHECKING:
    from .api import MinerUApiClient


class AsyncResult:
    """一个已提交（或已恢复）的 MinerU 任务结果句柄。

    同步阻塞式句柄，不实现 ``asyncio.Future``；获取最终结果通过
    ``wait()`` 完成。句柄不是线程安全的；多个线程等待同一任务时，每个
    线程应各自通过 ``client.resume(task_id)`` 创建独立句柄。
    """

    __slots__ = ("_client", "_data_id", "_result", "_status", "_task_id")

    def __init__(
        self,
        *,
        client: MinerUApiClient,
        task_id: str,
        data_id: str | None = None,
    ) -> None:
        self._client = client
        self._task_id = validate_task_id(task_id)
        self._data_id = validate_data_id(data_id)
        self._status: MinerUTaskStatus | None = None
        self._result: MinerUTaskResult | None = None

    # --- 只读属性 ---------------------------------------------------------

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def data_id(self) -> str | None:
        if self._data_id is not None:
            return self._data_id
        if self._status is not None:
            return self._status.data_id
        return None

    @property
    def status(self) -> MinerUTaskStatus | None:
        """最近一次查询到的状态；尚未查询时为 ``None``。"""
        return self._status

    @property
    def state(self) -> MinerUTaskState | None:
        return self._status.state if self._status is not None else None

    @property
    def result(self) -> MinerUTaskResult | None:
        """成功后的结果；尚未成功时为 ``None``。"""
        if (
            self._result is None
            and self._status is not None
            and self._status.state is MinerUTaskState.SUCCEEDED
        ):
            self._result = self._build_result(self._status)
        return self._result

    def __repr__(self) -> str:
        state = self._status.state.value if self._status is not None else "unknown"
        return (
            f"AsyncResult(task_id={self._task_id!r}, "
            f"data_id={self.data_id!r}, state={state!r})"
        )

    # --- 查询 -------------------------------------------------------------

    def refresh(self) -> MinerUTaskStatus:
        """查询一次状态并更新缓存。

        终态（成功 / 失败 / 取消）一旦观察到就不再重复请求；返回状态
        本身，不把服务端失败翻译成异常。
        """
        if self._status is not None and self._status.state.is_terminal:
            return self._status
        status = self._client._trace(self._task_id)
        self._status = status
        return status

    # --- 等待 -------------------------------------------------------------

    def wait(
        self,
        *,
        timeout: float | None = None,
        deadline_epoch: float | None = None,
        on_update: Callable[[MinerUTaskStatus], None] | None = None,
        policy: PollPolicy | None = None,
    ) -> MinerUTaskResult:
        """轮询直到完成、失败、取消或超时。

        ``timeout`` 是相对秒数；``deadline_epoch`` 是绝对 Unix 时间戳；
        两者只能给一个。都不给表示一直等待。超时抛
        :class:`MinerUTimeoutError`（携带最后已知状态），服务端失败 /
        取消抛 :class:`MinerUExecutionError`，认证与额度错误按各自类型抛出。

        成功后重复调用直接返回缓存结果；失败后重复调用会立即抛同一类
        异常，不再访问网络。
        """
        budget = self._resolve_budget(timeout, deadline_epoch)
        if on_update is not None and not callable(on_update):
            raise MinerUConfigurationError("on_update must be callable.")
        if policy is not None and not isinstance(policy, PollPolicy):
            raise MinerUConfigurationError("policy must be a PollPolicy instance.")

        started = time.perf_counter()
        try:
            if self._result is not None:
                return self._result
            if self._status is not None and self._status.state.is_terminal:
                result = self._finish(self._status, started=started, poll_count=0)
            else:
                outcome = self._client._poller(policy).run(
                    self.refresh,
                    timeout=budget,
                    on_update=on_update,
                    task_id=self._task_id,
                )
                result = self._finish(
                    outcome.status,
                    started=started,
                    poll_count=outcome.poll_count,
                )
        except MinerUTimeoutError:
            self._client._telemetry.metric(
                "mineru.task.duration_ms",
                elapsed_ms(started),
                {"outcome": "timeout"},
            )
            raise
        except MinerUExecutionError:
            self._client._telemetry.metric(
                "mineru.task.duration_ms",
                elapsed_ms(started),
                {"outcome": "failed"},
            )
            raise

        self._client._telemetry.metric(
            "mineru.task.duration_ms",
            elapsed_ms(started),
            {"outcome": "success"},
        )
        return result

    # --- 内部 -------------------------------------------------------------

    def _resolve_budget(
        self,
        timeout: float | None,
        deadline_epoch: float | None,
    ) -> float | None:
        if timeout is not None and deadline_epoch is not None:
            raise MinerUConfigurationError(
                "timeout and deadline_epoch are mutually exclusive."
            )
        if timeout is not None:
            return validate_non_negative(timeout, "timeout")
        if deadline_epoch is not None:
            deadline = validate_deadline_epoch(deadline_epoch)
            remaining = deadline - self._client._runtime.wall_clock()
            return max(0.0, remaining)
        return None

    def _build_result(self, status: MinerUTaskStatus) -> MinerUTaskResult:
        return MinerUTaskResult(
            zip_url=status.full_zip_url or "",
            provider_task_id=status.task_id or self._task_id,
            data_id=status.data_id or self._data_id,
        )

    def _finish(
        self,
        status: MinerUTaskStatus,
        *,
        started: float,
        poll_count: int,
    ) -> MinerUTaskResult:
        state = status.state
        if state is MinerUTaskState.SUCCEEDED:
            result = self._build_result(status)
            self._result = result
            self._client._telemetry.log(
                "mineru.succeeded",
                provider_task_id=self._task_id,
                provider_state=status.raw_state,
                duration_ms=elapsed_ms(started),
                poll_count=poll_count,
            )
            return result

        if state is MinerUTaskState.FAILED:
            self._client._telemetry.log(
                "mineru.failed",
                level=logging.WARNING,
                provider_task_id=self._task_id,
                provider_state=status.raw_state,
                error_type="MinerUTaskFailed",
            )
            raise MinerUExecutionError(
                status.err_msg or f"MinerU task {self._task_id} failed."
            )

        if state is MinerUTaskState.CANCELED:
            self._client._telemetry.log(
                "mineru.failed",
                level=logging.WARNING,
                provider_task_id=self._task_id,
                provider_state=status.raw_state,
                error_type="MinerUTaskCanceled",
            )
            raise MinerUExecutionError(f"MinerU task {self._task_id} was cancelled.")

        raise MinerUExecutionError(
            f"MinerU task {self._task_id} ended in unexpected state {state.value!r}."
        )


__all__ = ["AsyncResult"]
