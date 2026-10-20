"""MinerU 的 wire 模型、领域模型与状态归一化。

wire 模型只负责描述 HTTP 载荷；领域模型（``MinerUTaskStatus`` /
``MinerUTaskResult``）不依赖 Pydantic，供调用方长期持有。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._validation import is_absolute_http_url, validate_data_id
from .errors import (
    MinerUConfigurationError,
    MinerUExecutionError,
    MinerUTransientError,
)

# --- wire 模型 ------------------------------------------------------------


class ExtractionRequest(BaseModel):
    """``POST /extract/task`` 的请求体。"""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    uri: str = Field(serialization_alias="url")
    model_version: str = "vlm"
    data_id: str | None = None

    @field_validator("uri")
    @classmethod
    def _validate_uri(cls, value: str) -> str:
        if not is_absolute_http_url(value):
            raise ValueError("uri must be an absolute http(s) URL.")
        return value.strip()

    @field_validator("model_version")
    @classmethod
    def _validate_model_version(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("model_version must not be blank.")
        return value.strip()

    @field_validator("data_id")
    @classmethod
    def _validate_data_id(cls, value: str | None) -> str | None:
        try:
            return validate_data_id(value)
        except MinerUConfigurationError as exc:
            raise ValueError(str(exc)) from exc

    def payload(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=True)


class ExtractProgress(BaseModel):
    extracted_pages: int | None = None
    total_pages: int | None = None


class ExtractionTaskDetail(BaseModel):
    task_id: str | None = None
    state: str | None = None
    err_msg: str | None = None
    full_zip_url: str | None = None
    data_id: str | None = None
    extract_progress: ExtractProgress | None = None


class SubmitData(BaseModel):
    task_id: str | None = None


class ApiEnvelope[T](BaseModel):
    """官方标准信封与网关错误信封的统一视图。

    标准成功响应是 ``{"code": 0, "data": {...}}``；认证/网关失败可能是
    ``{"success": false, "msgCode": "A0202", "msg": "..."}``。两者都在
    错误码表里有对应条目。
    """

    model_config = ConfigDict(populate_by_name=True)

    code: int | str | None = None
    msg: str | None = None
    trace_id: str | None = None
    data: T | None = None
    success: bool | None = None
    msg_code: str | None = Field(default=None, alias="msgCode")

    @property
    def resolved_code(self) -> int | str | None:
        if self.code is not None:
            return self.code
        return self.msg_code


# --- 领域模型 -------------------------------------------------------------


class MinerUTaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            MinerUTaskState.SUCCEEDED,
            MinerUTaskState.FAILED,
            MinerUTaskState.CANCELED,
        )


@dataclass(frozen=True, slots=True)
class MinerUProgress:
    extracted_pages: int | None = None
    total_pages: int | None = None


@dataclass(frozen=True, slots=True)
class MinerUTaskStatus:
    state: MinerUTaskState
    raw_state: str
    task_id: str
    data_id: str | None = None
    err_msg: str | None = None
    full_zip_url: str | None = None
    progress: MinerUProgress | None = None


@dataclass(frozen=True, slots=True)
class MinerUTaskResult:
    zip_url: str
    provider_task_id: str
    data_id: str | None = None


# --- 归一化 ---------------------------------------------------------------

_STATE_MAP: dict[str, MinerUTaskState] = {
    "pending": MinerUTaskState.PENDING,
    "running": MinerUTaskState.RUNNING,
    "converting": MinerUTaskState.RUNNING,
    "done": MinerUTaskState.SUCCEEDED,
    "failed": MinerUTaskState.FAILED,
    "cancelled": MinerUTaskState.CANCELED,
    "canceled": MinerUTaskState.CANCELED,
}


def _normalize_progress(
    detail: ExtractionTaskDetail,
) -> MinerUProgress | None:
    progress = detail.extract_progress
    if progress is None:
        return None
    return MinerUProgress(
        extracted_pages=progress.extracted_pages,
        total_pages=progress.total_pages,
    )


def normalize_status(
    provider_task_id: str,
    detail: ExtractionTaskDetail,
) -> MinerUTaskStatus:
    """把 wire 状态映射为领域状态。

    未知状态按瞬态处理（可能是协议新增状态）；done 但缺少下载地址属于
    协议违约，直接按执行错误处理。
    """
    raw_state = (detail.state or "").strip()
    normalized = _STATE_MAP.get(raw_state.lower())
    if normalized is None:
        raise MinerUTransientError(f"Unexpected MinerU task state: {detail.state!r}")

    zip_url = (detail.full_zip_url or "").strip()
    if normalized is MinerUTaskState.SUCCEEDED and not zip_url:
        raise MinerUExecutionError(
            f"MinerU task {provider_task_id} completed without full_zip_url."
        )

    return MinerUTaskStatus(
        state=normalized,
        raw_state=raw_state,
        task_id=detail.task_id or provider_task_id,
        data_id=detail.data_id,
        err_msg=detail.err_msg or None,
        full_zip_url=zip_url or None,
        progress=_normalize_progress(detail),
    )


__all__ = [
    "ApiEnvelope",
    "ExtractProgress",
    "ExtractionRequest",
    "ExtractionTaskDetail",
    "MinerUProgress",
    "MinerUTaskResult",
    "MinerUTaskState",
    "MinerUTaskStatus",
    "SubmitData",
    "normalize_status",
]
