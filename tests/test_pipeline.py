"""SPEC-004 Pipeline 契约测试。

全部路径都在无网络环境下运行：client / downloader / 提取函数 / 时钟均通过
内部测试缝注入替身；唯一的例外是 AC-7.5 的默认构造路径测试，它使用本地
回环 mock HTTP 服务验证真实 client。
"""

from __future__ import annotations

import importlib
import inspect
import io
import json
import logging
import socket
import weakref
import zipfile
from pathlib import Path

import pytest

import mineru_parser
from mineru_parser import (
    ExtractionLimits,
    MinerUParserError,
    PipelineConfigurationError,
    PipelineError,
    PipelineStage,
    PipelineTimeoutError,
    parse,
)
from mineru_parser._client import MinerUApiClient
from mineru_parser._client.errors import (
    MinerUExecutionError,
    MinerUQuotaError,
    MinerUTimeoutError,
)
from mineru_parser._client.models import (
    MinerUTaskResult,
    MinerUTaskState,
    MinerUTaskStatus,
)
from mineru_parser._downloader.errors import (
    ResultDownloadSecurityError,
    ResultDownloadTimeoutError,
)
from mineru_parser._extractor import extract_result
from mineru_parser._extractor.errors import ResultExtractionLimitError
from mineru_parser.pipeline import orchestrator as orchestrator_module
from mineru_parser.pipeline.orchestrator import PipelineOrchestrator

URI = "https://example.com/paper.pdf"
ZIP_URL = "https://cdn.example.com/result.zip?token=TOP-SECRET"
PROVIDER_TASK_ID = "provider-task"
SUBMIT_TASK_ID = "submit-task"
DATA_ID = "doc-42"

STATUS = MinerUTaskStatus(
    state=MinerUTaskState.RUNNING,
    raw_state="running",
    task_id=SUBMIT_TASK_ID,
)

DEFAULT_DATA = {
    "pages": [[{"type": "paragraph"}]],
    "images": [{"path": "images/a.jpg", "bytes": b"image-bytes"}],
}

_PIPELINE_OUTCOMES = {
    "success",
    "config_error",
    "timeout",
    "stage_error",
    "unexpected",
}
_PIPELINE_STAGES = {stage.value for stage in PipelineStage}


# --- 测试替身 -------------------------------------------------------------


def make_result(
    *,
    provider_task_id: str = PROVIDER_TASK_ID,
    data_id: str | None = DATA_ID,
    zip_url: str = ZIP_URL,
) -> MinerUTaskResult:
    return MinerUTaskResult(
        zip_url=zip_url,
        provider_task_id=provider_task_id,
        data_id=data_id,
    )


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, dict[str, str]]] = []

    def __call__(self, name: str, value: float, tags: dict[str, str]) -> None:
        self.calls.append((name, float(value), dict(tags)))

    def named(self, name: str):
        return [call for call in self.calls if call[0] == name]


class TrackingStream(io.BytesIO):
    def __init__(self, data: bytes, *, events: list[str]) -> None:
        super().__init__(data)
        self._events = events

    def close(self) -> None:
        if not self.closed:
            self._events.append("stream:close")
        super().close()


class FakeHandle:
    def __init__(
        self,
        *,
        task_id: str = SUBMIT_TASK_ID,
        data_id: str | None = None,
        result: MinerUTaskResult | None = None,
        wait_error: BaseException | None = None,
        on_wait=None,
        events: list[str] | None = None,
    ) -> None:
        self._task_id = task_id
        self._data_id = data_id
        self._result = result if result is not None else make_result()
        self._wait_error = wait_error
        self._on_wait = on_wait
        self._events = events
        self.wait_kwargs: dict | None = None

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def data_id(self) -> str | None:
        return self._data_id

    def wait(
        self,
        *,
        timeout=None,
        deadline_epoch=None,
        on_update=None,
        policy=None,
    ):
        self.wait_kwargs = {"timeout": timeout, "on_update": on_update}
        if self._events is not None:
            self._events.append("wait")
        if self._on_wait is not None:
            self._on_wait()
        if on_update is not None:
            on_update(STATUS)
        if self._wait_error is not None:
            raise self._wait_error
        return self._result


class FakeClient:
    def __init__(
        self,
        *,
        handle: FakeHandle | None = None,
        submit_error: BaseException | None = None,
        close_error: BaseException | None = None,
        on_submit=None,
        events: list[str] | None = None,
    ) -> None:
        self._handle = handle if handle is not None else FakeHandle()
        self._submit_error = submit_error
        self._close_error = close_error
        self._on_submit = on_submit
        self._events = events
        self.closed = False
        self.submit_calls: list[dict] = []

    def submit(self, uri, *, model_version="vlm", data_id=None):
        self.submit_calls.append(
            {"uri": uri, "model_version": model_version, "data_id": data_id}
        )
        if self._events is not None:
            self._events.append("submit")
        if self._on_submit is not None:
            self._on_submit()
        if self._submit_error is not None:
            raise self._submit_error
        return self._handle

    def close(self) -> None:
        self.closed = True
        if self._events is not None:
            self._events.append("client:close")
        if self._close_error is not None:
            raise self._close_error


