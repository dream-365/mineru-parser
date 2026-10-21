"""结果包提取器。

公共 API 由 :mod:`mineru_parser` 顶层统一再导出；这里同样支持
``from mineru_parser.extractor import ...`` 的直接导入。
"""

from __future__ import annotations

from .._telemetry import MetricHook
from ._members import canonicalize_member_path
from .errors import (
    ResultExtractionArchiveError,
    ResultExtractionConfigurationError,
    ResultExtractionError,
    ResultExtractionLimitError,
    ResultExtractionManifestError,
    ResultExtractionValidationError,
)
from .extractor import extract_result
from .limits import DEFAULT_EXTRACTION_LIMITS, ExtractionLimits
from .models import ExtractedImage, ExtractionIssue, ExtractedResult

__all__ = [
    "DEFAULT_EXTRACTION_LIMITS",
    "ExtractedImage",
    "ExtractedResult",
    "ExtractionIssue",
    "ExtractionLimits",
    "MetricHook",
    "ResultExtractionArchiveError",
    "ResultExtractionConfigurationError",
    "ResultExtractionError",
    "ResultExtractionLimitError",
    "ResultExtractionManifestError",
    "ResultExtractionValidationError",
    "canonicalize_member_path",
    "extract_result",
]
