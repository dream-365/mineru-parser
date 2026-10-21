"""MinerU 客户端实现子包（内部实现，不对外）。

本包是 SPEC-001 的私有实现，仅由 :mod:`mineru_parser.pipeline` 内部使用；
不提供公开导入路径，也不遵循 SemVer。行为契约见 SPEC-001。
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
