"""下载重试策略。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .._http import to_finite_float
from .errors import ResultDownloadConfigurationError


def _positive(value: object, name: str) -> float:
    number = to_finite_float(value)
    if number is None or number <= 0:
        raise ResultDownloadConfigurationError(f"{name} must be a positive number.")
    return number


def _non_negative(value: object, name: str) -> float:
    number = to_finite_float(value)
    if number is None or number < 0:
        raise ResultDownloadConfigurationError(f"{name} must be zero or positive.")
    return number


@dataclass(frozen=True, slots=True)
class DownloadRetryPolicy:
    """不可变重试策略：尝试次数、指数退避、抖动与 ``Retry-After`` 上限。

    第 ``n`` 次尝试失败后的延迟为
    ``min(initial_interval * backoff ** (n - 1), max_interval) * factor``，
    其中 ``factor = (1 - jitter) + jitter * U``，``U`` 为 ``[0, 1]`` 内的
    随机值。存在合法 ``Retry-After`` 时优先使用且不叠加抖动。
    """

    max_attempts: int = 3
    initial_interval: float = 0.5
    backoff: float = 2.0
    max_interval: float = 8.0
    jitter: float = 0.2
    max_retry_after: float = 60.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ResultDownloadConfigurationError(
                "max_attempts must be an integer >= 1."
            )
        initial = _positive(self.initial_interval, "initial_interval")
        maximum = _positive(self.max_interval, "max_interval")
        if maximum < initial:
            raise ResultDownloadConfigurationError(
                "max_interval must be >= initial_interval."
            )
        growth = _positive(self.backoff, "backoff")
        if growth < 1.0:
            raise ResultDownloadConfigurationError("backoff must be >= 1.0.")
        jitter = to_finite_float(self.jitter)
        if jitter is None or not 0.0 <= jitter < 1.0:
            raise ResultDownloadConfigurationError("jitter must be a number in [0, 1).")
        _non_negative(self.max_retry_after, "max_retry_after")

    def delay(
        self,
        attempt: int,
        *,
        retry_after: float | None,
        random_value: float,
    ) -> float:
        """返回第 ``attempt`` 次尝试失败后的等待秒数。"""
        if retry_after is not None:
            return max(0.0, min(retry_after, self.max_retry_after))
        try:
            growth = self.backoff ** (attempt - 1)
        except OverflowError:
            # 指数增长溢出时直接按 max_interval 截断，而不是把 OverflowError
            # 泄漏给调用方。
            growth = math.inf
        base = min(self.initial_interval * growth, self.max_interval)
        factor = (1.0 - self.jitter) + self.jitter * random_value
        return base * factor


DEFAULT_DOWNLOAD_RETRY_POLICY = DownloadRetryPolicy()

__all__ = ["DEFAULT_DOWNLOAD_RETRY_POLICY", "DownloadRetryPolicy"]
