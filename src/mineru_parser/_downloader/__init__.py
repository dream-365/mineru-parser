"""结果包下载器（内部实现，不对外）。

本包是 SPEC-002 的私有实现，仅由 :mod:`mineru_parser.pipeline` 内部使用；
不提供公开导入路径，也不遵循 SemVer。行为契约见 SPEC-002。
"""

from __future__ import annotations

from .._telemetry import MetricHook
from ..errors import MinerUParserError
from .downloader import ResultDownloader
from .errors import (
    ResultDownloadConfigurationError,
    ResultDownloadContentTypeError,
    ResultDownloadError,
    ResultDownloadHTTPError,
    ResultDownloadSecurityError,
    ResultDownloadTimeoutError,
    ResultDownloadTooLargeError,
    ResultDownloadTransientError,
)
from .policy import DEFAULT_DOWNLOAD_RETRY_POLICY, DownloadRetryPolicy
from .security import DnsResolver

__all__ = [
    "DEFAULT_DOWNLOAD_RETRY_POLICY",
    "DnsResolver",
    "DownloadRetryPolicy",
    "MetricHook",
    "MinerUParserError",
    "ResultDownloadConfigurationError",
    "ResultDownloadContentTypeError",
    "ResultDownloadError",
    "ResultDownloadHTTPError",
    "ResultDownloadSecurityError",
    "ResultDownloadTimeoutError",
    "ResultDownloadTooLargeError",
    "ResultDownloadTransientError",
    "ResultDownloader",
]
