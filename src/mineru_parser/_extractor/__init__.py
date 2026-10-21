"""结果包提取器（内部实现，不对外）。

本包是 SPEC-003 的私有实现，仅由 :mod:`mineru_parser.pipeline` 内部使用；
不提供公开导入路径，也不遵循 SemVer。行为契约见 SPEC-003。
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
