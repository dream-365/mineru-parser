"""MinerU HTTP transport：请求构造、响应解析与错误分类。

这一层只关心 wire 协议与 HTTP 语义，不持有任务状态，也不做轮询。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests
import urllib3

from .._http import parse_retry_after, retry_after_from, status_class
from ._telemetry import Telemetry
from ._time import elapsed_ms
from .errors import (
    MinerUAuthenticationError,
    MinerUError,
    MinerUExecutionError,
    MinerUQuotaError,
    MinerUTransientError,
    classify_business_error,
)
from .models import (
    ApiEnvelope,
    ExtractionRequest,
    ExtractionTaskDetail,
    SubmitData,
)

MINERU_BASE_URL = "https://mineru.net/api/v4"

# NewConnectionError 表示连接尚未建立（DNS 失败、连接拒绝等；urllib3 2.x
# 的 NameResolutionError 是它的子类）：请求确定没有到达 MinerU，可以安全
# 重试。读超时、连接中断等发生在请求可能已被接收之后，必须按终态处理。
_NOT_SENT_ERRORS = (urllib3.exceptions.NewConnectionError,)


def _failed_before_request_sent(exc: BaseException) -> bool:
    """判断提交异常是否确定发生在请求发出之前。"""
    if isinstance(exc, requests.ConnectTimeout):
        return True
    if not isinstance(exc, requests.ConnectionError):
        return False

    for arg in exc.args:
        if isinstance(arg, _NOT_SENT_ERRORS):
            return True
        reason = getattr(arg, "reason", None)
        if isinstance(reason, _NOT_SENT_ERRORS):
            return True
    return False


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _retry_after(response: Any, *, wall_clock: Callable[[], float]) -> float | None:
    return retry_after_from(getattr(response, "headers", None), wall_clock=wall_clock)


class MinerUTransport:
    """``requests`` 之上的薄传输层。"""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float | tuple[float, float],
        session: requests.Session,
        telemetry: Telemetry,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._session = session
        self._telemetry = telemetry
        self._wall_clock = wall_clock

    # --- 公开操作 ---------------------------------------------------------

    def submit(self, request: ExtractionRequest, *, api_key: str) -> str:
        """提交任务，返回 provider task_id。"""
        try:
            payload = self._send(
                "submit",
                "POST",
                "/extract/task",
                api_key=api_key,
                json=request.payload(),
            )
            envelope = ApiEnvelope[SubmitData].model_validate(payload)
        except requests.HTTPError as exc:
            raise self._classify_submit_http_error(exc) from exc
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            raise self._classify_submit_transport_error(exc) from exc

        data = self._ensure_success(
            envelope,
            data_id=request.data_id,
            default_transient=False,
        )
        task_id = (data.task_id or "").strip() if data is not None else ""
        if not task_id:
            raise MinerUExecutionError("MinerU returned an empty task id.")
        return task_id

    def trace(self, provider_task_id: str, *, api_key: str) -> ExtractionTaskDetail:
        """查询一次任务状态，返回 wire 详情。"""
        path = f"/extract/task/{quote(provider_task_id, safe='')}"
        try:
            payload = self._send("trace", "GET", path, api_key=api_key)
            envelope = ApiEnvelope[ExtractionTaskDetail].model_validate(payload)
        except requests.HTTPError as exc:
            raise self._classify_trace_http_error(exc) from exc
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            raise MinerUTransientError(f"MinerU status query failed: {exc}") from exc

        data = self._ensure_success(
            envelope,
            provider_task_id=provider_task_id,
            default_transient=True,
        )
        if data is None:
            raise MinerUTransientError("MinerU status query returned no task data.")
        return data

    # --- HTTP -------------------------------------------------------------

    def _send(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        api_key: str,
        json: dict[str, object] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        started = time.perf_counter()
        try:
            response = self._session.request(
                method,
                url,
                json=json,
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as exc:
            self._emit_http_metric(operation, status_class(_http_status(exc)), started)
            raise
        except (requests.RequestException, ValueError, RuntimeError):
            self._emit_http_metric(operation, "error", started)
            raise
        self._emit_http_metric(operation, "2xx", started)
        return payload

    def _emit_http_metric(
        self, operation: str, status_class: str, started: float
    ) -> None:
        self._telemetry.metric(
            "mineru.http.request.duration_ms",
            elapsed_ms(started),
            {"operation": operation, "status_class": status_class},
        )

    # --- 错误分类 ---------------------------------------------------------

    def _ensure_success(
        self,
        envelope: ApiEnvelope[Any],
        *,
        provider_task_id: str | None = None,
        data_id: str | None = None,
        default_transient: bool,
    ) -> Any:
        code = envelope.resolved_code
        if code is not None:
            ok = str(code) == "0"
        else:
            # 网关信封没有 code 时以 success 为准；两者都没有则交给调用方
            # 检查 data 是否为空。
            ok = envelope.success is not False
        if not ok:
            raise self._business_error(
                code if code is not None else "unknown",
                envelope.msg,
                envelope.trace_id,
                provider_task_id=provider_task_id,
                data_id=data_id,
                default_transient=default_transient,
            )
        return envelope.data

    def _business_error(
        self,
        code: int | str,
        msg: str | None,
        trace_id: str | None,
        *,
        provider_task_id: str | None = None,
        data_id: str | None = None,
        default_transient: bool,
    ) -> MinerUError:
        kind = classify_business_error(code)
        message = f"MinerU API error (code={code}): {msg or 'unknown error'}"
        if trace_id:
            message = f"{message} [trace_id={trace_id}]"

        if kind == "auth":
            error: MinerUError = MinerUAuthenticationError(message)
        elif kind == "quota":
            error = MinerUQuotaError(message)
        elif kind == "transient" or (kind == "unknown" and default_transient):
            error = MinerUTransientError(message)
        else:
            # 未知码在 submit 中终态处理，避免重复创建任务。
            error = MinerUExecutionError(message)

        self._telemetry.log(
            "mineru.poll.error" if default_transient else "mineru.failed",
            level=logging.WARNING,
            provider_task_id=provider_task_id,
            data_id=data_id,
            error_type=type(error).__name__,
            error_code=str(code),
        )
        return error

    def _classify_submit_http_error(self, exc: requests.HTTPError) -> MinerUError:
        status = _http_status(exc)
        if status == 429:
            # 服务明确未处理；可以安全重试。
            return MinerUTransientError(
                f"MinerU task submission was rate limited (HTTP 429): {exc}",
                retry_after=_retry_after(exc.response, wall_clock=self._wall_clock),
            )
        if status in (401, 403):
            return MinerUAuthenticationError(
                f"MinerU task submission was rejected with HTTP {status}: {exc}"
            )
        # 其余（含 5xx）结果未知；重试可能重复创建任务。
        return MinerUExecutionError(f"MinerU task submission failed: {exc}")

    def _classify_submit_transport_error(self, exc: BaseException) -> MinerUError:
        if _failed_before_request_sent(exc):
            return MinerUTransientError(
                f"MinerU task submission failed before the request was sent: {exc}"
            )
        return MinerUExecutionError(f"MinerU task submission failed: {exc}")

    def _classify_trace_http_error(self, exc: requests.HTTPError) -> MinerUError:
        status = _http_status(exc)
        if status == 429:
            return MinerUTransientError(
                f"MinerU status query was rate limited (HTTP 429): {exc}",
                retry_after=_retry_after(exc.response, wall_clock=self._wall_clock),
            )
        if status == 404:
            # 刚提交时任务可能尚未可见；由 max_consecutive_errors 兜底。
            return MinerUTransientError(f"MinerU status query returned HTTP 404: {exc}")
        if status is not None and 500 <= status < 600:
            return MinerUTransientError(
                f"MinerU status query failed with HTTP {status}: {exc}"
            )
        if status in (401, 403):
            return MinerUAuthenticationError(
                f"MinerU status query was rejected with HTTP {status}: {exc}"
            )
        if status is not None and 400 <= status < 500:
            return MinerUExecutionError(
                f"MinerU status query was rejected with HTTP {status}: {exc}"
            )
        return MinerUTransientError(f"MinerU status query failed: {exc}")


__all__ = ["MINERU_BASE_URL", "MinerUTransport", "parse_retry_after"]
