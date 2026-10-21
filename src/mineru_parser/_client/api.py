"""``MinerUApiClient``：配置、凭证与结果句柄工厂。

客户端本身不保存任务状态，也不执行轮询；``submit`` / ``resume`` 返回
:class:`~mineru_parser._client.async_result.AsyncResult` 句柄，由句柄负责等待。
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable

import requests
from pydantic import ValidationError

from ._telemetry import MetricHook, Telemetry
from ._time import elapsed_ms
from ._validation import (
    validate_api_key,
    validate_base_url,
    validate_data_id,
    validate_request_timeout,
    validate_task_id,
)
from .async_result import AsyncResult
from .errors import (
    MinerUAuthenticationError,
    MinerUConfigurationError,
    MinerUError,
)
from .models import (
    ExtractionRequest,
    MinerUTaskStatus,
    normalize_status,
)
from .polling import (
    DEFAULT_POLL_POLICY,
    Poller,
    PollPolicy,
    PollRuntime,
)
from .transport import MINERU_BASE_URL, MinerUTransport


class MinerUApiClient:
    """MinerU API 的同步客户端。

    客户端可以在多个任务之间共享。客户端自行创建并管理底层
    ``requests.Session``（复用连接池）；也可以注入外部 Session，此时其
    生命周期由调用方负责，``close()`` 不会关闭它。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = MINERU_BASE_URL,
        request_timeout: float | tuple[float, float] = 10.0,
        poll_policy: PollPolicy | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        random_fn: Callable[[], float] = random.random,
        on_metric: MetricHook | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._api_key = validate_api_key(api_key)
        self._base_url = validate_base_url(base_url)
        self._request_timeout = validate_request_timeout(request_timeout)
        if poll_policy is None:
            poll_policy = DEFAULT_POLL_POLICY
        if not isinstance(poll_policy, PollPolicy):
            raise MinerUConfigurationError("poll_policy must be a PollPolicy instance.")
        self._poll_policy = poll_policy
        self._owns_session = session is None
        self._session = session if session is not None else requests.Session()
        self._runtime = PollRuntime(
            sleep=sleep,
            monotonic=monotonic,
            wall_clock=wall_clock,
            random_fn=random_fn,
        )
        self._telemetry = Telemetry(
            on_metric=on_metric,
            correlation_id=correlation_id,
        )
        self._transport = MinerUTransport(
            base_url=self._base_url,
            timeout=self._request_timeout,
            session=self._session,
            telemetry=self._telemetry,
            wall_clock=wall_clock,
        )

    # --- 生命周期 ---------------------------------------------------------

    def close(self) -> None:
        """关闭客户端自建的 Session；注入的 Session 由调用方管理。"""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> MinerUApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- 只读配置 ---------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def poll_policy(self) -> PollPolicy:
        return self._poll_policy

    # --- 提交 / 查询 ------------------------------------------------------

    def submit(
        self,
        uri: str,
        *,
        model_version: str = "vlm",
        data_id: str | None = None,
    ) -> AsyncResult:
        """提交任务，返回可等待的结果句柄。

        只有“确定请求未发出”的错误或 HTTP 429 抛
        :class:`MinerUTransientError`；其余错误（包括结果未知、HTTP 4xx/5xx）
        抛 :class:`MinerUExecutionError`。``data_id`` 仅用于对账，不是幂等键。
        """
        api_key = self._resolve_api_key()

        # 请求模型校验必须在 HTTP 异常处理块之外：Pydantic ValidationError
        # 不能被误映射为 MinerUExecutionError。
        try:
            request = ExtractionRequest(
                uri=uri,
                model_version=model_version,
                data_id=data_id,
            )
        except ValidationError as exc:
            raise MinerUConfigurationError(
                f"Invalid MinerU submit request: {exc}"
            ) from exc

        started = time.perf_counter()
        try:
            provider_task_id = self._transport.submit(request, api_key=api_key)
        except MinerUError:
            duration_ms = elapsed_ms(started)
            self._telemetry.log(
                "mineru.submit",
                level=logging.WARNING,
                data_id=request.data_id,
                duration_ms=duration_ms,
                outcome="error",
            )
            self._telemetry.metric("mineru.submit.total", 1, {"outcome": "error"})
            self._telemetry.metric(
                "mineru.submit.duration_ms",
                duration_ms,
                {"outcome": "error"},
            )
            raise

        duration_ms = elapsed_ms(started)
        self._telemetry.log(
            "mineru.submit",
            provider_task_id=provider_task_id,
            data_id=request.data_id,
            duration_ms=duration_ms,
            outcome="success",
        )
        self._telemetry.metric("mineru.submit.total", 1, {"outcome": "success"})
        self._telemetry.metric(
            "mineru.submit.duration_ms",
            duration_ms,
            {"outcome": "success"},
        )
        return AsyncResult(
            client=self,
            task_id=provider_task_id,
            data_id=request.data_id,
        )

    def resume(
        self,
        task_id: str,
        *,
        data_id: str | None = None,
    ) -> AsyncResult:
        """从已持久化的 task_id 恢复结果句柄，不发起网络请求。"""
        return AsyncResult(
            client=self,
            task_id=validate_task_id(task_id),
            data_id=validate_data_id(data_id),
        )

    # --- 内部 -------------------------------------------------------------

    def _trace(self, task_id: str) -> MinerUTaskStatus:
        """内部状态查询：仅供 ``AsyncResult.refresh()`` 调用。"""
        validated = validate_task_id(task_id)
        api_key = self._resolve_api_key()
        detail = self._transport.trace(validated, api_key=api_key)
        return normalize_status(validated, detail)

    def _resolve_api_key(self) -> str:
        key = self._api_key
        if key is None:
            key = os.getenv("MINERU_API_KEY")
        if key is None or not key.strip():
            raise MinerUAuthenticationError(
                "MinerU API key is not configured; set MINERU_API_KEY."
            )
        return key.strip()

    def _poller(self, policy: PollPolicy | None = None) -> Poller:
        return Poller(
            policy=policy if policy is not None else self._poll_policy,
            runtime=self._runtime,
            telemetry=self._telemetry,
        )


MinerUClient = MinerUApiClient

__all__ = ["MetricHook", "MinerUApiClient", "MinerUClient"]
