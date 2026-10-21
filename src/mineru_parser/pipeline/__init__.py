"""管道实现层（内部，不对外）。

唯一公共入口 ``parse`` 由顶层 :mod:`mineru_parser` 再导出；本包的其余名称
不进入顶层 ``__all__``（AC-2.7 / AC-2.8）。

测试缝（``PipelineOrchestrator`` 的构造参数）只属于内部实现，不是公共契约
（AC-7.8）。
"""

from __future__ import annotations

from .errors import (
    PipelineConfigurationError,
    PipelineError,
    PipelineTimeoutError,
)
from .orchestrator import parse
from .result import ErrorMessage, ParseResult
from .stages import PipelineStage

__all__ = [
    "ErrorMessage",
    "ParseResult",
    "PipelineConfigurationError",
    "PipelineError",
    "PipelineStage",
    "PipelineTimeoutError",
    "parse",
]
