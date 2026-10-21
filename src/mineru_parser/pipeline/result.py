"""``parse()`` 的返回值：状态信封与错误信息。

运行时都是普通 ``dict``；``TypedDict`` 只提供静态类型与文档约束。
``ParseResult`` **不继承** ``ExtractedResult``：解析产物整体收在 ``data``
里，与任务元数据平级且互不污染。
"""

from __future__ import annotations

from typing import Literal, TypedDict

from .._extractor.models import ExtractedResult
from .stages import PipelineStage


class ErrorMessage(TypedDict):
    stage: PipelineStage
    error_type: str
    message: str
    cause_type: str | None


class ParseResult(TypedDict):
    status: Literal["success", "failed"]
    data: ExtractedResult | None
    task_id: str | None
    data_id: str | None
    zip_url: str | None
    error: ErrorMessage | None


__all__ = ["ErrorMessage", "ParseResult"]
