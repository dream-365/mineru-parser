"""结果包下载器。

公共 API 由 :mod:`mineru_parser` 顶层统一再导出；这里同样支持
``from mineru_parser.downloader import ...`` 的直接导入。
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
