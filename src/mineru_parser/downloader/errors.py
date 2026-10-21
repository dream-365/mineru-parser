"""``ResultDownloader`` 的异常体系。

下载与 MinerU API 调用是两条独立的失败路径：本模块的异常不继承
``MinerUError``，公共消息与 ``__cause__`` 都不得泄漏原始签名 URL。
"""

from __future__ import annotations


class ResultDownloadError(Exception):
    """下载器异常基类。"""


class ResultDownloadConfigurationError(ResultDownloadError):
    """本地配置或初始 URL 非法。"""


class ResultDownloadSecurityError(ResultDownloadError):
    """SSRF、非 HTTP(S)、TLS、重定向越界 / 降级。"""


class ResultDownloadTooLargeError(ResultDownloadError):
    """响应体超过 ``max_bytes``。"""

    max_bytes: int
    received_bytes: int | None
    declared_bytes: int | None

    def __init__(
        self,
        message: str,
        *,
        max_bytes: int,
        received_bytes: int | None = None,
        declared_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.max_bytes = max_bytes
        self.received_bytes = received_bytes
        self.declared_bytes = declared_bytes


class ResultDownloadContentTypeError(ResultDownloadError):
    """``Content-Type`` 白名单不匹配或缺失。"""

    content_type: str | None
    allowed: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        content_type: str | None,
        allowed: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.content_type = content_type
        self.allowed = allowed


class ResultDownloadHTTPError(ResultDownloadError):
    """终态 HTTP 状态（含 206、未跟随的 3xx）。"""

    status_code: int | None
    url: str | None

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class ResultDownloadTransientError(ResultDownloadError):
    """重试耗尽后的瞬态失败。"""

    attempts: int
    last_error: str | None
    last_status_code: int | None
    retry_after: float | None

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        last_error: str | None = None,
        last_status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.last_status_code = last_status_code
        self.retry_after = retry_after


class ResultDownloadTimeoutError(ResultDownloadTransientError):
    """最后一次失败为超时，或总预算耗尽。"""


__all__ = [
    "ResultDownloadConfigurationError",
    "ResultDownloadContentTypeError",
    "ResultDownloadError",
    "ResultDownloadHTTPError",
    "ResultDownloadSecurityError",
    "ResultDownloadTimeoutError",
    "ResultDownloadTooLargeError",
    "ResultDownloadTransientError",
]
