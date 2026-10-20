"""MinerU 客户端实现子包。

公共 API 由 :mod:`mineru_parser` 顶层统一再导出；这里同样支持
``from mineru_parser.client import ...`` 的直接导入。
"""

from __future__ import annotations

from ._telemetry import MetricHook
from .api import MinerUApiClient, MinerUClient
from .async_result import AsyncResult
from .errors import (
    MinerUAuthenticationError,
    MinerUConfigurationError,
    MinerUError,
    MinerUExecutionError,
    MinerUQuotaError,
    MinerUTimeoutError,
    MinerUTransientError,
)
from .models import (
    MinerUProgress,
    MinerUTaskResult,
    MinerUTaskState,
    MinerUTaskStatus,
)
from .polling import DEFAULT_POLL_POLICY, PollPolicy

__all__ = [
    "DEFAULT_POLL_POLICY",
    "AsyncResult",
    "MetricHook",
    "MinerUApiClient",
    "MinerUAuthenticationError",
    "MinerUClient",
    "MinerUConfigurationError",
    "MinerUError",
    "MinerUExecutionError",
    "MinerUProgress",
    "MinerUQuotaError",
    "MinerUTaskResult",
    "MinerUTaskState",
    "MinerUTaskStatus",
    "MinerUTimeoutError",
    "MinerUTransientError",
    "PollPolicy",
]
