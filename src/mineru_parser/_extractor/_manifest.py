"""manifest 解码、JSON 解析与 Schema 校验。

本模块不读取成员、不发现成员。错误清洗只保留 ``loc`` / ``type`` / ``msg``；
原始 ``ValidationError`` 必须同时不出现在公共异常的 ``__cause__`` 与
``__context__`` 中——因此在 ``except`` 块内只做信息提取，待 handler 退出后
再抛出公共异常对象。
"""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from ..schema.content_v2 import DocumentContentSchema
from .errors import (
    ResultExtractionManifestError,
    ResultExtractionValidationError,
)
from .models import ExtractionIssue

_SCHEMA = TypeAdapter(DocumentContentSchema)

_MAX_ISSUES_IN_ERROR = 20

# Pydantic v2 中 ``msg`` 会内嵌输入值的错误类型；一律替换为固定文案。
_UNSAFE_MSG_ERROR_TYPES = frozenset({"union_tag_invalid"})
_UNSAFE_MSG_REPLACEMENT = (
    "Input tag does not match any of the expected block types."
)

_UNKNOWN_BLOCK_TYPES = frozenset({"union_tag_invalid", "union_tag_not_found"})


def decode_manifest(data: bytes, manifest_path: str) -> str:
    """按 UTF-8 解码并去除一个可选的 BOM；不猜测其他编码。"""
    pending: ResultExtractionManifestError | None = None
    text = ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        pending = ResultExtractionManifestError(
            "invalid_encoding", manifest_path=manifest_path
        )

    # 在 handler 之外抛出，确保 __context__ 不携带原始异常。
    if pending is not None:
        raise pending

    if text.startswith(chr(0xFEFF)):
        text = text[1:]
    return text


def validate_manifest(text: str, manifest_path: str) -> DocumentContentSchema:
    """用模块级 ``TypeAdapter`` 完成 JSON 与 Schema 校验。"""
    pending: (
        ResultExtractionManifestError | ResultExtractionValidationError | None
    ) = None
    pages: DocumentContentSchema | None = None

    try:
        pages = _SCHEMA.validate_json(text)
    except RecursionError:
        # 理论兜底：jiter 的递归上限通常以 json_invalid 报出。
        pending = ResultExtractionManifestError(
            "invalid_json", manifest_path=manifest_path
        )
    except ValidationError as exc:
        pending = _classify_validation_error(exc, manifest_path)

    # 在 handler 之外抛出：__cause__ 与 __context__ 均为 None。
    if pending is not None:
        raise pending

    assert pages is not None
    return pages


def _classify_validation_error(
    exc: ValidationError,
    manifest_path: str,
) -> ResultExtractionManifestError | ResultExtractionValidationError:
    details = exc.errors(include_url=False)

    if any(detail.get("type") == "json_invalid" for detail in details):
        return ResultExtractionManifestError(
            "invalid_json", manifest_path=manifest_path
        )

    issues: list[ExtractionIssue] = []
    for detail in details[:_MAX_ISSUES_IN_ERROR]:
        error_type = detail.get("type", "")
        msg = detail.get("msg", "")
        if error_type in _UNSAFE_MSG_ERROR_TYPES:
            msg = _UNSAFE_MSG_REPLACEMENT
        issues.append(
            {
                "loc": tuple(detail.get("loc", ())),
                "type": error_type,
                "msg": msg,
            }
        )

    return ResultExtractionValidationError(
        manifest_path,
        category=_validation_category(details),
        issues=tuple(issues),
        issue_count=len(details),
    )


def _validation_category(details: list[dict]) -> str:
    """按契约顺序归一粗粒度失败类别，命中即止。"""
    types = {detail.get("type", "") for detail in details}
    if types & _UNKNOWN_BLOCK_TYPES:
        return "unknown_block_type"
    if any("bbox" in tuple(detail.get("loc", ())) for detail in details):
        return "invalid_bbox"
    if any(len(detail.get("loc", ())) == 0 for detail in details) or (
        "list_type" in types
    ):
        return "root_shape"
    if "missing" in types:
        return "missing_field"
    return "other"


__all__ = ["decode_manifest", "validate_manifest"]
