"""共享 HTTP 辅助函数：``Retry-After`` 解析与状态码分类。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any


def status_class(status: int | None) -> str:
    """把状态码映射为低基数标签（``2xx`` / ``4xx`` / ``error``）。"""
    return "error" if status is None else f"{status // 100}xx"


def to_finite_float(value: object) -> float | None:
    """把数值转换为有限 ``float``；布尔、非数值、溢出与非有限值返回 ``None``。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_retry_after(value: str | None, *, now: float) -> float | None:
    """解析 ``Retry-After``（秒数或 HTTP-date），返回非负秒数。"""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except (ValueError, OverflowError):
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        try:
            seconds = parsed.timestamp() - now
        except (OverflowError, OSError, ValueError):
            return None
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def retry_after_from(
    headers: Mapping[str, Any] | None,
    *,
    wall_clock: Callable[[], float],
) -> float | None:
    """从响应头读取并解析 ``Retry-After``；缺失或非法时返回 ``None``。"""
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        for key, item in headers.items():
            if str(key).lower() == "retry-after":
                value = item
                break
    return parse_retry_after(value, now=wall_clock())


__all__ = [
    "parse_retry_after",
    "retry_after_from",
    "status_class",
    "to_finite_float",
]