class FakeDownloader:
    def __init__(
        self,
        *,
        stream: io.BytesIO | None = None,
        error: BaseException | None = None,
        close_error: BaseException | None = None,
        on_resolve=None,
        events: list[str] | None = None,
    ) -> None:
        self._stream = stream if stream is not None else io.BytesIO(b"zip")
        self._error = error
        self._close_error = close_error
        self._on_resolve = on_resolve
        self._events = events
        self.closed = False
        self.resolved_urls: list[str] = []

    @property
    def returned_stream(self) -> io.BytesIO:
        return self._stream

    def resolve(self, url: str) -> io.BytesIO:
        self.resolved_urls.append(url)
        if self._events is not None:
            self._events.append("download")
        if self._on_resolve is not None:
            self._on_resolve()
        if self._error is not None:
            raise self._error
        return self._stream

    def close(self) -> None:
        self.closed = True
        if self._events is not None:
            self._events.append("downloader:close")
        if self._close_error is not None:
            raise self._close_error


class Harness:
    """把编排器的内部测试缝打包成可配置的测试夹具。"""

    def __init__(
        self,
        *,
        handle: FakeHandle | None = None,
        submit_error: BaseException | None = None,
        client_close_error: BaseException | None = None,
        on_submit=None,
        stream: io.BytesIO | None = None,
        resolve_error: BaseException | None = None,
        downloader_close_error: BaseException | None = None,
        on_resolve=None,
        extract_data=None,
        extract_error: BaseException | None = None,
        on_extract=None,
        real_extract: bool = False,
    ) -> None:
        self.clock = Clock()
        self.wall_clock = lambda: 1_800_000_000.0
        self.events: list[str] = []
        self.factory_calls: list[tuple[str, object, object]] = []
        self.extract_calls: list[io.BytesIO] = []
        self.extract_kwargs: list[dict] = []

        self.handle = handle if handle is not None else FakeHandle()
        if self.handle._events is None:  # type: ignore[attr-defined]
            self.handle._events = self.events  # type: ignore[attr-defined]
        self.client = FakeClient(
            handle=self.handle,
            submit_error=submit_error,
            close_error=client_close_error,
            on_submit=on_submit,
            events=self.events,
        )
        self.downloader = FakeDownloader(
            stream=stream,
            error=resolve_error,
            close_error=downloader_close_error,
            on_resolve=on_resolve,
            events=self.events,
        )
        self._extract_data = extract_data
        self._extract_error = extract_error
        self._on_extract = on_extract
        self._real_extract = real_extract

    # --- 工厂 -------------------------------------------------------------

    def _client_factory(self, *, on_metric=None, correlation_id=None):
        self.factory_calls.append(("client", on_metric, correlation_id))
        return self.client

    def _downloader_factory(self, *, on_metric=None, correlation_id=None):
        self.factory_calls.append(("downloader", on_metric, correlation_id))
        return self.downloader

    def _extract(self, stream, *, limits=None, on_metric=None, correlation_id=None):
        self.extract_calls.append(stream)
        self.extract_kwargs.append(
            {"limits": limits, "on_metric": on_metric, "correlation_id": correlation_id}
        )
        self.events.append("extract")
        if self._on_extract is not None:
            self._on_extract()
        if self._extract_error is not None:
            raise self._extract_error
        return DEFAULT_DATA if self._extract_data is None else self._extract_data

    # --- 执行 -------------------------------------------------------------

    def run(self, **kwargs):
        kwargs.setdefault("timeout", 60)
        return PipelineOrchestrator(
            client_factory=self._client_factory,
            downloader_factory=self._downloader_factory,
            extract=extract_result if self._real_extract else self._extract,
            monotonic=self.clock,
            wall_clock=self.wall_clock,
        ).run(URI, **kwargs)


