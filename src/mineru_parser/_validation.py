"""配置参数校验：纯函数，不依赖网络、日志或客户端状态。"""

from __future__ import annotations

import math
from urllib.parse import urlsplit

from .errors import MinerUConfigurationError

_HTTP_SCHEMES = frozenset({"http", "https"})


def is_finite_number(value: object) -> bool:
    """拒绝 NaN / Infinity：它们能通过 ``<= 0`` 比较，却会在 sleep
    或 socket 超时处抛出未分类异常。"""
    return not (isinstance(value, float) and not math.isfinite(value))


def is_absolute_http_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port  # 触发非法端口校验
    except ValueError:
        return False
    return parsed.scheme.lower() in _HTTP_SCHEMES and bool(parsed.hostname)


def validate_api_key(api_key: str | None) -> str | None:
    if api_key is None:
        return None
    if not isinstance(api_key, str) or not api_key.strip():
        raise MinerUConfigurationError("MinerU API key must not be blank.")
    return api_key.strip()


def validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise MinerUConfigurationError("MinerU base_url must not be empty.")
    value = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # 触发非法端口校验
        hostname = parsed.hostname
    except ValueError as exc:
        raise MinerUConfigurationError("MinerU base_url is not a valid URL.") from exc
    if parsed.scheme.lower() not in _HTTP_SCHEMES or not hostname:
        raise MinerUConfigurationError(
            "MinerU base_url must be an absolute http(s) URL."
        )
    if parsed.query or parsed.fragment:
        raise MinerUConfigurationError(
            "MinerU base_url must not contain a query or fragment."
        )
    if any(
        ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in hostname
    ):
        raise MinerUConfigurationError("MinerU base_url contains an invalid host.")
    return value


def validate_request_timeout(
    value: float | tuple[float, float],
) -> float | tuple[float, float]:
    if isinstance(value, bool):
        raise MinerUConfigurationError("request_timeout must be positive.")
    if isinstance(value, (int, float)):
        if not is_finite_number(value) or value <= 0:
            raise MinerUConfigurationError("request_timeout must be positive.")
        return float(value)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        connect, read = value
        for item in (connect, read):
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not is_finite_number(item)
                or item <= 0
            ):
                raise MinerUConfigurationError(
                    "request_timeout tuple values must both be positive."
                )
        return (float(connect), float(read))
    raise MinerUConfigurationError(
        "request_timeout must be a positive number or a (connect, read) tuple."
    )


def validate_positive(value: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not is_finite_number(value)
    ):
        raise MinerUConfigurationError(f"{name} must be a positive number.")
    if value <= 0:
        raise MinerUConfigurationError(f"{name} must be a positive number.")
    return float(value)


def validate_non_negative(value: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not is_finite_number(value)
    ):
        raise MinerUConfigurationError(f"{name} must be zero or positive.")
    if value < 0:
        raise MinerUConfigurationError(f"{name} must be zero or positive.")
    return float(value)


def validate_max_errors(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MinerUConfigurationError(
            "max_consecutive_errors must be an integer >= 1."
        )
    return value


def validate_task_id(provider_task_id: str) -> str:
    if not isinstance(provider_task_id, str) or not provider_task_id.strip():
        raise MinerUConfigurationError("provider_task_id must be a non-empty string.")
    return provider_task_id.strip()


def validate_deadline_epoch(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not is_finite_number(value)
    ):
        raise MinerUConfigurationError("deadline_epoch must be a finite number.")
    return float(value)


def validate_data_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MinerUConfigurationError("data_id must not be blank.")
    value = value.strip()
    if len(value) > 128:
        raise MinerUConfigurationError("data_id must be at most 128 characters.")
    return value


__all__ = [
    "is_absolute_http_url",
    "is_finite_number",
    "validate_api_key",
    "validate_base_url",
    "validate_data_id",
    "validate_deadline_epoch",
    "validate_max_errors",
    "validate_non_negative",
    "validate_positive",
    "validate_request_timeout",
    "validate_task_id",
]
