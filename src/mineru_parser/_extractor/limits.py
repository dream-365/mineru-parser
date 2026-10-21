"""提取限额：解压后字节数与数量上限。"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ResultExtractionConfigurationError


@dataclass(frozen=True, slots=True)
class ExtractionLimits:
    """不可变的解压后资源上限；构造期校验，拒绝 ``bool`` 与非正整数。"""

    max_manifest_bytes: int = 16 * 1024 * 1024
    max_image_bytes: int = 32 * 1024 * 1024
    max_total_image_bytes: int = 160 * 1024 * 1024
    max_images: int = 10_000
    max_members: int = 100_000

    def __post_init__(self) -> None:
        for field in (
            "max_manifest_bytes",
            "max_image_bytes",
            "max_total_image_bytes",
            "max_images",
            "max_members",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ResultExtractionConfigurationError(field)


DEFAULT_EXTRACTION_LIMITS = ExtractionLimits()

__all__ = ["DEFAULT_EXTRACTION_LIMITS", "ExtractionLimits"]