def build_result_zip() -> bytes:
    manifest = json.dumps(
        [
            [
                {
                    "type": "paragraph",
                    "content": {
                        "paragraph_content": [{"type": "text", "content": "hello"}]
                    },
                    "bbox": [0, 0, 10, 10],
                }
            ]
        ]
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("doc_content_list_v2.json", manifest)
        archive.writestr("images/a.jpg", b"image-bytes")
    return buffer.getvalue()


# --- US-1：单函数端到端解析 ------------------------------------------------


def test_parse_returns_parse_result_with_nested_data():
    harness = Harness()
    result = harness.run()

    assert set(result) == {
        "status",
        "data",
        "task_id",
        "data_id",
        "zip_url",
        "error",
    }
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["data"] is DEFAULT_DATA
    assert set(result["data"]) == {"pages", "images"}
    assert result["task_id"] == PROVIDER_TASK_ID
    assert result["data_id"] == DATA_ID
    assert result["zip_url"] == ZIP_URL
    assert harness.client.submit_calls == [
        {"uri": URI, "model_version": "vlm", "data_id": None}
    ]


def test_component_parameters_passed_through():
    updates: list[MinerUTaskStatus] = []
    harness = Harness()
    result = harness.run(
        model_version="vlm-2",
        data_id="doc-x",
        on_update=updates.append,
    )

    assert result["status"] == "success"
    assert harness.client.submit_calls == [
        {"uri": URI, "model_version": "vlm-2", "data_id": "doc-x"}
    ]
    assert updates == [STATUS]


def test_parse_with_real_extractor_keeps_extracted_result_shape():
    stream = io.BytesIO(build_result_zip())
    harness = Harness(stream=stream, real_extract=True)
    result = harness.run()

    assert result["status"] == "success"
    pages = result["data"]["pages"]
    assert isinstance(pages, list) and len(pages) == 1
    assert type(pages[0][0]).__name__ == "ParagraphBlock"
    images = result["data"]["images"]
    assert images == [{"path": "images/a.jpg", "bytes": b"image-bytes"}]
    assert isinstance(images[0]["bytes"], bytes)


def _stage_events(events: list[str]) -> list[str]:
    return [event for event in events if not event.endswith(":close")]


def test_stage_order_and_early_abort():
    success = Harness()
    success.run()
    assert _stage_events(success.events) == ["submit", "wait", "download", "extract"]

    submit_failure = Harness(submit_error=MinerUExecutionError("boom"))
    result = submit_failure.run()
    assert result["status"] == "failed"
    assert _stage_events(submit_failure.events) == ["submit"]
    assert submit_failure.downloader.resolved_urls == []

    wait_failure = Harness(
        handle=FakeHandle(wait_error=MinerUExecutionError("wait failed"))
    )
    result = wait_failure.run()
    assert result["status"] == "failed"
    assert _stage_events(wait_failure.events) == ["submit", "wait"]
    assert wait_failure.downloader.resolved_urls == []

    download_failure = Harness(
        resolve_error=ResultDownloadSecurityError("blocked")
    )
    result = download_failure.run()
    assert result["status"] == "failed"
    assert _stage_events(download_failure.events) == ["submit", "wait", "download"]
    assert download_failure.extract_calls == []


def test_components_built_internally_and_isolated_per_call(monkeypatch):
    clients: list[FakeClient] = []
    downloaders: list[FakeDownloader] = []

    def client_factory(**kwargs):
        client = FakeClient()
        clients.append(client)
        return client

    def downloader_factory(**kwargs):
        downloader = FakeDownloader()
        downloaders.append(downloader)
        return downloader

    monkeypatch.setattr(orchestrator_module, "_default_client_factory", client_factory)
    monkeypatch.setattr(
        orchestrator_module, "_default_downloader_factory", downloader_factory
    )
    monkeypatch.setattr(
        orchestrator_module,
        "extract_result",
        lambda stream, **kwargs: {"pages": [], "images": []},
    )

    assert parse(URI)["status"] == "success"
    assert parse(URI)["status"] == "success"

    assert len(clients) == 2 and len(downloaders) == 2
    assert clients[0] is not clients[1]
    assert downloaders[0] is not downloaders[1]
    assert all(client.closed for client in clients)
    assert all(downloader.closed for downloader in downloaders)
    assert sum(len(client.submit_calls) for client in clients) == 2


def test_concurrent_parses_use_isolated_components(monkeypatch):
    import threading

    clients: list[FakeClient] = []
    lock = threading.Lock()

    def client_factory(**kwargs):
        client = FakeClient()
        with lock:
            clients.append(client)
        return client

    monkeypatch.setattr(orchestrator_module, "_default_client_factory", client_factory)
    monkeypatch.setattr(
        orchestrator_module,
        "_default_downloader_factory",
        lambda **kwargs: FakeDownloader(),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "extract_result",
        lambda stream, **kwargs: {"pages": [], "images": []},
    )

    results: list[dict] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(parse(URI))
        except BaseException as exc:  # pragma: no cover - 失败时由断言报告
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(results) == 4
    assert all(result["status"] == "success" for result in results)
    assert len(clients) == 4
    assert len({id(client) for client in clients}) == 4
    assert all(client.closed for client in clients)


def test_results_are_fresh_objects():
    first = Harness(
        extract_data={"pages": [[1]], "images": [{"path": "a", "bytes": b"1"}]}
    ).run()
    second = Harness(
        extract_data={"pages": [[2]], "images": [{"path": "b", "bytes": b"2"}]}
    ).run()

    assert first["data"] is not second["data"]
    assert first["data"]["pages"] is not second["data"]["pages"]
    assert first["data"]["images"] is not second["data"]["images"]
    assert first["data"]["images"][0]["bytes"] is not second["data"]["images"][0]["bytes"]


def test_no_retained_references():
    harness = Harness()
    stream = harness.downloader.returned_stream
    reference = weakref.ref(stream)

    harness.run()
    harness.downloader._stream = None  # type: ignore[attr-defined]
    del harness, stream
    import gc

    gc.collect()
    assert reference() is None


def test_parse_result_metadata_provenance():
    harness = Harness(
        handle=FakeHandle(
            task_id=SUBMIT_TASK_ID,
            data_id=DATA_ID,
            result=make_result(
                provider_task_id="server-side-id",
                data_id="server-data-id",
                zip_url=ZIP_URL,
            ),
        ),
        extract_data=DEFAULT_DATA,
    )
    result = harness.run()

    assert result["task_id"] == "server-side-id"
    assert result["data_id"] == "server-data-id"
    assert result["zip_url"] == ZIP_URL


def test_zip_url_never_logged_or_labelled(caplog):
    metrics = RecordingMetrics()
    harness = Harness(
        resolve_error=ResultDownloadSecurityError("blocked"), extract_data=None
    )
    with caplog.at_level(logging.INFO, logger="mineru_parser"):
        result = harness.run(on_metric=metrics)

    assert result["status"] == "failed"
    assert result["zip_url"] == ZIP_URL  # 当时已知
    assert ZIP_URL not in caplog.text
    for name, _, tags in metrics.calls:
        assert ZIP_URL not in name
        assert ZIP_URL not in str(tags)


def test_known_errors_wrapped_and_unknown_propagated():
    known = Harness(submit_error=MinerUQuotaError("quota"))
    result = known.run()
    assert result["status"] == "failed"
    assert result["error"]["error_type"] == "MinerUQuotaError"
    assert result["error"]["stage"] == PipelineStage.SUBMIT

    unknown_error = ValueError("unexpected")
    unknown = Harness(submit_error=unknown_error)
    with pytest.raises(ValueError) as info:
        unknown.run()
    assert info.value is unknown_error

    with pytest.raises(ValueError) as info:
        Harness(submit_error=unknown_error).run(raise_on_error=True)
    assert info.value is unknown_error


def test_failed_envelope_shape_and_partial_metadata():
    submit_failure = Harness(submit_error=MinerUExecutionError("boom"))
    result = submit_failure.run(data_id="caller-data-id")

    assert set(result) == {
        "status",
        "data",
        "task_id",
        "data_id",
        "zip_url",
        "error",
    }
    assert result["status"] == "failed"
    assert result["data"] is None
    assert result["task_id"] is None
    assert result["data_id"] == "caller-data-id"
    assert result["zip_url"] is None
    assert set(result["error"]) == {"stage", "error_type", "message", "cause_type"}
    assert result["error"]["stage"] == PipelineStage.SUBMIT
    assert result["error"]["error_type"] == "MinerUExecutionError"

    download_failure = Harness(
        resolve_error=ResultDownloadSecurityError("blocked")
    )
    result = download_failure.run(data_id="caller-data-id")
    assert result["task_id"] == PROVIDER_TASK_ID
    assert result["data_id"] == DATA_ID
    assert result["zip_url"] == ZIP_URL
    assert result["error"]["stage"] == PipelineStage.DOWNLOAD


# --- US-2：唯一公共 API 与契约面 ------------------------------------------


def test_top_level_exports_exactly_one_function():
    functions = [
        name
        for name in mineru_parser.__all__
        if inspect.isfunction(getattr(mineru_parser, name))
    ]
    assert functions == ["parse"]

    retained = {
        "MinerUParserError",
        "PipelineError",
        "PipelineTimeoutError",
        "PipelineConfigurationError",
        "ParseResult",
        "ErrorMessage",
        "ExtractedResult",
        "ExtractedImage",
        "ExtractionLimits",
        "MetricHook",
        "PipelineStage",
        "MinerUTaskStatus",
        "__version__",
        "parse",
    }
    assert set(mineru_parser.__all__) == retained
    for name in retained:
        assert hasattr(mineru_parser, name)

    removed = {
        "MinerUApiClient",
        "AsyncResult",
        "ResultDownloader",
        "extract_result",
        "canonicalize_member_path",
        "MinerUError",
        "MinerUQuotaError",
        "ResultDownloadError",
        "ResultExtractionError",
        "MinerUTaskResult",
        "DEFAULT_EXTRACTION_LIMITS",
    }
    for name in removed:
        assert not hasattr(mineru_parser, name)
        assert name not in mineru_parser.__all__


def test_component_public_import_paths_are_closed():
    for module in (
        "mineru_parser.client",
        "mineru_parser.downloader",
        "mineru_parser.extractor",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


def test_top_level_has_no_second_function():
    public_functions = [
        name
        for name in dir(mineru_parser)
        if not name.startswith("_") and inspect.isfunction(getattr(mineru_parser, name))
    ]
    assert public_functions == ["parse"]
    assert not hasattr(mineru_parser, "parse_async")
    assert not hasattr(mineru_parser, "parse_sync")
    assert not hasattr(mineru_parser, "parse_with")


def test_parse_signature_is_stable():
    signature = inspect.signature(parse)
    parameters = signature.parameters
    assert list(parameters) == [
        "uri",
        "model_version",
        "data_id",
        "timeout",
        "deadline_epoch",
        "limits",
        "raise_on_error",
        "on_update",
        "on_error",
        "on_metric",
        "correlation_id",
    ]
    assert parameters["uri"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["uri"].default is inspect.Parameter.empty
    for name in list(parameters)[1:]:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY

    assert parameters["model_version"].default == "vlm"
    assert parameters["data_id"].default is None
    assert parameters["timeout"].default is None
    assert parameters["deadline_epoch"].default is None
    assert parameters["limits"].default is None
    assert parameters["raise_on_error"].default is False
    assert parameters["on_update"].default is None
    assert parameters["on_error"].default is None
    assert parameters["on_metric"].default is None
    assert parameters["correlation_id"].default is None


def test_orchestration_lives_in_pipeline_package():
    assert parse.__module__ == "mineru_parser.pipeline.orchestrator"
    assert "PipelineOrchestrator" not in mineru_parser.__all__
    assert not hasattr(mineru_parser, "PipelineOrchestrator")
    assert not hasattr(mineru_parser, "Budget")


def test_no_task_resume_parameter():
    assert "task_id" not in inspect.signature(parse).parameters


def test_public_surface_has_no_component_parameters():
    parameters = inspect.signature(parse).parameters
    for name in ("client", "downloader", "extractor", "client_factory", "downloader_factory"):
        assert name not in parameters
    annotation = repr(inspect.signature(parse))
    assert "MinerUApiClient" not in annotation
    assert "ResultDownloader" not in annotation


def test_duplicate_calls_create_two_tasks(monkeypatch):
    clients: list[FakeClient] = []

    def client_factory(**kwargs):
        client = FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr(orchestrator_module, "_default_client_factory", client_factory)
    monkeypatch.setattr(
        orchestrator_module,
        "_default_downloader_factory",
        lambda **kwargs: FakeDownloader(),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "extract_result",
        lambda stream, **kwargs: {"pages": [], "images": []},
    )

    parse(URI, data_id="same")
    parse(URI, data_id="same")

    assert len(clients) == 2
    assert all(len(client.submit_calls) == 1 for client in clients)


# --- US-3：生命周期与资源所有权 --------------------------------------------


def test_owned_components_closed_in_order():
    events: list[str] = []
    stream = TrackingStream(b"zip", events=events)
    harness = Harness(stream=stream, real_extract=False)
    harness.events = events
    harness.handle._events = events
    harness.client._events = events
    harness.downloader._events = events

    harness.run()

    assert events == [
        "submit",
        "wait",
        "download",
        "extract",
        "stream:close",
        "downloader:close",
        "client:close",
    ]
    assert stream.closed
    assert harness.downloader.closed
    assert harness.client.closed


def test_components_closed_on_failure():
    harness = Harness(submit_error=MinerUExecutionError("boom"))
    result = harness.run()

    assert result["status"] == "failed"
    assert harness.downloader.closed
    assert harness.client.closed


def test_zip_stream_closed_and_result_independent():
    stream = io.BytesIO(build_result_zip())
    harness = Harness(stream=stream, real_extract=True)
    result = harness.run()

    assert stream.closed
    # 提取器已复制字节，关闭流之后结果仍可正常使用。
    assert result["data"]["images"][0]["bytes"] == b"image-bytes"
    assert result["data"]["pages"][0][0].type == "paragraph"


def test_zip_stream_closed_on_extract_failure():
    events: list[str] = []
    stream = TrackingStream(b"zip", events=events)
    harness = Harness(
        stream=stream, extract_error=ResultExtractionLimitError("total_image_bytes")
    )
    result = harness.run()

    assert result["status"] == "failed"
    assert stream.closed
    assert "stream:close" in events


def test_close_failure_does_not_change_outcome(caplog):
    harness = Harness(
        downloader_close_error=ResultDownloadSecurityError("close boom")
    )
    with caplog.at_level(logging.WARNING, logger="mineru_parser"):
        result = harness.run()

    # 清理失败不改变本次调用的结果，也不阻止后续组件关闭。
    assert result["status"] == "success"
    assert harness.client.closed
    close_logs = [
        record
        for record in caplog.records
        if record.message == "mineru.pipeline.close.failed"
    ]
    assert len(close_logs) == 1
    assert close_logs[0].component == "downloader"
    assert close_logs[0].error_type == "ResultDownloadSecurityError"


def test_caller_owned_objects_untouched():
    """调用方无法向管道提供任何需要被管理的对象（AC-2.10 / AC-3.7）。"""
    parameters = inspect.signature(parse).parameters
    assert not any(
        name in parameters
        for name in ("session", "stream", "bundle", "result", "task_id")
    )


# --- US-4：端到端预算与超时 ------------------------------------------------


def test_mutually_exclusive_parameters_rejected_before_network():
    harness = Harness()
    result = harness.run(timeout=10, deadline_epoch=1_700_000_000.0)

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.CONFIG
    assert result["error"]["error_type"] == "PipelineConfigurationError"
    assert harness.factory_calls == []

    with pytest.raises(PipelineConfigurationError) as info:
        Harness().run(timeout=10, deadline_epoch=1_700_000_000.0, raise_on_error=True)
    assert info.value.field == "timeout"


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf"), True, "10"])
def test_invalid_budget_values_rejected_before_components(timeout):
    harness = Harness()
    result = harness.run(timeout=timeout)
    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.CONFIG
    assert harness.factory_calls == []


def test_budget_exhausted_before_submit():
    harness = Harness()
    result = harness.run(timeout=0)

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.SUBMIT
    assert result["error"]["error_type"] == "PipelineTimeoutError"
    assert harness.factory_calls == []
    assert harness.events == []

    with pytest.raises(PipelineTimeoutError) as info:
        Harness().run(timeout=0, raise_on_error=True)
    assert info.value.stage is PipelineStage.SUBMIT


def test_budget_exhausted_before_wait():
    harness = Harness(on_submit=lambda: harness.clock.advance(100))
    result = harness.run(timeout=10)

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.WAIT
    assert result["error"]["error_type"] == "PipelineTimeoutError"
    assert harness.downloader.resolved_urls == []


def test_budget_exhausted_before_download():
    harness = Harness()
    harness.handle._on_wait = lambda: harness.clock.advance(100)

    result = harness.run(timeout=10)

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.DOWNLOAD
    assert harness.downloader.resolved_urls == []


def test_download_overrun_detected_after_stage():
    harness = Harness()
    harness.downloader._on_resolve = lambda: harness.clock.advance(100)

    result = harness.run(timeout=10)

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.DOWNLOAD
    assert result["error"]["error_type"] == "PipelineTimeoutError"
    assert len(harness.downloader.resolved_urls) == 1


def test_extract_overrun_detected_after_extract():
    metrics = RecordingMetrics()
    harness = Harness(on_extract=lambda: harness.clock.advance(100))
    result = harness.run(timeout=10, on_metric=metrics)

    assert result["status"] == "failed"
    assert result["data"] is None
    assert result["error"]["stage"] == PipelineStage.EXTRACT
    assert result["error"]["error_type"] == "PipelineTimeoutError"
    assert metrics.named("mineru.pipeline.pages")[0][1] == 0
    assert metrics.named("mineru.pipeline.images")[0][1] == 0
    assert metrics.named("mineru.pipeline.image_bytes")[0][1] == 0


def test_wait_timeout_translated_with_cause():
    original = MinerUTimeoutError(
        "late", task_id=SUBMIT_TASK_ID, last_status=STATUS
    )
    harness = Harness(handle=FakeHandle(wait_error=original))

    with pytest.raises(PipelineTimeoutError) as info:
        harness.run(raise_on_error=True)

    assert info.value.stage is PipelineStage.WAIT
    assert info.value.task_id == SUBMIT_TASK_ID
    assert info.value.last_status is STATUS
    assert info.value.__cause__ is original


def test_wait_timeout_enveloped():
    original = MinerUTimeoutError(
        "late", task_id=SUBMIT_TASK_ID, last_status=STATUS
    )
    harness = Harness(handle=FakeHandle(wait_error=original))
    result = harness.run()

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.WAIT
    assert result["error"]["error_type"] == "PipelineTimeoutError"
    assert result["error"]["cause_type"] == "MinerUTimeoutError"
    assert result["task_id"] == SUBMIT_TASK_ID


def test_download_timeout_translated_with_cause():
    original = ResultDownloadTimeoutError("slow")
    harness = Harness(resolve_error=original)

    with pytest.raises(PipelineTimeoutError) as info:
        harness.run(raise_on_error=True)

    assert info.value.stage is PipelineStage.DOWNLOAD
    assert info.value.__cause__ is original


def test_download_timeout_enveloped():
    harness = Harness(resolve_error=ResultDownloadTimeoutError("slow"))
    result = harness.run()

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.DOWNLOAD
    assert result["error"]["error_type"] == "PipelineTimeoutError"
    assert result["error"]["cause_type"] == "ResultDownloadTimeoutError"


def test_budget_uses_injected_monotonic_clock():
    harness = Harness()
    harness.run(timeout=10)

    assert harness.handle.wait_kwargs["timeout"] == pytest.approx(10)


def test_deadline_epoch_is_converted_once_to_monotonic_budget():
    harness = Harness()
    harness.wall_clock = lambda: 1_800_000_000.0
    result = harness.run(timeout=None, deadline_epoch=1_800_000_010.0)

    assert result["status"] == "success"
    assert harness.handle.wait_kwargs["timeout"] == pytest.approx(10)


def test_no_default_timeout_means_unbounded_wait():
    harness = Harness()
    result = harness.run(timeout=None)

    assert result["status"] == "success"
    assert harness.handle.wait_kwargs["timeout"] is None


# --- US-5：阶段归因与可观测性 ----------------------------------------------


def test_pipeline_stage_enum_is_closed():
    assert [stage.value for stage in PipelineStage] == [
        "config",
        "submit",
        "wait",
        "download",
        "extract",
    ]
    assert all(isinstance(stage, str) for stage in PipelineStage)


def test_pipeline_error_hierarchy():
    assert issubclass(PipelineError, MinerUParserError)
    assert issubclass(PipelineConfigurationError, PipelineError)
    assert issubclass(PipelineTimeoutError, PipelineError)
    assert not issubclass(PipelineError, MinerUExecutionError)
    assert not issubclass(MinerUExecutionError, PipelineError)


def _stage_harness(case: str, error: BaseException) -> Harness:
    if case == "submit":
        return Harness(submit_error=error)
    if case == "wait":
        return Harness(handle=FakeHandle(wait_error=error))
    if case == "download":
        return Harness(resolve_error=error)
    return Harness(extract_error=error)


@pytest.mark.parametrize(
    "case,error_factory,expected_stage",
    [
        (
            "submit",
            lambda: MinerUQuotaError("quota"),
            PipelineStage.SUBMIT,
        ),
        (
            "wait",
            lambda: MinerUExecutionError("wait"),
            PipelineStage.WAIT,
        ),
        (
            "download",
            lambda: ResultDownloadSecurityError("blocked"),
            PipelineStage.DOWNLOAD,
        ),
        (
            "extract",
            lambda: ResultExtractionLimitError("total_image_bytes"),
            PipelineStage.EXTRACT,
        ),
    ],
)
def test_stage_error_propagates_unchanged(case, error_factory, expected_stage):
    error = error_factory()
    with pytest.raises(type(error)) as info:
        _stage_harness(case, error).run(raise_on_error=True)
    assert info.value is error

    envelope_error = error_factory()
    envelope = _stage_harness(case, envelope_error).run()
    assert envelope["status"] == "failed"
    assert envelope["error"]["stage"] == expected_stage
    assert envelope["error"]["error_type"] == type(envelope_error).__name__


def test_on_error_isolated():
    harness = Harness(submit_error=MinerUExecutionError("boom"))

    def explode(stage, exc):
        raise RuntimeError("callback bug")

    result = harness.run(on_error=explode)
    assert result["status"] == "failed"
    assert result["error"]["error_type"] == "MinerUExecutionError"


def test_on_error_failure_is_logged(caplog):
    harness = Harness(submit_error=MinerUExecutionError("boom"))

    def explode(stage, exc):
        raise RuntimeError("callback bug")

    with caplog.at_level(logging.WARNING, logger="mineru_parser"):
        harness.run(on_error=explode)

    assert any(
        record.message == "mineru.pipeline.on_error.failed"
        for record in caplog.records
    )


def test_on_error_receives_original_before_translation():
    original = MinerUTimeoutError("late", task_id=SUBMIT_TASK_ID, last_status=STATUS)
    seen: list[tuple[PipelineStage, BaseException]] = []
    harness = Harness(handle=FakeHandle(wait_error=original))

    harness.run(on_error=lambda stage, exc: seen.append((stage, exc)))

    assert len(seen) == 1
    assert seen[0][0] is PipelineStage.WAIT
    assert seen[0][1] is original


def test_on_error_base_exception_is_swallowed():
    def explode(stage, exc):
        raise MemoryError("callback bug")

    envelope = Harness(submit_error=MinerUExecutionError("boom")).run(
        on_error=explode
    )
    assert envelope["status"] == "failed"
    assert envelope["error"]["error_type"] == "MinerUExecutionError"

    with pytest.raises(MinerUExecutionError):
        Harness(submit_error=MinerUExecutionError("boom")).run(
            on_error=explode, raise_on_error=True
        )


def test_on_metric_isolated(caplog):
    def explode(name, value, tags):
        raise RuntimeError("metrics backend down")

    with caplog.at_level(logging.WARNING, logger="mineru_parser"):
        result = Harness().run(on_metric=explode)

    assert result["status"] == "success"
    assert any(record.message == "mineru.metric.failed" for record in caplog.records)


def test_on_metric_base_exception_is_swallowed():
    def explode(name, value, tags):
        raise MemoryError("metrics backend down")

    result = Harness().run(on_metric=explode)
    assert result["status"] == "success"


def test_metrics_reported_on_success_and_failure():
    success_metrics = RecordingMetrics()
    success = Harness().run(on_metric=success_metrics)
    assert success["status"] == "success"

    failure_metrics = RecordingMetrics()
    failure = Harness(submit_error=MinerUExecutionError("boom")).run(
        on_metric=failure_metrics
    )
    assert failure["status"] == "failed"

    for metrics, expected_outcome in (
        (success_metrics, "success"),
        (failure_metrics, "stage_error"),
    ):
        total = metrics.named("mineru.pipeline.total")
        duration = metrics.named("mineru.pipeline.duration_ms")
        assert len(total) == 1
        assert len(duration) == 1
        assert total[0][2]["outcome"] == expected_outcome
        assert duration[0][2]["outcome"] == expected_outcome
        assert total[0][2]["stage"] == (
            "extract" if expected_outcome == "success" else "submit"
        )
        assert len(metrics.named("mineru.pipeline.pages")) == 1
        assert len(metrics.named("mineru.pipeline.images")) == 1
        assert len(metrics.named("mineru.pipeline.image_bytes")) == 1

    assert success_metrics.named("mineru.pipeline.pages")[0][1] == 1
    assert success_metrics.named("mineru.pipeline.images")[0][1] == 1
    assert success_metrics.named("mineru.pipeline.image_bytes")[0][1] == len(
        b"image-bytes"
    )
    assert failure_metrics.named("mineru.pipeline.pages")[0][1] == 0
    assert failure_metrics.named("mineru.pipeline.images")[0][1] == 0
    assert failure_metrics.named("mineru.pipeline.image_bytes")[0][1] == 0


def test_metrics_reported_exactly_once():
    metrics = RecordingMetrics()
    Harness().run(on_metric=metrics, raise_on_error=False)

    for name in (
        "mineru.pipeline.total",
        "mineru.pipeline.duration_ms",
        "mineru.pipeline.pages",
        "mineru.pipeline.images",
        "mineru.pipeline.image_bytes",
    ):
        assert len(metrics.named(name)) == 1, name

    stage_durations = metrics.named("mineru.pipeline.stage.duration_ms")
    assert len(stage_durations) == 4
    assert [call[2]["stage"] for call in stage_durations] == [
        "submit",
        "wait",
        "download",
        "extract",
    ]


def test_metric_labels_are_closed_enums():
    metrics = RecordingMetrics()
    Harness().run(on_metric=metrics)
    Harness(submit_error=MinerUExecutionError("boom")).run(on_metric=metrics)

    for name, _, tags in metrics.calls:
        assert set(tags) <= {"outcome", "stage"}
        if "outcome" in tags:
            assert tags["outcome"] in _PIPELINE_OUTCOMES
        if "stage" in tags:
            assert tags["stage"] in _PIPELINE_STAGES


def test_correlation_id_propagated_to_components(caplog):
    harness = Harness()
    with caplog.at_level(logging.INFO, logger="mineru_parser"):
        result = harness.run(correlation_id="corr-1")

    assert result["status"] == "success"
    assert harness.factory_calls
    assert all(call[2] == "corr-1" for call in harness.factory_calls)
    assert harness.extract_kwargs[0]["correlation_id"] == "corr-1"

    pipeline_records = [
        record
        for record in caplog.records
        if record.message.startswith("mineru.pipeline")
    ]
    assert pipeline_records
    assert all(record.correlation_id == "corr-1" for record in pipeline_records)


def test_unknown_exception_propagates_in_both_modes():
    for mode in (False, True):
        error = ValueError("unexpected")
        harness = Harness(submit_error=error)
        with pytest.raises(ValueError) as info:
            harness.run(raise_on_error=mode)
        assert info.value is error


@pytest.mark.parametrize("error", [MemoryError("oom"), KeyboardInterrupt(), SystemExit()])
def test_uncaught_errors_are_never_wrapped(error):
    for mode in (False, True):
        harness = Harness(extract_error=error)
        with pytest.raises(type(error)) as info:
            harness.run(raise_on_error=mode)
        assert info.value is error


def test_pipeline_logs_and_stage_durations(caplog):
    with caplog.at_level(logging.INFO, logger="mineru_parser"):
        result = Harness().run(correlation_id="corr-logs")

    assert result["status"] == "success"
    success = [r for r in caplog.records if r.message == "mineru.pipeline"]
    assert len(success) == 1
    assert success[0].outcome == "success"
    assert set(success[0].stage_durations_ms) == {
        "submit",
        "wait",
        "download",
        "extract",
    }
    stage_logs = [
        r for r in caplog.records if r.message == "mineru.pipeline.stage"
    ]
    assert [r.stage for r in stage_logs] == [
        "submit",
        "wait",
        "download",
        "extract",
    ]
    assert all(isinstance(r.duration_ms, float) for r in stage_logs)


def test_failure_stage_durations_logged(caplog):
    with caplog.at_level(logging.INFO, logger="mineru_parser"):
        Harness(resolve_error=ResultDownloadSecurityError("blocked")).run()

    stage_logs = [
        r for r in caplog.records if r.message == "mineru.pipeline.stage"
    ]
    assert [r.stage for r in stage_logs] == ["submit", "wait", "download"]
    assert stage_logs[-1].outcome == "stage_error"
    error_logs = [
        r for r in caplog.records if r.message == "mineru.pipeline.error"
    ]
    assert len(error_logs) == 1
    assert error_logs[0].stage == "download"
    assert error_logs[0].error_type == "ResultDownloadSecurityError"
    assert error_logs[0].outcome == "stage_error"
    assert isinstance(error_logs[0].duration_ms, float)


def test_error_message_is_serializable_and_sanitised():
    secret = "https://signed.example/result?token=LEAK"
    cause = ValueError("secret cause message")
    error = MinerUExecutionError(f"boom {secret}")
    error.__cause__ = cause
    harness = Harness(submit_error=error)

    result = harness.run()
    envelope = result["error"]

    assert set(envelope) == {"stage", "error_type", "message", "cause_type"}
    assert envelope["error_type"] == "MinerUExecutionError"
    assert envelope["cause_type"] == "ValueError"
    assert secret not in envelope["message"]
    assert "secret cause message" not in envelope["message"]
    encoded = json.dumps(envelope)
    assert secret not in encoded
    assert "MinerUExecutionError" in encoded


def test_uncaught_errors_logged_with_traceback(caplog):
    error = ValueError("unexpected")
    with caplog.at_level(logging.ERROR, logger="mineru_parser"):
        with pytest.raises(ValueError):
            Harness(extract_error=error).run()

    records = [
        r
        for r in caplog.records
        if r.message == "mineru.pipeline.error" and r.levelno == logging.ERROR
    ]
    assert len(records) == 1
    assert records[0].stage == "extract"
    assert records[0].error_type == "ValueError"
    assert records[0].outcome == "unexpected"
    assert records[0].exc_info is not None


# --- US-6：资源预算自洽 ----------------------------------------------------


def test_extraction_limit_is_terminal():
    harness = Harness(
        extract_error=ResultExtractionLimitError("total_image_bytes")
    )
    result = harness.run()

    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.EXTRACT
    assert result["error"]["error_type"] == "ResultExtractionLimitError"
    assert len(harness.downloader.resolved_urls) == 1
    assert len(harness.extract_calls) == 1


def test_invalid_limits_rejected_before_stages():
    harness = Harness()
    result = harness.run(limits=object())
    assert result["status"] == "failed"
    assert result["error"]["stage"] == PipelineStage.CONFIG
    assert harness.factory_calls == []

    with pytest.raises(PipelineConfigurationError) as info:
        Harness().run(limits=object(), raise_on_error=True)
    assert info.value.field == "limits"


def test_no_caching_or_disk_writes():
    harness = Harness()
    stream = harness.downloader.returned_stream
    result = harness.run()

    assert result["status"] == "success"
    assert harness.downloader.resolved_urls == [ZIP_URL]
    assert len(harness.extract_calls) == 1
    assert harness.extract_calls[0] is stream


def test_peak_budget_constants_documented():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text("utf-8")
    assert "290" in readme
    assert "126" in readme


# --- US-7：可测试性 --------------------------------------------------------


def test_no_module_level_mutable_state():
    import mineru_parser.pipeline.budget as budget_module
    import mineru_parser.pipeline.errors as pipeline_errors
    import mineru_parser.pipeline.result as pipeline_result
    import mineru_parser.pipeline.stages as pipeline_stages

    modules = (
        orchestrator_module,
        budget_module,
        pipeline_errors,
        pipeline_result,
        pipeline_stages,
    )
    for module in modules:
        for name, value in vars(module).items():
            if name.startswith("__") and name.endswith("__"):
                continue
            assert not isinstance(value, (dict, list, set, bytearray)), (
                f"{module.__name__}.{name} is module-level mutable state"
            )


def test_no_network_access_with_injected_components(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    result = Harness().run()
    assert result["status"] == "success"


def test_default_path_with_local_mock_server(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    payload_zip = build_result_zip()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self._send_json({"code": 0, "data": {"task_id": "task-123"}})

        def do_GET(self):
            if self.path.startswith("/extract/task/"):
                port = self.server.server_address[1]
                self._send_json(
                    {
                        "code": 0,
                        "data": {
                            "task_id": "task-123",
                            "state": "done",
                            "full_zip_url": f"http://127.0.0.1:{port}/result.zip",
                            "data_id": "doc-9",
                        },
                    }
                )
            else:  # pragma: no cover - 测试不应请求其他路径
                self.send_error(404)

        def log_message(self, *args):  # pragma: no cover - 静默测试输出
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    class LocalDownloader:
        def __init__(self, *, on_metric=None, correlation_id=None) -> None:
            self.closed = False

        def resolve(self, url: str) -> io.BytesIO:
            assert url == f"{base_url}/result.zip"
            return io.BytesIO(payload_zip)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setenv("MINERU_API_KEY", "test-key")
    monkeypatch.setattr(
        orchestrator_module,
        "_default_client_factory",
        lambda *, on_metric=None, correlation_id=None: MinerUApiClient(
            base_url=base_url,
            on_metric=on_metric,
            correlation_id=correlation_id,
        ),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "_default_downloader_factory",
        lambda *, on_metric=None, correlation_id=None: LocalDownloader(
            on_metric=on_metric, correlation_id=correlation_id
        ),
    )

    try:
        result = parse(URI, timeout=30, data_id="doc-9")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["status"] == "success"
    assert result["task_id"] == "task-123"
    assert result["data_id"] == "doc-9"
    assert result["zip_url"] == f"{base_url}/result.zip"
    assert result["data"]["images"][0]["bytes"] == b"image-bytes"
    assert type(result["data"]["pages"][0][0]).__name__ == "ParagraphBlock"
