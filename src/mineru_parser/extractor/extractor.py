"""``extract_result`` 编排：ZIP 内存流 → ``{pages, images}``。"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from typing import Any, BinaryIO

from .._telemetry import MetricHook, Telemetry
from ._manifest import decode_manifest, validate_manifest
from ._members import (
    collect_images,
    discover_manifest,
    log_context_path,
    member_count_bound,
    read_member,
)
from .errors import (
    ResultExtractionArchiveError,
    ResultExtractionConfigurationError,
    ResultExtractionError,
    ResultExtractionLimitError,
    ResultExtractionManifestError,
    ResultExtractionValidationError,
)
from .limits import DEFAULT_EXTRACTION_LIMITS, ExtractionLimits
from .models import ExtractedResult

_OUTCOME_BY_ERROR = {
    ResultExtractionConfigurationError: "config_error",
    ResultExtractionLimitError: "limit_error",
    ResultExtractionValidationError: "validation_error",
    ResultExtractionManifestError: "manifest_error",
    ResultExtractionArchiveError: "archive_error",
}


def extract_result(
    stream: BinaryIO,
    *,
    limits: ExtractionLimits | None = None,
    on_metric: MetricHook | None = None,
    correlation_id: str | None = None,
) -> ExtractedResult:
    """把 ZIP 内存流确定性地解析为 ``{"pages", "images"}``。

    不下载、不重试、不落盘、不解码图片；不关闭调用方流，成功与已处理的失败
    路径都会恢复游标。
    """
    # 阶段 1：hooks 在 Telemetry 构造前校验；这两个参数非法时无法上报指标。
    if on_metric is not None and not callable(on_metric):
        raise ResultExtractionConfigurationError("on_metric")
    if correlation_id is not None and not isinstance(correlation_id, str):
        raise ResultExtractionConfigurationError("correlation_id")
    telemetry = Telemetry(on_metric=on_metric, correlation_id=correlation_id)

    started = time.perf_counter()
    outcome = "unexpected"
    failure: ResultExtractionError | None = None
    position: int | None = None
    pages_count = 0
    images_count = 0
    image_bytes = 0
    manifest_path: str | None = None

    try:
        # 阶段 2 / 3：limits 与流能力在读取 ZIP 前校验。
        resolved_limits = _resolve_limits(limits)
        position = _validate_stream(stream)

        # 阶段 4：成员数前置预检（构造 ZipFile 之前）。
        bound = member_count_bound(stream)
        if bound is not None and bound > resolved_limits.max_members:
            raise ResultExtractionLimitError(
                "member_count",
                limit=resolved_limits.max_members,
                actual=bound,
            )

        # 阶段 5：只读打开归档。
        try:
            archive = zipfile.ZipFile(stream, "r")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ResultExtractionArchiveError("invalid_zip") from exc

        with archive:
            # 阶段 6：中央目录条目数后置复核（权威兜底）。
            member_count = len(archive.infolist())
            if member_count > resolved_limits.max_members:
                raise ResultExtractionLimitError(
                    "member_count",
                    limit=resolved_limits.max_members,
                    actual=member_count,
                )

            # 阶段 7 / 8：发现并读取唯一顶层 manifest。
            manifest_path, manifest_info = discover_manifest(archive)
            manifest_bytes = read_member(
                archive,
                manifest_info,
                limit=resolved_limits.max_manifest_bytes,
                resource="manifest",
                member=manifest_path,
            )

            # 阶段 9：UTF-8 解码与 Schema 校验。
            manifest_text = decode_manifest(manifest_bytes, manifest_path)
            pages = validate_manifest(manifest_text, manifest_path)

            # 阶段 10：图片发现、去重、排序与声明总量预检。
            image_entries = collect_images(archive, resolved_limits)

            # 阶段 11：逐张有界读取。
            images: list[dict[str, Any]] = []
            total_image_bytes = 0
            for path, info in image_entries:
                data = read_member(
                    archive,
                    info,
                    limit=resolved_limits.max_image_bytes,
                    resource="image",
                    member=path,
                )
                total_image_bytes += len(data)
                if total_image_bytes > resolved_limits.max_total_image_bytes:
                    raise ResultExtractionLimitError(
                        "total_image_bytes",
                        limit=resolved_limits.max_total_image_bytes,
                        actual=total_image_bytes,
                        member=path,
                    )
                images.append({"path": path, "bytes": data})

        # 阶段 12：只有全部成功后才构造结果。
        result: ExtractedResult = {"pages": pages, "images": images}
        pages_count = len(pages)
        images_count = len(images)
        image_bytes = total_image_bytes
        outcome = "success"

        telemetry.log(
            "mineru.extract",
            manifest=log_context_path(manifest_path),
            pages=pages_count,
            images=images_count,
            image_bytes=image_bytes,
            duration_ms=_elapsed_ms(started),
            outcome=outcome,
        )
        return result

    except ResultExtractionError as exc:
        failure = exc
        outcome = _outcome_for(exc)
        telemetry.log(
            "mineru.extract.error",
            level=logging.ERROR,
            error_type=type(exc).__name__,
            outcome=outcome,
            **_error_log_fields(exc),
        )
        raise
    except Exception as exc:
        # 未知异常原样抛出；MemoryError / KeyboardInterrupt / SystemExit 不在此列。
        outcome = "unexpected"
        telemetry.log(
            "mineru.extract.error",
            level=logging.ERROR,
            error_type=type(exc).__name__,
            outcome=outcome,
        )
        raise
    finally:
        # 阶段 13：恢复游标（失败只告警），随后恰好上报一次指标。
        if position is not None:
            try:
                _restore_stream(stream, position)
            except MemoryError:
                raise
            except Exception as exc:  # noqa: BLE001 - 恢复失败不覆盖主结果
                telemetry.log(
                    "mineru.extract.restore_failed",
                    level=logging.WARNING,
                    error_type=type(exc).__name__,
                )
        _emit_metrics(
            telemetry,
            outcome=outcome,
            failure=failure,
            duration_ms=_elapsed_ms(started),
            pages=pages_count,
            images=images_count,
            image_bytes=image_bytes,
        )


def _resolve_limits(limits: ExtractionLimits | None) -> ExtractionLimits:
    if limits is None:
        return DEFAULT_EXTRACTION_LIMITS
    if not isinstance(limits, ExtractionLimits):
        raise ResultExtractionConfigurationError("limits")
    return limits


def _validate_stream(stream: BinaryIO) -> int:
    """校验二进制性、可读、可 seek，并返回起始游标。"""
    if isinstance(stream, io.TextIOBase):
        raise ResultExtractionConfigurationError("stream")
    if not all(
        callable(getattr(stream, name, None)) for name in ("read", "seek", "tell")
    ):
        raise ResultExtractionConfigurationError("stream")

    try:
        readable = getattr(stream, "readable", None)
        if callable(readable) and not readable():
            raise ResultExtractionConfigurationError("stream")
        seekable = getattr(stream, "seekable", None)
        if callable(seekable) and not seekable():
            raise ResultExtractionConfigurationError("stream")
    except ResultExtractionConfigurationError:
        raise
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - 能力探测失败视为不可用
        raise ResultExtractionConfigurationError("stream") from exc

    try:
        position = stream.tell()
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - 游标不可读
        raise ResultExtractionConfigurationError("stream") from exc
    if not isinstance(position, int) or isinstance(position, bool):
        raise ResultExtractionConfigurationError("stream")
    return position


def _restore_stream(stream: BinaryIO, position: int) -> None:
    stream.seek(position)


def _outcome_for(exc: ResultExtractionError) -> str:
    for error_type, outcome in _OUTCOME_BY_ERROR.items():
        if isinstance(exc, error_type):
            return outcome
    return "unexpected"


def _error_log_fields(exc: ResultExtractionError) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    reason = getattr(exc, "reason", None)
    if reason is not None:
        fields["reason"] = reason
    resource = getattr(exc, "resource", None)
    if resource is not None:
        fields["resource"] = resource
    category = getattr(exc, "category", None)
    if category is not None:
        fields["category"] = category
    member = getattr(exc, "member", None)
    if member is not None:
        fields["member"] = log_context_path(member)
    manifest_path = getattr(exc, "manifest_path", None)
    if manifest_path is not None:
        fields["manifest_path"] = log_context_path(manifest_path)
    return fields


def _metric_tags(
    outcome: str,
    failure: ResultExtractionError | None,
) -> dict[str, str]:
    tags = {"outcome": outcome}
    if failure is None:
        return tags
    if isinstance(failure, (ResultExtractionArchiveError, ResultExtractionManifestError)):
        tags["reason"] = failure.reason
    elif isinstance(failure, ResultExtractionLimitError):
        tags["resource"] = failure.resource
    elif isinstance(failure, ResultExtractionValidationError):
        tags["category"] = failure.category
    return tags


def _emit_metrics(
    telemetry: Telemetry,
    *,
    outcome: str,
    failure: ResultExtractionError | None,
    duration_ms: float,
    pages: int,
    images: int,
    image_bytes: int,
) -> None:
    tags = _metric_tags(outcome, failure)
    telemetry.metric("mineru.extract.total", 1, tags)
    telemetry.metric("mineru.extract.duration_ms", duration_ms, tags)
    telemetry.metric("mineru.extract.pages", pages, tags)
    telemetry.metric("mineru.extract.images", images, tags)
    telemetry.metric("mineru.extract.image_bytes", image_bytes, tags)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


__all__ = ["extract_result"]
