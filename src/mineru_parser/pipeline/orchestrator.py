"""四阶段编排器：submit → wait → download → extract。

这是 SPEC-004 的唯一实现入口。公共 ``parse()`` 是它的薄包装；组件工厂、
提取函数与单调时钟都可以从**内部**构造参数注入（测试缝，AC-7.8），但不会
出现在公共签名中。

控制流契约（SPEC-004 §3.4）：

- 参数校验先于组件创建，预算检查先于每个阶段；
- 除超时翻译外，阶段异常只观察不介入；
- 默认把已知异常封装为状态信封，兜不住的异常原样抛出；
- 自建组件与中间 ZIP 流由本模块按"流 → downloader → client"关闭。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .._client.api import MinerUApiClient
from .._client.errors import MinerUTimeoutError
from .._client.models import MinerUTaskStatus
from .._downloader.downloader import ResultDownloader
from .._downloader.errors import ResultDownloadTimeoutError
from .._extractor.extractor import extract_result
from .._extractor.limits import ExtractionLimits
from .._extractor.models import ExtractedResult
from .._telemetry import MetricHook, Telemetry
from ..errors import MinerUParserError
from .budget import Budget
from .errors import PipelineConfigurationError, PipelineTimeoutError
from .result import ErrorMessage, ParseResult
from .stages import PipelineStage

# ``outcome`` 是封闭枚举，只允许这五个取值（SPEC-004 §3.4）。
_OUTCOME_SUCCESS = "success"
_OUTCOME_CONFIG_ERROR = "config_error"
_OUTCOME_TIMEOUT = "timeout"
_OUTCOME_STAGE_ERROR = "stage_error"
_OUTCOME_UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class _StageRecord:
    stage: PipelineStage
    duration_ms: float
    outcome: str


def _default_client_factory(
    *,
    on_metric: MetricHook | None,
    correlation_id: str | None,
) -> MinerUApiClient:
    return MinerUApiClient(on_metric=on_metric, correlation_id=correlation_id)


def _default_downloader_factory(
    *,
    on_metric: MetricHook | None,
    correlation_id: str | None,
) -> ResultDownloader:
    return ResultDownloader(on_metric=on_metric, correlation_id=correlation_id)


def _cause_type(exc: BaseException) -> str | None:
    """返回异常链首因的类名；链上没有其他异常时返回 ``None``。

    只看类型，不读取消息——消息可能含签名 URL 或文档正文。
    """
    seen: set[int] = set()
    cause: BaseException | None = None
    current: BaseException = exc
    while True:
        if current.__cause__ is not None:
            nxt = current.__cause__
        elif current.__suppress_context__:
            nxt = None
        else:
            nxt = current.__context__
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(nxt))
        cause = nxt
        current = nxt
    return type(cause).__name__ if cause is not None else None


def _sanitized_message(
    stage: PipelineStage,
    error_type: str,
    exc: BaseException,
) -> str:
    """构造脱敏后的可读摘要：不含异常原文、凭据、URL 或文档正文。"""
    if error_type == "PipelineConfigurationError":
        field = getattr(exc, "field", None)
        if field is not None:
            return f"invalid pipeline configuration: {field}."
        return "invalid pipeline configuration."
    if error_type == "PipelineTimeoutError":
        return f"pipeline budget exhausted during the '{stage.value}' stage."
    return f"{error_type} raised during the {stage.value} stage."


class PipelineOrchestrator:
    """无状态编排器：每次调用只使用局部变量与注入的构造器。"""

    __slots__ = (
        "_client_factory",
        "_downloader_factory",
        "_extract",
        "_monotonic",
        "_wall_clock",
    )

    def __init__(
        self,
        *,
        client_factory: Callable[..., Any] | None = None,
        downloader_factory: Callable[..., Any] | None = None,
        extract: Callable[..., ExtractedResult] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._client_factory = (
            _default_client_factory if client_factory is None else client_factory
        )
        self._downloader_factory = (
            _default_downloader_factory
            if downloader_factory is None
            else downloader_factory
        )
        self._extract = extract_result if extract is None else extract
        self._monotonic = monotonic
        self._wall_clock = wall_clock

    # --- 编排 -------------------------------------------------------------

    def run(
        self,
        uri: str,
        *,
        model_version: str = "vlm",
        data_id: str | None = None,
        timeout: float | None = None,
        deadline_epoch: float | None = None,
        limits: ExtractionLimits | None = None,
        raise_on_error: bool = False,
        on_update: Callable[[MinerUTaskStatus], None] | None = None,
        on_error: Callable[[PipelineStage, BaseException], None] | None = None,
        on_metric: MetricHook | None = None,
        correlation_id: str | None = None,
    ) -> ParseResult:
        """执行一次完整流水线；失败语义由 ``raise_on_error`` 决定。"""
        telemetry = Telemetry(
            on_metric=on_metric if callable(on_metric) else None,
            correlation_id=correlation_id if isinstance(correlation_id, str) else None,
        )
        raise_mode = bool(raise_on_error)
        started = self._monotonic()

        stage = PipelineStage.CONFIG
        stage_started = started
        records: list[_StageRecord] = []
        recorded: set[PipelineStage] = set()

        task_id: str | None = None
        current_data_id = data_id if isinstance(data_id, str) else None
        zip_url: str | None = None
        pages_count = 0
        images_count = 0
        image_bytes = 0

        outcome = _OUTCOME_UNEXPECTED
        final_stage = PipelineStage.CONFIG
        failure: BaseException | None = None
        failure_type: str | None = None

        client: Any = None
        downloader: Any = None
        stream: Any = None

        def finish_stage(which: PipelineStage, stage_outcome: str) -> None:
            if which in recorded:
                return
            duration_ms = (self._monotonic() - stage_started) * 1000.0
            recorded.add(which)
            records.append(_StageRecord(which, duration_ms, stage_outcome))
            telemetry.log(
                "mineru.pipeline.stage",
                stage=which.value,
                duration_ms=duration_ms,
                outcome=stage_outcome,
            )

        def notify_error(which: PipelineStage, exc: BaseException) -> None:
            if not callable(on_error):
                return
            try:
                on_error(which, exc)
            except BaseException as callback_exc:  # noqa: BLE001 - 回调失败不中断主流程
                # AC-5.5：on_error 抛出的任何异常都必须被吞掉；否则它会
                # 覆盖原始阶段异常，使失败归因丢失。
                telemetry.log(
                    "mineru.pipeline.on_error.failed",
                    level=logging.WARNING,
                    stage=which.value,
                    error_type=type(callback_exc).__name__,
                )

        def close_component(component: Any, name: str) -> None:
            """关闭自建资源；清理失败只告警，不改变本次调用的结果。

            ``close()`` 不在任何执行阶段内，其异常没有可归因的 ``stage``；
            若让它逃逸，会在信封模式下破坏 AC-1.11 的"已知异常不抛出"，
            并让遥测 outcome 与实际结果不一致。``BaseException``（如
            ``KeyboardInterrupt``）仍按兜不住异常处理，原样传播。
            """
            if component is None:
                return
            try:
                component.close()
            except Exception as exc:  # noqa: BLE001 - 清理失败不改变主结果
                telemetry.log(
                    "mineru.pipeline.close.failed",
                    level=logging.WARNING,
                    component=name,
                    error_type=type(exc).__name__,
                    exc_info=exc,
                )

        def failed_result(
            which: PipelineStage,
            exc: BaseException,
            *,
            error_type: str | None = None,
            cause_type: str | None = None,
        ) -> ParseResult:
            effective_type = type(exc).__name__ if error_type is None else error_type
            error: ErrorMessage = {
                "stage": which,
                "error_type": effective_type,
                "message": _sanitized_message(which, effective_type, exc),
                "cause_type": (
                    _cause_type(exc) if cause_type is None else cause_type
                ),
            }
            return {
                "status": "failed",
                "data": None,
                "task_id": task_id,
                "data_id": current_data_id,
                "zip_url": zip_url,
                "error": error,
            }

        try:
            # --- 1. 参数校验（不创建任何组件） ---------------------------
            self._validate(
                uri=uri,
                on_update=on_update,
                on_error=on_error,
                on_metric=on_metric,
                correlation_id=correlation_id,
                limits=limits,
            )
            budget = Budget.from_parameters(
                timeout=timeout,
                deadline_epoch=deadline_epoch,
                monotonic=self._monotonic,
                wall_clock=self._wall_clock,
            )

            # --- 2. submit ------------------------------------------------
            stage = PipelineStage.SUBMIT
            stage_started = self._monotonic()
            budget.check(stage, task_id=task_id)
            client = self._client_factory(
                on_metric=on_metric, correlation_id=correlation_id
            )
            downloader = self._downloader_factory(
                on_metric=on_metric, correlation_id=correlation_id
            )
            handle = client.submit(
                uri, model_version=model_version, data_id=data_id
            )
            task_id = handle.task_id or None
            current_data_id = handle.data_id or current_data_id
            finish_stage(stage, _OUTCOME_SUCCESS)

            # --- 3. wait --------------------------------------------------
            stage = PipelineStage.WAIT
            stage_started = self._monotonic()
            budget.check(stage, task_id=task_id)
            task_result = handle.wait(
                timeout=budget.remaining(), on_update=on_update
            )
            task_id = task_result.provider_task_id
            current_data_id = task_result.data_id
            zip_url = task_result.zip_url
            finish_stage(stage, _OUTCOME_SUCCESS)

            # --- 4. download ----------------------------------------------
            stage = PipelineStage.DOWNLOAD
            stage_started = self._monotonic()
            budget.check(stage, task_id=task_id)
            stream = downloader.resolve(zip_url)
            # resolve() 不接受每次调用预算：只能在阶段结束后检出（AC-4.7）。
            budget.check(stage, task_id=task_id)
            finish_stage(stage, _OUTCOME_SUCCESS)

            # --- 5. extract -----------------------------------------------
            stage = PipelineStage.EXTRACT
            stage_started = self._monotonic()
            budget.check(stage, task_id=task_id)
            try:
                data = self._extract(
                    stream,
                    limits=limits,
                    on_metric=on_metric,
                    correlation_id=correlation_id,
                )
            finally:
                # 提取结束（成功或失败）立即关闭中间 ZIP 流（AC-3.3 / AC-3.8）。
                try:
                    close_component(stream, "stream")
                finally:
                    stream = None
            # 提取不可中断：预算只能在提取结束后检查（AC-4.6）。
            budget.check(stage, task_id=task_id)
            pages_count = len(data["pages"])
            images_count = len(data["images"])
            image_bytes = sum(len(image["bytes"]) for image in data["images"])
            finish_stage(stage, _OUTCOME_SUCCESS)

            outcome = _OUTCOME_SUCCESS
            final_stage = PipelineStage.EXTRACT
            return {
                "status": "success",
                "data": data,
                "task_id": task_id,
                "data_id": current_data_id,
                "zip_url": zip_url,
                "error": None,
            }

        except BaseException as exc:
            failure = exc

            if isinstance(exc, PipelineTimeoutError):
                # 预算检查点耗尽：stage 已由抛出点标注。
                outcome = _OUTCOME_TIMEOUT
                final_stage = exc.stage
                failure_type = type(exc).__name__
                notify_error(exc.stage, exc)
                finish_stage(exc.stage, _OUTCOME_TIMEOUT)
                if raise_mode:
                    raise
                return failed_result(final_stage, exc)

            if isinstance(exc, PipelineConfigurationError):
                outcome = _OUTCOME_CONFIG_ERROR
                final_stage = PipelineStage.CONFIG
                failure_type = type(exc).__name__
                notify_error(PipelineStage.CONFIG, exc)
                finish_stage(PipelineStage.CONFIG, _OUTCOME_CONFIG_ERROR)
                if raise_mode:
                    raise
                return failed_result(PipelineStage.CONFIG, exc)

            if isinstance(exc, MinerUTimeoutError) and stage is PipelineStage.WAIT:
                outcome = _OUTCOME_TIMEOUT
                final_stage = PipelineStage.WAIT
                failure_type = "PipelineTimeoutError"
                notify_error(PipelineStage.WAIT, exc)
                finish_stage(PipelineStage.WAIT, _OUTCOME_TIMEOUT)
                translated = PipelineTimeoutError(
                    "Pipeline budget exceeded during the 'wait' stage.",
                    stage=PipelineStage.WAIT,
                    task_id=exc.task_id or task_id,
                    last_status=exc.last_status,
                )
                if raise_mode:
                    raise translated from exc
                return failed_result(
                    PipelineStage.WAIT,
                    exc,
                    error_type="PipelineTimeoutError",
                    cause_type=type(exc).__name__,
                )

            if (
                isinstance(exc, ResultDownloadTimeoutError)
                and stage is PipelineStage.DOWNLOAD
            ):
                outcome = _OUTCOME_TIMEOUT
                final_stage = PipelineStage.DOWNLOAD
                failure_type = "PipelineTimeoutError"
                notify_error(PipelineStage.DOWNLOAD, exc)
                finish_stage(PipelineStage.DOWNLOAD, _OUTCOME_TIMEOUT)
                translated = PipelineTimeoutError(
                    "Pipeline budget exceeded during the 'download' stage.",
                    stage=PipelineStage.DOWNLOAD,
                    task_id=task_id,
                )
                if raise_mode:
                    raise translated from exc
                return failed_result(
                    PipelineStage.DOWNLOAD,
                    exc,
                    error_type="PipelineTimeoutError",
                    cause_type=type(exc).__name__,
                )

            if isinstance(exc, MinerUParserError):
                # 已知的非超时失败：异常模式下原样抛出（同一对象）。
                outcome = _OUTCOME_STAGE_ERROR
                final_stage = stage
                failure_type = type(exc).__name__
                notify_error(stage, exc)
                finish_stage(stage, _OUTCOME_STAGE_ERROR)
                if raise_mode:
                    raise
                return failed_result(stage, exc)

            # 兜不住：未知类型 / MemoryError / KeyboardInterrupt / SystemExit。
            outcome = _OUTCOME_UNEXPECTED
            final_stage = stage
            failure_type = type(exc).__name__
            notify_error(stage, exc)
            finish_stage(stage, _OUTCOME_UNEXPECTED)
            raise

        finally:
            try:
                # 关闭顺序：中间流 → downloader → client（AC-3.8）。
                # 嵌套 finally 保证前一个关闭失败时后续关闭仍会执行。
                try:
                    close_component(stream, "stream")
                finally:
                    stream = None
                    try:
                        close_component(downloader, "downloader")
                    finally:
                        close_component(client, "client")
            finally:
                # 遥测放在内层 finally：即使关闭失败也恰好上报一次（AC-5.7）。
                duration_ms = (self._monotonic() - started) * 1000.0
                if outcome == _OUTCOME_SUCCESS:
                    telemetry.log(
                        "mineru.pipeline",
                        duration_ms=duration_ms,
                        outcome=outcome,
                        task_id=task_id,
                        data_id=current_data_id,
                        stage_durations_ms={
                            record.stage.value: record.duration_ms
                            for record in records
                        },
                    )
                else:
                    level = (
                        logging.ERROR
                        if outcome == _OUTCOME_UNEXPECTED
                        else logging.WARNING
                    )
                    telemetry.log(
                        "mineru.pipeline.error",
                        level=level,
                        stage=final_stage.value,
                        error_type=failure_type,
                        duration_ms=duration_ms,
                        outcome=outcome,
                        exc_info=failure if failure is not None else False,
                    )

                # 管道自身的指标在 finally 中恰好上报一次（AC-5.7）。
                telemetry.metric(
                    "mineru.pipeline.total",
                    1,
                    {"outcome": outcome, "stage": final_stage.value},
                )
                telemetry.metric(
                    "mineru.pipeline.duration_ms",
                    duration_ms,
                    {"outcome": outcome},
                )
                for record in records:
                    telemetry.metric(
                        "mineru.pipeline.stage.duration_ms",
                        record.duration_ms,
                        {"stage": record.stage.value, "outcome": record.outcome},
                    )
                # 失败时三项产物计数必须为 0；计数只在全部检查通过后才赋值。
                telemetry.metric(
                    "mineru.pipeline.pages", pages_count, {"outcome": outcome}
                )
                telemetry.metric(
                    "mineru.pipeline.images", images_count, {"outcome": outcome}
                )
                telemetry.metric(
                    "mineru.pipeline.image_bytes",
                    image_bytes,
                    {"outcome": outcome},
                )

    # --- 参数校验 ---------------------------------------------------------

    @staticmethod
    def _validate(
        *,
        uri: object,
        on_update: object,
        on_error: object,
        on_metric: object,
        correlation_id: object,
        limits: object,
    ) -> None:
        """校验非预算类参数；必须早于任何组件创建（AC-4.1 / AC-6.4）。"""
        if not isinstance(uri, str) or not uri.strip():
            raise PipelineConfigurationError(
                "uri must be a non-empty string.", field="uri"
            )
        if on_update is not None and not callable(on_update):
            raise PipelineConfigurationError(
                "on_update must be callable.", field="on_update"
            )
        if on_error is not None and not callable(on_error):
            raise PipelineConfigurationError(
                "on_error must be callable.", field="on_error"
            )
        if on_metric is not None and not callable(on_metric):
            raise PipelineConfigurationError(
                "on_metric must be callable.", field="on_metric"
            )
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise PipelineConfigurationError(
                "correlation_id must be a string or None.",
                field="correlation_id",
            )
        if limits is not None and not isinstance(limits, ExtractionLimits):
            raise PipelineConfigurationError(
                "limits must be an ExtractionLimits instance or None.",
                field="limits",
            )


def parse(
    uri: str,
    *,
    model_version: str = "vlm",
    data_id: str | None = None,
    timeout: float | None = None,
    deadline_epoch: float | None = None,
    limits: ExtractionLimits | None = None,
    raise_on_error: bool = False,
    on_update: Callable[[MinerUTaskStatus], None] | None = None,
    on_error: Callable[[PipelineStage, BaseException], None] | None = None,
    on_metric: MetricHook | None = None,
    correlation_id: str | None = None,
) -> ParseResult:
    """一次调用完成"提交 → 等待 → 下载 → 解析"。

    默认（``raise_on_error=False``）不抛异常：已知失败被封装为
    ``status="failed"`` 的状态信封；未知异常与 ``MemoryError`` /
    ``KeyboardInterrupt`` / ``SystemExit`` 原样抛出。
    """
    return PipelineOrchestrator().run(
        uri,
        model_version=model_version,
        data_id=data_id,
        timeout=timeout,
        deadline_epoch=deadline_epoch,
        limits=limits,
        raise_on_error=raise_on_error,
        on_update=on_update,
        on_error=on_error,
        on_metric=on_metric,
        correlation_id=correlation_id,
    )


__all__ = ["PipelineOrchestrator", "parse"]
