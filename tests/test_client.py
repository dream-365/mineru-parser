"""行为测试：全部通过假 Session 与假时钟完成，不访问网络。"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

import pytest
import requests

from mineru_parser import (
    MinerUApiClient,
    MinerUAuthenticationError,
    MinerUConfigurationError,
    MinerUExecutionError,
    MinerUQuotaError,
    MinerUTaskState,
    MinerUTimeoutError,
    PollPolicy,
)
from mineru_parser.core import parse_retry_after

# --- 测试替身 -------------------------------------------------------------


class FakeResponse:
    def __init__(
        self,
        payload=None,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses) -> None:
        self._responses = deque(responses)
        self.requests: list[dict] = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        if not self._responses:
            raise AssertionError("unexpected HTTP request")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


class FakeRuntime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now

    def wall_clock(self) -> float:
        return 1_000_000.0 + self.now

    def random(self) -> float:
        return 0.5


def make_client(responses, *, policy=None, runtime=None):
    runtime = runtime or FakeRuntime()
    session = FakeSession(responses)
    client = MinerUApiClient(
        api_key="test-key",
        session=session,
        poll_policy=policy,
        sleep=runtime.sleep,
        monotonic=runtime.monotonic,
        wall_clock=runtime.wall_clock,
        random_fn=runtime.random,
    )
    return client, session, runtime


def submit_ok(task_id: str = "task-1") -> dict:
    return {"code": 0, "msg": "ok", "data": {"task_id": task_id}}


def trace_ok(state: str, *, task_id: str = "task-1", **data) -> dict:
    body = {"task_id": task_id, "state": state, **data}
    return {"code": 0, "msg": "ok", "data": body}


def done_ok(**data) -> dict:
    return trace_ok(
        "done",
        full_zip_url="https://cdn.example/result.zip",
        **data,
    )


# --- submit / task 句柄 ---------------------------------------------------


def test_submit_returns_task_handle_and_sends_expected_request():
    client, session, _ = make_client([FakeResponse(submit_ok())])

    task = client.submit("https://example.com/doc.pdf", data_id="doc-1")

    assert task.task_id == "task-1"
    assert task.data_id == "doc-1"
    assert task.status is None
    assert task.state is None
    assert task.result is None
    assert repr(task) == (
        "MinerUTask(task_id='task-1', data_id='doc-1', state='unknown')"
    )

    request = session.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://mineru.net/api/v4/extract/task"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"] == {
        "url": "https://example.com/doc.pdf",
        "model_version": "vlm",
        "data_id": "doc-1",
    }
    assert request["timeout"] == 10.0


def test_submit_omits_none_data_id():
    client, session, _ = make_client([FakeResponse(submit_ok())])

    client.submit("https://example.com/doc.pdf")

    assert session.requests[0]["json"] == {
        "url": "https://example.com/doc.pdf",
        "model_version": "vlm",
    }


def test_invalid_uri_fails_before_http():
    client, session, _ = make_client([])

    with pytest.raises(MinerUConfigurationError, match="Invalid MinerU submit request"):
        client.submit("not-a-url")

    assert session.requests == []


def test_task_resumes_from_persisted_id_without_submit():
    client, session, _ = make_client(
        [
            FakeResponse(
                trace_ok(
                    "done",
                    task_id="task-9",
                    full_zip_url="https://cdn.example/result.zip",
                )
            )
        ]
    )

    task = client.task("task-9", data_id="doc-9")
    result = task.wait(timeout=10)

    assert result.provider_task_id == "task-9"
    assert result.data_id == "doc-9"
    assert [r["method"] for r in session.requests] == ["GET"]
    assert session.requests[0]["url"].endswith("/extract/task/task-9")


def test_task_id_is_url_encoded():
    client, session, _ = make_client([FakeResponse(done_ok(task_id="a/b"))])

    client.task("a/b").wait(timeout=10)

    assert session.requests[0]["url"].endswith("/extract/task/a%2Fb")


# --- 等待与轮询 -----------------------------------------------------------


def test_wait_polls_until_done_and_notifies_on_state_and_progress():
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse(trace_ok("pending")),
        FakeResponse(
            trace_ok(
                "running",
                extract_progress={"extracted_pages": 1, "total_pages": 3},
            )
        ),
        FakeResponse(
            trace_ok(
                "running",
                extract_progress={"extracted_pages": 2, "total_pages": 3},
            )
        ),
        FakeResponse(done_ok()),
    ]
    client, session, runtime = make_client(responses)
    task = client.submit("https://example.com/doc.pdf", data_id="doc-1")

    updates = []
    result = task.wait(timeout=60, on_update=updates.append)

    assert result.zip_url == "https://cdn.example/result.zip"
    assert result.provider_task_id == "task-1"
    assert result.data_id == "doc-1"
    assert [status.state for status in updates] == [
        MinerUTaskState.PENDING,
        MinerUTaskState.RUNNING,
        MinerUTaskState.RUNNING,
        MinerUTaskState.SUCCEEDED,
    ]
    assert [status.progress.extracted_pages for status in updates[1:3]] == [1, 2]
    assert task.state is MinerUTaskState.SUCCEEDED
    assert task.result is result
    assert len(session.requests) == 5
    # 先推进 interval（3 * 1.5），再乘抖动因子（0.5 + 0.5 * 0.5）。
    assert runtime.sleeps[0] == pytest.approx(3.375)


def test_parse_submits_and_waits():
    client, session, _ = make_client(
        [FakeResponse(submit_ok()), FakeResponse(done_ok())]
    )

    result = client.parse("https://example.com/doc.pdf", timeout=10)

    assert result.zip_url == "https://cdn.example/result.zip"
    assert [r["method"] for r in session.requests] == ["POST", "GET"]


def test_wait_failed_raises_and_is_idempotent():
    client, session, _ = make_client(
        [
            FakeResponse(submit_ok()),
            FakeResponse(trace_ok("failed", err_msg="bad pdf")),
        ]
    )
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUExecutionError, match="bad pdf"):
        task.wait(timeout=10)
    assert task.state is MinerUTaskState.FAILED
    assert task.result is None

    with pytest.raises(MinerUExecutionError, match="bad pdf"):
        task.wait(timeout=10)
    assert len(session.requests) == 2


def test_wait_cancelled_raises():
    client, _, _ = make_client(
        [
            FakeResponse(submit_ok()),
            FakeResponse(trace_ok("cancelled")),
        ]
    )
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUExecutionError, match="cancelled"):
        task.wait(timeout=10)


def test_timeout_carries_last_status():
    policy = PollPolicy(
        initial_interval=1.0,
        max_interval=1.0,
        backoff=1.0,
        jitter=0.0,
    )
    responses = [FakeResponse(submit_ok())] + [
        FakeResponse(trace_ok("pending")) for _ in range(20)
    ]
    client, _, runtime = make_client(responses, policy=policy)
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUTimeoutError) as excinfo:
        task.wait(timeout=5)

    assert excinfo.value.task_id == "task-1"
    assert excinfo.value.last_status is not None
    assert excinfo.value.last_status.state is MinerUTaskState.PENDING
    assert task.status is not None
    assert task.status.state is MinerUTaskState.PENDING
    assert runtime.now == pytest.approx(5.0)


def test_deadline_epoch_is_converted_to_budget():
    policy = PollPolicy(
        initial_interval=1.0,
        max_interval=1.0,
        backoff=1.0,
        jitter=0.0,
    )
    responses = [FakeResponse(submit_ok())] + [
        FakeResponse(trace_ok("pending")) for _ in range(20)
    ]
    client, _, runtime = make_client(responses, policy=policy)
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUTimeoutError):
        task.wait(deadline_epoch=1_000_003.0)

    assert runtime.now == pytest.approx(3.0)


def test_timeout_and_deadline_are_mutually_exclusive():
    client, session, _ = make_client([FakeResponse(submit_ok())])
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUConfigurationError, match="mutually exclusive"):
        task.wait(timeout=1, deadline_epoch=2)

    assert len(session.requests) == 1


def test_callback_exception_does_not_interrupt_polling():
    client, _, _ = make_client([FakeResponse(submit_ok()), FakeResponse(done_ok())])
    task = client.submit("https://example.com/doc.pdf")

    def boom(_status):
        raise RuntimeError("boom")

    result = task.wait(timeout=10, on_update=boom)
    assert result.zip_url == "https://cdn.example/result.zip"


# --- 错误重试与分类 -------------------------------------------------------


def test_transient_error_is_retried():
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse({"error": "boom"}, status_code=500),
        FakeResponse(trace_ok("pending")),
        FakeResponse(done_ok()),
    ]
    client, session, _ = make_client(responses)
    task = client.submit("https://example.com/doc.pdf")

    result = task.wait(timeout=60)

    assert result.zip_url == "https://cdn.example/result.zip"
    assert len([r for r in session.requests if r["method"] == "GET"]) == 3


def test_transient_errors_exhaust_retry_budget():
    policy = PollPolicy(max_consecutive_errors=2)
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse({"error": "boom"}, status_code=500),
        FakeResponse({"error": "boom"}, status_code=500),
    ]
    client, _, _ = make_client(responses, policy=policy)
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUExecutionError, match="2 consecutive times"):
        task.wait(timeout=60)


def test_retry_after_is_honored_and_capped():
    policy = PollPolicy(max_retry_after=5.0)
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse(
            {"error": "rate limited"},
            status_code=429,
            headers={"Retry-After": "30"},
        ),
        FakeResponse(done_ok()),
    ]
    client, _, runtime = make_client(responses, policy=policy)
    task = client.submit("https://example.com/doc.pdf")

    result = task.wait(timeout=60)

    assert result.zip_url == "https://cdn.example/result.zip"
    assert runtime.sleeps[0] == 5.0


def test_authentication_error_on_trace_is_not_retried():
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse({"error": "auth"}, status_code=401),
    ]
    client, session, _ = make_client(responses)
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUAuthenticationError):
        task.wait(timeout=10)

    assert len([r for r in session.requests if r["method"] == "GET"]) == 1


def test_gateway_auth_envelope_is_recognized():
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse(
            {
                "success": False,
                "msgCode": "A0202",
                "msg": "user authenticate failed",
            }
        ),
    ]
    client, _, _ = make_client(responses)
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUAuthenticationError, match="A0202"):
        task.wait(timeout=10)


def test_submit_5xx_is_terminal_and_not_retried():
    client, session, _ = make_client([FakeResponse({"error": "boom"}, status_code=500)])

    with pytest.raises(MinerUExecutionError):
        client.submit("https://example.com/doc.pdf")

    assert len(session.requests) == 1


def test_submit_quota_business_error():
    client, _, _ = make_client(
        [FakeResponse({"code": -60018, "msg": "quota exceeded"})]
    )

    with pytest.raises(MinerUQuotaError, match="quota"):
        client.submit("https://example.com/doc.pdf")


def test_done_without_zip_url_is_an_execution_error():
    client, _, _ = make_client(
        [FakeResponse(submit_ok()), FakeResponse(trace_ok("done"))]
    )
    task = client.submit("https://example.com/doc.pdf")

    with pytest.raises(MinerUExecutionError, match="full_zip_url"):
        task.wait(timeout=10)


def test_unknown_state_is_retried_as_transient():
    responses = [
        FakeResponse(submit_ok()),
        FakeResponse(trace_ok("mystery")),
        FakeResponse(done_ok()),
    ]
    client, _, _ = make_client(responses)
    task = client.submit("https://example.com/doc.pdf")

    result = task.wait(timeout=60)

    assert result.zip_url == "https://cdn.example/result.zip"


# --- Session 生命周期 -----------------------------------------------------


def test_client_manages_its_own_session(monkeypatch):
    session = FakeSession([FakeResponse(submit_ok()), FakeResponse(done_ok())])
    monkeypatch.setattr("mineru_parser.client.requests.Session", lambda: session)
    client = MinerUApiClient(api_key="test-key")

    result = client.parse("https://example.com/doc.pdf", timeout=10)
    client.close()

    assert result.zip_url == "https://cdn.example/result.zip"
    # 同一个 Session 贯穿提交与轮询。
    assert [r["method"] for r in session.requests] == ["POST", "GET"]
    assert session.closed is True


def test_injected_session_is_not_closed_by_client():
    client, session, _ = make_client([])

    with client:
        pass

    assert session.closed is False


# --- 配置 -----------------------------------------------------------------


def test_api_key_comes_from_environment(monkeypatch):
    monkeypatch.setenv("MINERU_API_KEY", "env-key")
    session = FakeSession([FakeResponse(submit_ok())])
    client = MinerUApiClient(session=session)

    client.submit("https://example.com/doc.pdf")

    assert session.requests[0]["headers"]["Authorization"] == "Bearer env-key"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("MINERU_API_KEY", raising=False)
    client = MinerUApiClient(session=FakeSession([]))

    with pytest.raises(MinerUAuthenticationError, match="MINERU_API_KEY"):
        client.submit("https://example.com/doc.pdf")


def test_invalid_configuration_is_rejected():
    with pytest.raises(MinerUConfigurationError):
        MinerUApiClient(api_key="   ")
    with pytest.raises(MinerUConfigurationError):
        MinerUApiClient(base_url="ftp://example.com")
    with pytest.raises(MinerUConfigurationError):
        MinerUApiClient(request_timeout=0)
    with pytest.raises(MinerUConfigurationError):
        PollPolicy(backoff=0.5)
    with pytest.raises(MinerUConfigurationError):
        PollPolicy(jitter=1.0)
    with pytest.raises(MinerUConfigurationError):
        PollPolicy(initial_interval=10.0, max_interval=5.0)
    with pytest.raises(MinerUConfigurationError):
        MinerUApiClient(base_url="https://mineru.net/api/v4?debug=1")


def test_parse_retry_after_supports_seconds_and_http_date():
    assert parse_retry_after("120", now=0.0) == 120.0
    assert parse_retry_after("", now=0.0) is None
    assert parse_retry_after("not-a-date", now=0.0) is None

    when = datetime(2015, 10, 21, 7, 28, tzinfo=UTC)
    header = "Wed, 21 Oct 2015 07:28:00 GMT"
    assert parse_retry_after(header, now=when.timestamp()) == 0.0
    assert parse_retry_after(header, now=when.timestamp() - 60) == 60.0
