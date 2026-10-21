"""日志与指标的统一出口。

指标回调失败不得影响主流程；``client`` 与 ``downloader`` 共用本模块。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

_logger = logging.getLogger("mineru_parser")

MetricHook = Callable[[str, float, Mapping[str, str]], None]


class Telemetry:
    def __init__(
        self,
        *,
        on_metric: MetricHook | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._on_metric = on_metric
        self._correlation_id = correlation_id

    def log(self, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
        extra = {key: value for key, value in fields.items() if value is not None}
        if self._correlation_id is not None:
            extra["correlation_id"] = self._correlation_id
        _logger.log(level, event, extra=extra)

    def metric(
        self,
        name: str,
        value: float,
        tags: Mapping[str, str] | None = None,
    ) -> None:
        if self._on_metric is None:
            return
        try:
            self._on_metric(name, float(value), dict(tags or {}))
        except Exception as exc:  # noqa: BLE001 - 指标失败不影响主流程
            self.log(
                "mineru.metric.failed",
                level=logging.WARNING,
                metric_name=name,
                error_type=type(exc).__name__,
            )


__all__ = ["MetricHook", "Telemetry"]
