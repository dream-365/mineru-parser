"""提取结果的静态类型。

运行时 ``extract_result`` 返回普通 ``dict``；这里的 ``TypedDict`` 只提供静态
类型与文档约束。``TypedDict`` 的注解在类体作用域求值，``bytes`` 字段名解析到
内置类型，与已发布的键名约定一致。
"""

from __future__ import annotations

from typing import TypedDict

from ..schema.content_v2 import DocumentContentSchema


class ExtractedImage(TypedDict):
    path: str
    bytes: bytes


class ExtractedResult(TypedDict):
    pages: DocumentContentSchema
    images: list[ExtractedImage]


class ExtractionIssue(TypedDict):
    loc: tuple[str | int, ...]
    type: str
    msg: str


__all__ = ["ExtractedImage", "ExtractedResult", "ExtractionIssue"]
