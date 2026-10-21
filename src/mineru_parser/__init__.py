"""MinerU Parser 公共 API。

整个库对外只暴露一个函数 :func:`parse`（SPEC-004 AC-2.1 / AC-2.6）；
其余导出都是 ``parse`` 的签名或返回值所引用的类型、异常类与版本常量。
三个组件（client / downloader / extractor）是私有实现，不提供公开导入路径
（SPEC-004 AC-2.3）。
"""

from __future__ import annotations

from ._client.models import MinerUTaskStatus
from ._extractor.limits import ExtractionLimits
from ._extractor.models import ExtractedImage, ExtractedResult
from ._telemetry import MetricHook
from ._version import __version__
from .errors import MinerUParserError
from .pipeline import parse
from .pipeline.errors import (
    PipelineConfigurationError,
    PipelineError,
    PipelineTimeoutError,
)
from .pipeline.result import ErrorMessage, ParseResult
from .pipeline.stages import PipelineStage

__all__ = [
    "ErrorMessage",
    "ExtractedImage",
    "ExtractedResult",
    "ExtractionLimits",
    "MetricHook",
    "MinerUParserError",
    "MinerUTaskStatus",
    "ParseResult",
    "PipelineConfigurationError",
    "PipelineError",
    "PipelineStage",
    "PipelineTimeoutError",
    "__version__",
    "parse",
]
