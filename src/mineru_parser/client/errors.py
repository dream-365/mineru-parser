"""MinerU 客户端异常体系与业务错误码表。

这些异常只描述 MinerU 调用语义；调用方（例如任务执行层）负责把它们
映射为自己的可重试 / 终态 / 超时异常。

``MinerUAuthenticationError`` / ``MinerUQuotaError`` /
``MinerUConfigurationError`` 都继承 ``MinerUExecutionError``，因此既有的
``except MinerUExecutionError`` 不受影响；需要细分时先捕获更具体的类型。
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..errors import MinerUParserError

if TYPE_CHECKING:
    from .models import MinerUTaskStatus


class MinerUError(MinerUParserError):
    """MinerU 客户端异常基类。

    继承库级根 ``MinerUParserError``，与 ``ResultDownloadError`` /
    ``ResultExtractionError`` **互不继承**；既有 ``except MinerUError`` 的
    捕获语义不变。
    """


class MinerUTransientError(MinerUError):
    """可安全重试：确定请求未发出，或只读查询失败。"""

    retry_after: float | None

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MinerUExecutionError(MinerUError):
    """终态失败：结果未知、请求被拒绝，或外部明确失败。"""


class MinerUAuthenticationError(MinerUExecutionError):
    """Token 缺失、无效、过期，或无权访问任务。"""


class MinerUQuotaError(MinerUExecutionError):
    """每日额度或 HTML 解析额度耗尽。"""


class MinerUConfigurationError(MinerUExecutionError):
    """本地参数非法：data_id、base_url、轮询参数、API Key 为空。"""


class MinerUTimeoutError(MinerUError):
    """超过调用方给定的 deadline。

    ``last_status`` 是超时前最后一次成功查询到的状态（从未成功则为
    ``None``），方便调用方决定是继续等待还是放弃。
    """

    task_id: str | None
    last_status: MinerUTaskStatus | None

    def __init__(
        self,
        message: str,
        *,
        task_id: str | None = None,
        last_status: MinerUTaskStatus | None = None,
    ) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.last_status = last_status


# 官方错误码分类（纯数据，不依赖网络）。键统一使用 ``str(code)``，避免
# int / str 混用；``-60014``（删除运行中任务）本模块没有对应 API，不收录。
ERROR_CODE_KIND: Mapping[str, str] = MappingProxyType(
    {
        # auth
        "A0202": "auth",
        "A0211": "auth",
        "-60013": "auth",
        # quota
        "-60018": "quota",
        "-60019": "quota",
        # transient
        "-10001": "transient",
        "-60001": "transient",
        "-60003": "transient",
        "-60007": "transient",
        "-60008": "transient",
        "-60009": "transient",
        "-60011": "transient",
        "-60012": "transient",
        "-60021": "transient",
        "-60022": "transient",
        # terminal
        "-500": "terminal",
        "-10002": "terminal",
        "-60002": "terminal",
        "-60004": "terminal",
        "-60005": "terminal",
        "-60006": "terminal",
        "-60010": "terminal",
        "-60015": "terminal",
        "-60016": "terminal",
        "-60017": "terminal",
        "-60020": "terminal",
    }
)


def classify_business_error(code: int | str) -> str:
    """返回 ``auth`` / ``quota`` / ``transient`` / ``terminal`` / ``unknown``。"""
    return ERROR_CODE_KIND.get(str(code), "unknown")


__all__ = [
    "ERROR_CODE_KIND",
    "MinerUAuthenticationError",
    "MinerUConfigurationError",
    "MinerUError",
    "MinerUExecutionError",
    "MinerUQuotaError",
    "MinerUTimeoutError",
    "MinerUTransientError",
    "classify_business_error",
]
