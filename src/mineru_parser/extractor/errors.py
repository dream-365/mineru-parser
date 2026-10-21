"""``ResultExtractionError`` 异常体系。

提取失败与客户端（``MinerUError``）、下载器（``ResultDownloadError``）是三条
互相独立的失败路径：本模块的异常**不继承**二者，但共同继承库级根异常
``MinerUParserError``。公共消息只使用英文固定文案，不携带 manifest 正文、
图片字节或原始 Pydantic 消息。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import MinerUParserError

if TYPE_CHECKING:
    from .models import ExtractionIssue


class ResultExtractionError(MinerUParserError):
    """提取器异常基类。"""


class ResultExtractionConfigurationError(ResultExtractionError):
    """流能力、``limits`` 或注入 callable 非法。"""

    field: str | None

    def __init__(self, field: str | None = None) -> None:
        if field is None:
            super().__init__("invalid result extraction configuration.")
        else:
            super().__init__(f"invalid result extraction configuration: {field}.")
        self.field = field


class ResultExtractionArchiveError(ResultExtractionError):
    """ZIP 结构或成员读取失败。"""

    reason: str
    member: str | None

    def __init__(self, reason: str, *, member: str | None = None) -> None:
        super().__init__(f"result archive error: {reason}.")
        self.reason = reason
        self.member = member


class ResultExtractionManifestError(ResultExtractionError):
    """manifest 缺失、多份、编码或 JSON 结构错误。"""

    reason: str
    manifest_path: str | None
    candidates: tuple[str, ...]
    candidate_count: int
    top_level_members: tuple[str, ...]
    top_level_member_count: int

    def __init__(
        self,
        reason: str,
        *,
        manifest_path: str | None = None,
        candidates: tuple[str, ...] = (),
        candidate_count: int = 0,
        top_level_members: tuple[str, ...] = (),
        top_level_member_count: int = 0,
    ) -> None:
        super().__init__(f"result manifest error: {reason}.")
        self.reason = reason
        self.manifest_path = manifest_path
        self.candidates = tuple(candidates)
        self.candidate_count = candidate_count
        self.top_level_members = tuple(top_level_members)
        self.top_level_member_count = top_level_member_count


class ResultExtractionValidationError(ResultExtractionError):
    """JSON 合法但不符合 ``DocumentContentSchema``。"""

    manifest_path: str
    category: str
    issues: tuple[ExtractionIssue, ...]
    issue_count: int

    def __init__(
        self,
        manifest_path: str,
        *,
        category: str,
        issues: tuple[ExtractionIssue, ...] = (),
        issue_count: int = 0,
    ) -> None:
        super().__init__(f"result manifest does not match content_v2 schema ({category}).")
        self.manifest_path = manifest_path
        self.category = category
        self.issues = tuple(issues)
        self.issue_count = issue_count


class ResultExtractionLimitError(ResultExtractionError):
    """解压后大小或数量超过限额。"""

    resource: str
    limit: int
    actual: int
    member: str | None

    def __init__(
        self,
        resource: str,
        *,
        limit: int = 0,
        actual: int = 0,
        member: str | None = None,
    ) -> None:
        super().__init__(f"result extraction limit exceeded: {resource}.")
        self.resource = resource
        self.limit = limit
        self.actual = actual
        self.member = member


__all__ = [
    "ResultExtractionArchiveError",
    "ResultExtractionConfigurationError",
    "ResultExtractionError",
    "ResultExtractionLimitError",
    "ResultExtractionManifestError",
    "ResultExtractionValidationError",
]
