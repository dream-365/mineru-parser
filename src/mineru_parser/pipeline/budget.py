"""端到端预算：``timeout`` / ``deadline_epoch`` 的换算与检查点。

预算只在入口处换算一次为**单调时钟**上的截止点；之后所有检查都基于
注入的单调时钟，测试无需 sleep 即可确定性地触发耗尽（AC-4.2 / AC-4.9）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from .errors import PipelineConfigurationError, PipelineTimeoutError
from .stages import PipelineStage

if TYPE_CHECKING:
    from .._client.models import MinerUTaskStatus


def _finite_number(value: object, *, field: str, non_negative: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineConfigurationError(
            f"{field} must be a finite number.", field=field
        )
    number = float(value)
    if not math.isfinite(number) or (non_negative and number < 0):
        qualifier = "a finite non-negative number" if non_negative else "finite"
        raise PipelineConfigurationError(
            f"{field} must be {qualifier}.", field=field
        )
    return number


class Budget:
    """一次调用的端到端预算；``deadline`` 为 ``None`` 表示不设上限。"""

    __slots__ = ("_deadline", "_monotonic")

    def __init__(
        self,
        *,
        deadline: float | None,
        monotonic: Callable[[], float],
    ) -> None:
        self._deadline = deadline
        self._monotonic = monotonic

    @classmethod
    def from_parameters(
        cls,
        *,
        timeout: object,
        deadline_epoch: object,
        monotonic: Callable[[], float],
        wall_clock: Callable[[], float],
    ) -> Budget:
        """把调用方参数换算为单调时钟截止点。

        非法参数在**创建任何组件之前**抛 ``PipelineConfigurationError``；
        ``deadline_epoch`` 已过期是合法配置，只是剩余预算为 0——由第一个
        检查点（``submit``）判定为预算耗尽。
        """
        if timeout is not None and deadline_epoch is not None:
            raise PipelineConfigurationError(
                "timeout and deadline_epoch are mutually exclusive.",
                field="timeout",
            )

        now = monotonic()
        if timeout is not None:
            seconds = _finite_number(timeout, field="timeout", non_negative=True)
            return cls(deadline=now + seconds, monotonic=monotonic)

        if deadline_epoch is not None:
            epoch = _finite_number(
                deadline_epoch, field="deadline_epoch", non_negative=False
            )
            remaining = epoch - wall_clock()
            return cls(deadline=now + max(0.0, remaining), monotonic=monotonic)

        return cls(deadline=None, monotonic=monotonic)

    def remaining(self) -> float | None:
        """剩余秒数（不小于 0）；无端到端上限时返回 ``None``。"""
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - self._monotonic())

    def exhausted(self) -> bool:
        return self._deadline is not None and self._monotonic() >= self._deadline

    def check(
        self,
        stage: PipelineStage,
        *,
        task_id: str | None = None,
        last_status: MinerUTaskStatus | None = None,
    ) -> None:
        """在检查点判定预算；耗尽时抛 ``PipelineTimeoutError``。"""
        if self.exhausted():
            raise PipelineTimeoutError(
                f"Pipeline budget exceeded during the '{stage.value}' stage.",
                stage=stage,
                task_id=task_id,
                last_status=last_status,
            )


__all__ = ["Budget"]
