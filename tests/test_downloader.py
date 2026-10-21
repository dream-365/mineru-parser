"""ResultDownloader 行为测试：假 Session / 假 Resolver / 假时钟，无网络。"""

from __future__ import annotations

import io
import ipaddress
import logging
import socket
from email.utils import formatdate
from urllib.parse import urlsplit

import pytest
import requests
import urllib3
from requests.structures import CaseInsensitiveDict

from mineru_parser import (
    DEFAULT_DOWNLOAD_RETRY_POLICY,
    DownloadRetryPolicy,
    ResultDownloadConfigurationError,
    ResultDownloadContentTypeError,
    ResultDownloader,
    ResultDownloadHTTPError,
    ResultDownloadSecurityError,
    ResultDownloadTimeoutError,
    ResultDownloadTooLargeError,
    ResultDownloadTransientError,
)

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"


# --- 测试替身 -------------------------------------------------------------


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks=(),
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})
        self._chunks = list(chunks)
        self._error = error
        self.closed = False
        self.reads = 0

    def iter_content(self, chunk_size):
        self.reads += 1
        if self._error is not None:
            raise self._error
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses=(), *, headers=None, auth=None, error=None) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.headers = headers or {}
        self.auth = auth
        self._error = error
        self.closed = False

    def get(self, url, **kwargs):
        self.requests.append({"method": "GET", "url": url, **kwargs})
        if self._error is not None:
            raise self._error
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.random_value = 0.5

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now

    def wall_clock(self) -> float:
        return 1_000_000.0 + self.now

    def random(self) -> float:
        return self.random_value


class RecordingResolver:
    def __init__(self, addresses=None, *, error: Exception | None = None) -> None:
        self.addresses = list([PUBLIC_IP] if addresses is None else addresses)
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int):
        self.calls.append((host, port))
        if self.error is not None:
            raise self.error
        return self.addresses


def make_downloader(responses=(), *, resolver=None, clock=None, **kwargs):
    session = FakeSession(responses)
    clock = clock or FakeClock()
    resolver = resolver or RecordingResolver()
    downloader = ResultDownloader(
        session=session,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
        random_fn=clock.random,
        dns_resolver=resolver,
        **kwargs,
    )
    return downloader, session, clock, resolver


# --- 构造与配置 -----------------------------------------------------------


def test_defaults():
    downloader, _, _, _ = make_downloader()
    assert downloader.max_bytes == 50 * 1024 * 1024
    assert downloader.retry_policy == DEFAULT_DOWNLOAD_RETRY_POLICY
    assert isinstance(downloader.retry_policy, DownloadRetryPolicy)
    assert downloader.retry_policy.max_attempts == 3
    downloader.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bytes": 0},
        {"max_bytes": -1},
        {"max_bytes": True},
        {"max_bytes": 1.5},
        {"chunk_size": 0},
        {"chunk_size": False},
    ],
)
def test_invalid_size_config_rejected(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_timeout": 0},
        {"request_timeout": True},
        {"request_timeout": (1.0, 0)},
        {"request_timeout": (float("inf"), 1.0)},
        {"request_timeout": "10"},
        {"total_timeout": 0},
        {"total_timeout": -1},
        {"total_timeout": False},
        {"total_timeout": (1.0, 2.0)},
    ],
)
def test_invalid_timeout_config_rejected(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), **kwargs)


def test_total_timeout_none_is_allowed():
    downloader, _, _, _ = make_downloader(total_timeout=None)
    downloader.close()


def test_retry_policy_must_be_instance():
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), retry_policy={"max_attempts": 2})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": True},
        {"initial_interval": 0},
        {"backoff": 0.5},
        {"max_interval": 0.1, "initial_interval": 1.0},
        {"jitter": 1.0},
        {"jitter": -0.1},
        {"jitter": float("nan")},
        {"max_retry_after": -1},
    ],
)
def test_retry_policy_validation(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        DownloadRetryPolicy(**kwargs)


def test_content_types_normalized():
    downloader, _, _, _ = make_downloader(
        allowed_content_types={" Application/ZIP ", "IMAGE/*", "*/*"}
    )
    assert downloader._allowed_content_types == frozenset(
        {"application/zip", "image/*", "*/*"}
    )
    downloader.close()


@pytest.mark.parametrize(
    "value",
    [
        set(),
        "application/zip",
        {"*/json"},
        {"text"},
        {"text/html; charset=utf-8"},
        {123},
        {""},
    ],
)
def test_invalid_content_types_rejected(value):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), allowed_content_types=value)


def test_allowed_hosts_normalized():
    downloader, _, _, _ = make_downloader(
        allowed_hosts={"EXAMPLE.com.", "[::1]", "bücher.example"}
    )
    assert downloader._allowed_hosts == frozenset(
        {"example.com", "::1", "xn--bcher-kva.example"}
    )
    downloader.close()


@pytest.mark.parametrize(
    "value",
    [
        set(),
        "example.com",
        {"https://example.com"},
        {"example.com:443"},
        {"*.example.com"},
        {"example.com/path"},
        {"exa mple.com"},
        {""},
        {"[not-an-ip]"},
    ],
)
def test_invalid_allowed_hosts_rejected(value):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), allowed_hosts=value)


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "example.com"},
        {"content-length": "1"},
        {"Transfer-Encoding": "chunked"},
        {"Connection": "keep-alive"},
        {"Range": "bytes=0-1"},
        {"Bad Header": "x"},
        {"X-Test": "a\r\nInjected: 1"},
        {"X-Test": 1},
        {1: "x"},
        {"X-Test": "a", "x-test": "b"},
    ],
)
def test_invalid_headers_rejected(headers):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), headers=headers)


def test_headers_are_copied():
    headers = {"X-Test": "original"}
    downloader, _, _, _ = make_downloader(headers=headers)
    headers["X-Test"] = "changed"
    assert downloader._headers["X-Test"] == "original"
    downloader.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sleep": None},
        {"monotonic": None},
        {"wall_clock": None},
        {"random_fn": None},
        {"dns_resolver": 42},
        {"on_metric": 42},
        {"correlation_id": 42},
    ],
)
def test_non_callable_injection_rejected(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_redirects": -1},
        {"max_redirects": True},
        {"allow_private_hosts": 1},
        {"allow_https_downgrade": "yes"},
    ],
)
def test_invalid_boolean_and_redirect_config_rejected(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), **kwargs)


def test_injected_session_with_sensitive_global_headers_rejected():
    for header in ("Authorization", "Proxy-Authorization", "Cookie", "Cookie2"):
        with pytest.raises(ResultDownloadConfigurationError):
            ResultDownloader(session=FakeSession(headers={header: "secret"}))


def test_injected_session_with_auth_rejected():
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(auth=("user", "pass")))


# --- 基本下载 -------------------------------------------------------------


def test_resolve_returns_bytesio_at_start_and_sends_expected_request():
    response = FakeResponse(headers={"Content-Length": "5"}, chunks=[b"hello"])
    downloader, session, _, _ = make_downloader([response])

    stream = downloader.resolve("https://example.com/result.zip?token=secret")

    assert isinstance(stream, io.BytesIO)
    assert stream.tell() == 0
    assert stream.read() == b"hello"
    assert response.closed

    request = session.requests[0]
    assert request["method"] == "GET"
    assert request["stream"] is True
    assert request["allow_redirects"] is False
    assert request["timeout"] == (5.0, 30.0)
    assert request["headers"]["Accept-Encoding"] == "identity"
    assert request["headers"]["Accept"] == "*/*"
    assert request["headers"]["User-Agent"].startswith("mineru-parser/")


def test_user_headers_override_defaults_without_mutating_session():
    response = FakeResponse(chunks=[b"ok"])
    downloader, session, _, _ = make_downloader(
        [response], headers={"Accept-Encoding": "gzip", "X-Test": "1"}
    )
    downloader.resolve("https://example.com/x")
    assert session.requests[0]["headers"]["Accept-Encoding"] == "gzip"
    assert session.requests[0]["headers"]["X-Test"] == "1"
    assert session.headers == {}


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "http://user:pass@example.com/x",
        "http://@example.com/x",
        "http://example.com:0/x",
        "http://example.com:70000/x",
        "http://exa mple.com/x",
        "http://exa\\mple.com/x",
        "http://exa%6dple.com/x",
        "https://example.com/a\nb",
        "https://example.com/a\x00b",
        "https://example.com/a\x7fb",
        "not-a-url",
    ],
)
def test_invalid_url_fails_before_http(url):
    downloader, session, _, _ = make_downloader()
    with pytest.raises(ResultDownloadConfigurationError):
        downloader.resolve(url)
    assert session.requests == []


def test_non_string_url_rejected():
    downloader, session, _, _ = make_downloader()
    with pytest.raises(ResultDownloadConfigurationError):
        downloader.resolve(123)
    assert session.requests == []


def test_sequential_calls_return_independent_buffers():
    first = FakeResponse(headers={"Content-Length": "3"}, chunks=[b"one"])
    second = FakeResponse(headers={"Content-Length": "3"}, chunks=[b"two"])
    downloader, _, _, _ = make_downloader([first, second])

    stream_one = downloader.resolve("https://example.com/a")
    stream_two = downloader.resolve("https://example.com/b")

    assert stream_one.read() == b"one"
    assert stream_two.read() == b"two"
    assert stream_one.tell() == 3


# --- 流式读取与大小上限 ---------------------------------------------------


def test_content_length_over_limit_fails_early():
    response = FakeResponse(headers={"Content-Length": "100"}, chunks=[b"x" * 100])
    downloader, _, _, _ = make_downloader([response], max_bytes=10)

    with pytest.raises(ResultDownloadTooLargeError) as info:
        downloader.resolve("https://example.com/big")

    assert info.value.max_bytes == 10
    assert info.value.declared_bytes == 100
    assert info.value.received_bytes is None
    assert response.reads == 0
    assert response.closed


def test_streamed_size_limit_aborts():
    response = FakeResponse(chunks=[b"x" * 8, b"y" * 8])
    downloader, _, _, _ = make_downloader([response], max_bytes=10)

    with pytest.raises(ResultDownloadTooLargeError) as info:
        downloader.resolve("https://example.com/big")

    assert info.value.received_bytes == 16
    assert info.value.declared_bytes is None


def test_incomplete_body_is_retried():
    incomplete = FakeResponse(headers={"Content-Length": "10"}, chunks=[b"12345"])
    complete = FakeResponse(headers={"Content-Length": "10"}, chunks=[b"1234567890"])
    downloader, session, _, _ = make_downloader(
        [incomplete, complete],
        retry_policy=DownloadRetryPolicy(max_attempts=2, jitter=0.0),
    )

    stream = downloader.resolve("https://example.com/x")

    assert stream.read() == b"1234567890"
    assert len(session.requests) == 2
    assert incomplete.closed


def test_incomplete_body_exhaustion_is_transient():
    downloader, session, _, _ = make_downloader(
        [
            FakeResponse(headers={"Content-Length": "10"}, chunks=[b"1"]),
            FakeResponse(headers={"Content-Length": "10"}, chunks=[b"2"]),
        ],
        retry_policy=DownloadRetryPolicy(max_attempts=2, jitter=0.0),
    )

    with pytest.raises(ResultDownloadTransientError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.attempts == 2
    assert len(session.requests) == 2
    assert "incomplete body" in (info.value.last_error or "")


def test_partial_content_is_rejected():
    downloader, session, _, _ = make_downloader([FakeResponse(status_code=206)])

    with pytest.raises(ResultDownloadHTTPError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.status_code == 206
    assert len(session.requests) == 1


def test_empty_204_returns_empty_stream():
    downloader, _, _, _ = make_downloader([FakeResponse(status_code=204)])

    stream = downloader.resolve("https://example.com/x")

    assert isinstance(stream, io.BytesIO)
    assert stream.tell() == 0
    assert stream.read() == b""


def test_zero_content_length_skips_content_type_check():
    response = FakeResponse(headers={"Content-Length": "0"})
    downloader, _, _, _ = make_downloader(
        [response], allowed_content_types={"application/zip"}
    )

    stream = downloader.resolve("https://example.com/x")

    assert stream.read() == b""
    assert response.reads == 0


def test_transfer_encoding_makes_content_length_unusable():
    response = FakeResponse(
        headers={
            "Transfer-Encoding": "chunked",
            "Content-Length": "999",
        },
        chunks=[b"ok"],
    )
    downloader, _, _, _ = make_downloader([response], max_bytes=100)

    assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_chunk_size_is_capped_by_max_bytes():
    class RecordingResponse(FakeResponse):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.chunk_sizes: list[int] = []

        def iter_content(self, chunk_size):
            self.chunk_sizes.append(chunk_size)
            yield from super().iter_content(chunk_size)

    response = RecordingResponse(chunks=[b"ok"])
    downloader, _, _, _ = make_downloader([response], max_bytes=4, chunk_size=64)

    downloader.resolve("https://example.com/x")

    assert response.chunk_sizes == [4]


# --- 重试与状态码 ---------------------------------------------------------


def test_retryable_statuses_retry_with_backoff_and_jitter():
    responses = [
        FakeResponse(status_code=503),
        FakeResponse(status_code=503),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, clock, _ = make_downloader(
        responses,
        retry_policy=DownloadRetryPolicy(
            max_attempts=3, initial_interval=0.5, backoff=2.0, jitter=0.2
        ),
    )
    clock.random_value = 0.5

    stream = downloader.resolve("https://example.com/x")

    assert stream.read() == b"ok"
    assert len(session.requests) == 3
    # d1 = 0.5 * 0.9, d2 = 1.0 * 0.9
    assert clock.sleeps == pytest.approx([0.45, 0.9])
    assert [item["url"] for item in session.requests] == ["https://example.com/x"] * 3


def test_terminal_4xx_is_not_retried():
    downloader, session, _, _ = make_downloader([FakeResponse(status_code=404)])

    with pytest.raises(ResultDownloadHTTPError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.status_code == 404
    assert len(session.requests) == 1


def test_retry_after_seconds_is_honored_without_jitter():
    responses = [
        FakeResponse(status_code=503, headers={"Retry-After": "2"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(responses)

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [2.0]


def test_retry_after_is_capped():
    responses = [
        FakeResponse(status_code=503, headers={"Retry-After": "999"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(
        responses,
        retry_policy=DownloadRetryPolicy(max_retry_after=5.0),
    )

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [5.0]


def test_retry_after_http_date_is_supported():
    retry_at = formatdate(1_000_005, usegmt=True)
    responses = [
        FakeResponse(status_code=503, headers={"Retry-After": retry_at}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(responses)

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [5.0]


def test_retry_exhaustion_reports_last_error():
    downloader, session, _, _ = make_downloader(
        [FakeResponse(status_code=503), FakeResponse(status_code=503)],
        retry_policy=DownloadRetryPolicy(max_attempts=2),
    )

    with pytest.raises(ResultDownloadTransientError) as info:
        downloader.resolve("https://example.com/x?token=secret")

    assert info.value.attempts == 2
    assert info.value.last_status_code == 503
    assert info.value.last_error == "HTTP 503"
    assert "secret" not in str(info.value)
    assert len(session.requests) == 2


def test_read_timeout_exhaustion_is_timeout_error():
    downloader, _, _, _ = make_downloader(
        [
            requests.ReadTimeout("https://example.com/x?token=secret"),
            requests.ReadTimeout("https://example.com/x?token=secret"),
        ],
        retry_policy=DownloadRetryPolicy(max_attempts=2),
        total_timeout=None,
    )

    with pytest.raises(ResultDownloadTimeoutError) as info:
        downloader.resolve("https://example.com/x?token=secret")

    assert info.value.attempts == 2
    assert info.value.last_error == "ReadTimeout"
    assert "secret" not in str(info.value)
    assert info.value.__cause__ is None


def test_ssl_error_is_terminal_security_error():
    downloader, session, clock, _ = make_downloader(
        [requests.exceptions.SSLError("bad cert https://example.com/x?token=s")]
    )

    with pytest.raises(ResultDownloadSecurityError) as info:
        downloader.resolve("https://example.com/x?token=secret")

    assert len(session.requests) == 1
    assert clock.sleeps == []
    assert "secret" not in str(info.value)
    assert info.value.__cause__ is None


def test_random_fn_non_finite_is_treated_as_zero():
    responses = [
        FakeResponse(status_code=503),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(
        responses,
        retry_policy=DownloadRetryPolicy(initial_interval=2.0, jitter=0.5, backoff=1.0),
    )
    clock.random_value = float("nan")

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [1.0]


# --- 超时 -----------------------------------------------------------------


def test_total_timeout_before_retry_raises_immediately():
    downloader, session, clock, _ = make_downloader(
        [FakeResponse(status_code=503), FakeResponse()],
        retry_policy=DownloadRetryPolicy(
            max_attempts=3, initial_interval=10.0, max_interval=10.0, jitter=0.0
        ),
        total_timeout=1.0,
    )

    with pytest.raises(ResultDownloadTimeoutError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.last_status_code == 503
    assert info.value.attempts == 1
    assert clock.sleeps == []
    assert len(session.requests) == 1


def test_read_timeout_does_not_return_partial_buffer():
    downloader, _, _, _ = make_downloader(
        [FakeResponse(chunks=[b"partial", requests.ReadTimeout("secret")])],
        retry_policy=DownloadRetryPolicy(max_attempts=1),
    )

    with pytest.raises(ResultDownloadTimeoutError) as info:
        downloader.resolve("https://example.com/x")

    assert "secret" not in str(info.value)


# --- SSRF / URL 安全 ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/x",
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/x",
        "http://224.0.0.1/x",
        "http://[::1]/x",
        "http://[ff02::1]/x",
        "http://[64:ff9b::a00:1]/x",
        "http://[2002:c000:204::]/x",
        "http://[2001::1]/x",
        "http://[::ffff:10.0.0.1]/x",
        "http://[fd00:ec2::254]/x",
    ],
)
def test_non_public_ip_literals_rejected(url):
    resolver = RecordingResolver()
    downloader, session, _, _ = make_downloader(resolver=resolver)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve(url)

    assert resolver.calls == []
    assert session.requests == []


def test_public_ip_literal_skips_resolver():
    resolver = RecordingResolver(error=AssertionError("resolver must not run"))
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, session, _, _ = make_downloader([response], resolver=resolver)

    assert downloader.resolve(f"http://{PUBLIC_IP}/data").read() == b"ok"
    assert session.requests[0]["url"] == f"http://{PUBLIC_IP}/data"


def test_dns_mixed_public_and_private_is_rejected():
    resolver = RecordingResolver([PUBLIC_IP, "10.0.0.5"])
    downloader, session, _, _ = make_downloader(resolver=resolver)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/x")

    assert session.requests == []


def test_dns_invalid_result_fails_closed():
    resolver = RecordingResolver(["not-an-ip"])
    downloader, session, _, _ = make_downloader(resolver=resolver)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/x")

    assert len(resolver.calls) == 1
    assert session.requests == []


def test_dns_empty_result_is_retried_then_transient():
    resolver = RecordingResolver([])
    downloader, session, _, _ = make_downloader(
        resolver=resolver,
        retry_policy=DownloadRetryPolicy(max_attempts=2, jitter=0.0),
    )

    with pytest.raises(ResultDownloadTransientError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.last_error == "DNS resolution failed."
    assert len(resolver.calls) == 2
    assert session.requests == []


def test_dns_gaierror_is_retried():
    resolver = RecordingResolver(error=socket.gaierror("temporary failure"))
    downloader, session, _, _ = make_downloader(
        resolver=resolver,
        retry_policy=DownloadRetryPolicy(max_attempts=2, jitter=0.0),
    )

    with pytest.raises(ResultDownloadTransientError):
        downloader.resolve("https://example.com/x")

    assert len(resolver.calls) == 2
    assert session.requests == []


def test_idna_host_is_canonicalized_everywhere():
    resolver = RecordingResolver()
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, session, _, _ = make_downloader(
        [response],
        resolver=resolver,
        allowed_hosts={"BÜCHER.example."},
    )

    downloader.resolve("https://bücher.example/result")

    assert resolver.calls == [("xn--bcher-kva.example", 443)]
    assert session.requests[0]["url"] == "https://xn--bcher-kva.example/result"


def test_idna_failure_is_security_error():
    downloader, session, _, _ = make_downloader()

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("http://foo_bar.example/x")

    assert session.requests == []


def test_allowed_hosts_mismatch_is_security_error():
    downloader, session, _, _ = make_downloader(allowed_hosts={"example.com"})

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://other.example/x")

    assert session.requests == []


def test_allow_private_hosts_skips_ip_checks():
    resolver = RecordingResolver(["127.0.0.1"])
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader(
        [response], resolver=resolver, allow_private_hosts=True
    )

    assert downloader.resolve("https://internal.example/x").read() == b"ok"


def test_allow_private_hosts_still_rejects_bad_scheme():
    downloader, session, _, _ = make_downloader(allow_private_hosts=True)

    with pytest.raises(ResultDownloadConfigurationError):
        downloader.resolve("ftp://127.0.0.1/x")

    assert session.requests == []


# --- 重定向 ---------------------------------------------------------------


def test_redirect_is_followed_and_validated():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "https://cdn.example/x"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(responses)

    assert downloader.resolve("https://example.com/start").read() == b"ok"
    assert [item["url"] for item in session.requests] == [
        "https://example.com/start",
        "https://cdn.example/x",
    ]


def test_relative_redirect_is_resolved():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "/next"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(responses)

    downloader.resolve("https://example.com/start")

    assert session.requests[1]["url"] == "https://example.com/next"


def test_redirect_target_is_revalidated():
    # 同 scheme 跳转到私网地址：必须由 validate_target 的 IP 校验拦截，
    # 而不是先被 HTTPS->HTTP 降级检查拦下。
    responses = [
        FakeResponse(status_code=302, headers={"Location": "https://127.0.0.1/x"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(responses)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/start")

    assert len(session.requests) == 1


def test_redirect_target_is_validated_once_per_hop():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "https://cdn.example/x"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, _, resolver = make_downloader(responses)

    downloader.resolve("https://example.com/start")

    assert resolver.calls == [("example.com", 443), ("cdn.example", 443)]


def test_redirect_limit_is_enforced():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "/a"}),
        FakeResponse(status_code=302, headers={"Location": "/b"}),
    ]
    downloader, session, _, _ = make_downloader(responses, max_redirects=1)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/start")

    assert len(session.requests) == 2


def test_missing_location_is_http_error():
    downloader, _, _, _ = make_downloader([FakeResponse(status_code=302)])

    with pytest.raises(ResultDownloadHTTPError) as info:
        downloader.resolve("https://example.com/start")

    assert info.value.status_code == 302


def test_non_http_redirect_is_security_error():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "file:///etc/passwd"}),
    ]
    downloader, session, _, _ = make_downloader(responses)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/start")

    assert len(session.requests) == 1


def test_https_downgrade_is_rejected_by_default():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "http://example.com/x"}),
    ]
    downloader, session, _, _ = make_downloader(responses)

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/start")

    assert len(session.requests) == 1


def test_https_downgrade_can_be_allowed():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "http://example.com/x"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(responses, allow_https_downgrade=True)

    assert downloader.resolve("https://example.com/start").read() == b"ok"
    assert session.requests[1]["url"] == "http://example.com/x"


def test_cross_origin_redirect_drops_sensitive_headers():
    responses = [
        FakeResponse(
            status_code=302, headers={"Location": "https://other.example/next"}
        ),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(
        responses,
        headers={
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "X-Keep": "yes",
        },
    )

    downloader.resolve("https://example.com/start")

    assert "Authorization" in session.requests[0]["headers"]
    assert "Cookie" in session.requests[0]["headers"]
    second = session.requests[1]["headers"]
    assert "Authorization" not in second
    assert "Cookie" not in second
    assert second["X-Keep"] == "yes"


def test_same_origin_redirect_keeps_sensitive_headers():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "/next"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(
        responses, headers={"Authorization": "Bearer secret"}
    )

    downloader.resolve("https://example.com/start")

    assert session.requests[1]["headers"]["Authorization"] == "Bearer secret"


# --- Content-Type 白名单 --------------------------------------------------


def test_content_type_exact_match():
    response = FakeResponse(
        headers={
            "Content-Type": "application/zip; charset=binary",
            "Content-Length": "2",
        },
        chunks=[b"ok"],
    )
    downloader, _, _, _ = make_downloader(
        [response], allowed_content_types={"application/zip"}
    )

    assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_content_type_wildcard_match():
    for content_type in ("image/png", "text/html"):
        response = FakeResponse(
            headers={"Content-Type": content_type, "Content-Length": "2"},
            chunks=[b"ok"],
        )
        downloader, _, _, _ = make_downloader(
            [response], allowed_content_types={"image/*", "text/*"}
        )
        assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_content_type_mismatch_is_terminal():
    response = FakeResponse(
        headers={"Content-Type": "text/html", "Content-Length": "2"},
        chunks=[b"ok"],
    )
    downloader, session, _, _ = make_downloader(
        [response], allowed_content_types={"application/zip"}
    )

    with pytest.raises(ResultDownloadContentTypeError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.content_type == "text/html"
    assert info.value.allowed == ("application/zip",)
    assert len(session.requests) == 1
    assert response.reads == 0


def test_missing_content_type_is_rejected():
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader(
        [response], allowed_content_types={"application/zip"}
    )

    with pytest.raises(ResultDownloadContentTypeError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.content_type is None


# --- 会话生命周期与依赖注入 ----------------------------------------------


def test_injected_session_is_not_closed():
    session = FakeSession()
    downloader = ResultDownloader(session=session, dns_resolver=RecordingResolver())
    downloader.close()
    downloader.close()
    assert session.closed is False


def test_owned_session_is_closed(monkeypatch):
    class TrackingSession(requests.Session):
        closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(requests, "Session", TrackingSession)
    downloader = ResultDownloader(dns_resolver=RecordingResolver())
    session = downloader._session
    downloader.close()
    assert session.closed is True


def test_context_manager_closes_owned_session(monkeypatch):
    class TrackingSession(requests.Session):
        closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(requests, "Session", TrackingSession)
    with ResultDownloader(dns_resolver=RecordingResolver()) as downloader:
        session = downloader._session
    assert session.closed is True


def test_resolver_receives_canonical_host_and_effective_port():
    resolver = RecordingResolver()
    downloader, _, _, _ = make_downloader(
        [FakeResponse(headers={"Content-Length": "0"})], resolver=resolver
    )

    downloader.resolve("http://example.com/x")

    assert resolver.calls == [("example.com", 80)]


# --- 遥测 -----------------------------------------------------------------


def test_success_metrics_are_emitted_exactly_once():
    metrics = []
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader(
        [response],
        on_metric=lambda name, value, tags: metrics.append((name, value, dict(tags))),
    )

    downloader.resolve("https://example.com/x")

    names = [item[0] for item in metrics]
    assert names == [
        "mineru.download.total",
        "mineru.download.duration_ms",
        "mineru.download.bytes",
        "mineru.download.attempts",
    ]
    assert all(item[2] == {"outcome": "success"} for item in metrics)
    assert metrics[2][1] == 2
    assert metrics[3][1] == 1


def test_config_error_metrics_are_emitted_in_finally():
    metrics = []
    downloader, _, _, _ = make_downloader(
        on_metric=lambda name, value, tags: metrics.append((name, value, dict(tags)))
    )

    with pytest.raises(ResultDownloadConfigurationError):
        downloader.resolve("ftp://example.com/x")

    assert len(metrics) == 4
    assert all(item[2]["outcome"] == "config_error" for item in metrics)
    assert metrics[3][1] == 0


def test_security_error_outcome():
    metrics = []
    downloader, _, _, _ = make_downloader(
        on_metric=lambda name, value, tags: metrics.append((name, value, dict(tags)))
    )

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("http://127.0.0.1/x")

    assert metrics[0][2]["outcome"] == "security_error"


def test_metric_hook_failure_is_swallowed():
    def broken_hook(name, value, tags):
        raise RuntimeError("metrics down")

    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader([response], on_metric=broken_hook)

    assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_retry_metric_is_emitted():
    metrics = []
    responses = [
        FakeResponse(status_code=503),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, _, _ = make_downloader(
        responses,
        on_metric=lambda name, value, tags: metrics.append((name, value, dict(tags))),
    )

    downloader.resolve("https://example.com/x")

    retry_metrics = [
        item for item in metrics if item[0] == "mineru.download.retry.total"
    ]
    assert retry_metrics == [
        (
            "mineru.download.retry.total",
            1.0,
            {"error_type": "HTTPStatus", "status_class": "5xx"},
        )
    ]


def test_logs_redact_query_and_fragment(caplog):
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader([response])

    with caplog.at_level(logging.DEBUG, logger="mineru_parser"):
        downloader.resolve("https://example.com/file.zip?token=topsecret#frag")

    assert "topsecret" not in caplog.text
    assert "frag" not in caplog.text
    records = [
        item for item in caplog.records if item.getMessage() == "mineru.download"
    ]
    assert records
    assert records[0].url == "https://example.com/file.zip"


def test_error_message_and_url_field_are_redacted():
    downloader, _, _, _ = make_downloader([FakeResponse(status_code=404)])

    with pytest.raises(ResultDownloadHTTPError) as info:
        downloader.resolve("https://example.com/file.zip?token=topsecret")

    assert "topsecret" not in str(info.value)
    assert info.value.url == "https://example.com/file.zip"


def test_transport_error_summary_does_not_leak_exception_text():
    error = requests.ConnectionError("failed https://example.com/x?token=topsecret")
    downloader, _, _, _ = make_downloader(
        [error], retry_policy=DownloadRetryPolicy(max_attempts=1)
    )

    with pytest.raises(ResultDownloadTransientError) as info:
        downloader.resolve("https://example.com/x?token=topsecret")

    assert "topsecret" not in str(info.value)
    assert "topsecret" not in (info.value.last_error or "")
    assert info.value.__cause__ is None


def test_metrics_tags_do_not_include_url_or_correlation_id():
    seen_tags = []
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader(
        [response],
        correlation_id="cid-1",
        on_metric=lambda name, value, tags: seen_tags.append(dict(tags)),
    )

    downloader.resolve("https://example.com/x?token=secret")

    for tags in seen_tags:
        assert set(tags).issubset({"outcome"})


def test_correlation_id_is_attached_to_logs(caplog):
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader([response], correlation_id="cid-1")

    with caplog.at_level(logging.INFO, logger="mineru_parser"):
        downloader.resolve("https://example.com/x")

    records = [
        item for item in caplog.records if item.getMessage() == "mineru.download"
    ]
    assert records
    assert records[0].correlation_id == "cid-1"


def test_unexpected_exception_propagates_and_is_measured():
    metrics = []

    class ExplodingSession(FakeSession):
        def get(self, url, **kwargs):
            raise ValueError("boom")

    session = ExplodingSession()
    downloader = ResultDownloader(
        session=session,
        dns_resolver=RecordingResolver(),
        on_metric=lambda name, value, tags: metrics.append((name, value, dict(tags))),
    )

    with pytest.raises(ValueError):
        downloader.resolve("https://example.com/x")

    assert metrics[0][2]["outcome"] == "unexpected"


def test_resolve_reuses_same_session_across_retries_and_redirects():
    responses = [
        FakeResponse(status_code=503),
        FakeResponse(status_code=302, headers={"Location": "/next"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(
        responses, retry_policy=DownloadRetryPolicy(max_attempts=2)
    )

    downloader.resolve("https://example.com/start")

    assert len(session.requests) == 3
    assert session.closed is False
    assert downloader._session is session


def test_resolved_final_url_is_canonicalized():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "/Next%20Page"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(responses)

    downloader.resolve("https://Example.COM/start")

    assert session.requests[0]["url"] == "https://example.com/start"
    assert session.requests[1]["url"] == "https://example.com/Next%20Page"
    assert urlsplit(session.requests[1]["url"]).hostname == "example.com"


def test_invalid_retry_after_is_ignored():
    responses = [
        FakeResponse(status_code=503, headers={"Retry-After": "not-a-date"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(
        responses,
        retry_policy=DownloadRetryPolicy(initial_interval=0.5, jitter=0.0),
    )

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [0.5]


def test_responses_are_closed_on_retry_and_redirect_paths():
    retry = FakeResponse(status_code=503)
    redirect = FakeResponse(status_code=302, headers={"Location": "/next"})
    success = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader(
        [retry, redirect, success],
        retry_policy=DownloadRetryPolicy(max_attempts=2),
    )

    downloader.resolve("https://example.com/x")

    assert retry.closed
    assert redirect.closed
    assert success.closed


def test_redirect_budget_resets_per_attempt():
    responses = [
        FakeResponse(status_code=302, headers={"Location": "/a"}),
        FakeResponse(status_code=429),
        FakeResponse(status_code=302, headers={"Location": "/b"}),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, session, _, _ = make_downloader(
        responses,
        max_redirects=1,
        retry_policy=DownloadRetryPolicy(max_attempts=2),
    )

    assert downloader.resolve("https://example.com/start").read() == b"ok"
    assert [item["url"] for item in session.requests] == [
        "https://example.com/start",
        "https://example.com/a",
        "https://example.com/start",
        "https://example.com/b",
    ]


def test_non_identity_content_encoding_makes_content_length_unusable():
    response = FakeResponse(
        headers={
            "Content-Encoding": "gzip",
            "Content-Length": "999",
        },
        chunks=[b"ok"],
    )
    downloader, _, _, _ = make_downloader([response], max_bytes=100)

    assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_lowercase_user_header_overrides_default_without_duplicate():
    response = FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"])
    downloader, session, _, _ = make_downloader(
        [response], headers={"accept-encoding": "gzip"}
    )

    downloader.resolve("https://example.com/x")

    headers = session.requests[0]["headers"]
    assert headers["accept-encoding"] == "gzip"
    assert [key.lower() for key in headers].count("accept-encoding") == 1


def test_allow_private_hosts_does_not_bypass_allowed_hosts():
    downloader, session, _, _ = make_downloader(
        allowed_hosts={"example.com"}, allow_private_hosts=True
    )

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://other.example/x")

    assert session.requests == []


def test_allow_private_hosts_still_rejects_invalid_dns_results():
    resolver = RecordingResolver(["not-an-ip"])
    downloader, session, _, _ = make_downloader(
        resolver=resolver, allow_private_hosts=True
    )

    with pytest.raises(ResultDownloadSecurityError):
        downloader.resolve("https://example.com/x")

    assert session.requests == []


def test_content_type_star_star_matches_anything():
    response = FakeResponse(
        headers={"Content-Type": "application/octet-stream"},
        chunks=[b"ok"],
    )
    downloader, _, _, _ = make_downloader([response], allowed_content_types={"*/*"})

    assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_empty_location_is_http_error():
    downloader, _, _, _ = make_downloader(
        [FakeResponse(status_code=302, headers={"Location": "  "})]
    )

    with pytest.raises(ResultDownloadHTTPError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.status_code == 302


@pytest.mark.parametrize("value", ["-1", "abc", "1, 1", "", "1_0"])
def test_unusable_content_length_falls_back_to_stream_count(value):
    response = FakeResponse(headers={"Content-Length": value}, chunks=[b"ok"])
    downloader, _, _, _ = make_downloader([response], max_bytes=100)

    assert downloader.resolve("https://example.com/x").read() == b"ok"


def test_memory_bound_is_close_to_max_bytes():
    import tracemalloc

    payload = b"x" * (1024 * 1024)
    response = FakeResponse(
        headers={"Content-Length": str(len(payload))},
        chunks=[payload],
    )
    downloader, _, _, _ = make_downloader(
        [response], max_bytes=len(payload), chunk_size=64 * 1024
    )

    tracemalloc.start()
    try:
        stream = downloader.resolve("https://example.com/x")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert stream.read() == payload
    # 目标上界为 O(max_bytes + chunk_size)；BytesIO 扩容会带来常数倍放大，
    # 这里用 8x 的宽松阈值记录实测上界。
    assert peak < 8 * len(payload)


# --- 回归测试：超时 / 异常上下文 / 日志安全 ---------------------------------


class FakeRaw:
    """模拟 urllib3 ``HTTPResponse`` 的增量读取接口。"""

    def __init__(self, chunks=(), *, clock=None, error=None) -> None:
        self.chunks = list(chunks)
        self.clock = clock
        self.error = error
        self.reads = 0

    def read1(self, amount, decode_content=False):
        self.reads += 1
        if self.clock is not None:
            self.clock.now += 10.0
        if self.error is not None:
            raise self.error
        return self.chunks.pop(0) if self.chunks else b""


class RawResponse(FakeResponse):
    def __init__(self, raw, **kwargs) -> None:
        super().__init__(**kwargs)
        self.raw = raw


class DripResponse(FakeResponse):
    """每次产出 chunk 前推进假时钟，模拟慢速响应体。"""

    def __init__(self, clock, **kwargs) -> None:
        super().__init__(**kwargs)
        self.clock = clock

    def iter_content(self, chunk_size):
        for chunk in self._chunks:
            self.clock.now += 10.0
            yield chunk


def test_total_timeout_is_checked_after_blocking_get():
    clock = FakeClock()
    response = FakeResponse(status_code=204)

    class SlowSession(FakeSession):
        def get(self, url, **kwargs):
            clock.now += 5.0
            return super().get(url, **kwargs)

    session = SlowSession([response])
    downloader = ResultDownloader(
        session=session,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
        random_fn=clock.random,
        dns_resolver=RecordingResolver(),
        total_timeout=1.0,
        retry_policy=DownloadRetryPolicy(max_attempts=1),
    )

    with pytest.raises(ResultDownloadTimeoutError):
        downloader.resolve("https://example.com/x")

    assert response.closed


def test_raw_read_timeout_is_timeout_error():
    raw = FakeRaw(
        error=urllib3.exceptions.ReadTimeoutError(None, "/x", "timed out")
    )
    response = RawResponse(raw, headers={"Content-Length": "5"})
    downloader, _, _, _ = make_downloader(
        [response],
        retry_policy=DownloadRetryPolicy(max_attempts=1),
        total_timeout=None,
    )

    with pytest.raises(ResultDownloadTimeoutError):
        downloader.resolve("https://example.com/x?token=secret")

    assert response.closed


def test_wrapped_stream_read_timeout_is_timeout_error():
    inner = urllib3.exceptions.ReadTimeoutError(None, "/x", "timed out")
    response = FakeResponse(chunks=[requests.ConnectionError(inner)])
    downloader, _, _, _ = make_downloader(
        [response],
        retry_policy=DownloadRetryPolicy(max_attempts=1),
        total_timeout=None,
    )

    with pytest.raises(ResultDownloadTimeoutError):
        downloader.resolve("https://example.com/x?token=secret")


def test_retry_timeout_does_not_retain_transport_exception():
    downloader, _, _, _ = make_downloader(
        [requests.ConnectTimeout("https://example.com/x?token=SECRET")],
        retry_policy=DownloadRetryPolicy(
            max_attempts=2,
            initial_interval=10.0,
            max_interval=10.0,
            jitter=0.0,
        ),
        total_timeout=2.0,
    )

    with pytest.raises(ResultDownloadTimeoutError) as info:
        downloader.resolve("https://example.com/x?token=SECRET")

    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_timeout_during_body_preserves_last_status_and_retry_after():
    clock = FakeClock()
    first = FakeResponse(status_code=503, headers={"Retry-After": "1"})
    second = DripResponse(
        clock, headers={"Content-Length": "2"}, chunks=[b"ok"]
    )
    downloader, _, _, _ = make_downloader(
        [first, second],
        clock=clock,
        retry_policy=DownloadRetryPolicy(
            max_attempts=2, initial_interval=0.5, jitter=0.0
        ),
        total_timeout=5.0,
    )

    with pytest.raises(ResultDownloadTimeoutError) as info:
        downloader.resolve("https://example.com/x")

    assert info.value.last_status_code == 503
    assert info.value.retry_after == 1.0


def test_raw_read1_streams_to_completion():
    raw = FakeRaw([b"he", b"llo"])
    response = RawResponse(raw, headers={"Content-Length": "5"})
    downloader, _, _, _ = make_downloader([response])

    assert downloader.resolve("https://example.com/x").read() == b"hello"
    assert raw.reads == 3


def test_raw_read1_checks_deadline_between_partial_chunks():
    clock = FakeClock()
    raw = FakeRaw([b"a", b"b"], clock=clock)
    response = RawResponse(
        raw, headers={"Content-Length": "2"}
    )
    downloader, _, _, _ = make_downloader(
        [response],
        clock=clock,
        total_timeout=5.0,
        retry_policy=DownloadRetryPolicy(max_attempts=1),
    )

    with pytest.raises(ResultDownloadTimeoutError):
        downloader.resolve("https://example.com/x")

    assert raw.reads == 1
    assert response.closed


def test_transition_networks_rejected_even_if_ipaddress_reports_public(
    monkeypatch,
):
    from mineru_parser.downloader import security

    for name in (
        "is_global",
        "is_private",
        "is_loopback",
        "is_link_local",
        "is_multicast",
        "is_reserved",
        "is_unspecified",
        "is_site_local",
    ):
        monkeypatch.setattr(
            ipaddress.IPv6Address,
            name,
            property(lambda self, _name=name: _name == "is_global"),
        )

    for address in ("64:ff9b::a00:1", "2002:c000:204::", "2001::1"):
        assert security._is_public_ip(ipaddress.ip_address(address)) is False


def test_injected_session_with_bytes_sensitive_header_rejected():
    for header in (b"Authorization", b"Proxy-Authorization", b"Cookie", b"Cookie2"):
        with pytest.raises(ResultDownloadConfigurationError):
            ResultDownloader(session=FakeSession(headers={header: "secret"}))


def test_absurd_retry_after_date_is_ignored():
    responses = [
        FakeResponse(
            status_code=503,
            headers={"Retry-After": "Mon, 01 Jan 999999999999 00:00:00 GMT"},
        ),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(
        responses,
        retry_policy=DownloadRetryPolicy(initial_interval=0.5, jitter=0.0),
    )

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [0.5]


@pytest.mark.parametrize("char", ["\x1b", "\x9b", "\x00", "\x7f"])
def test_control_chars_are_rejected_and_not_logged(char, caplog):
    downloader, session, _, _ = make_downloader()
    url = f"https://example.com/a{char}b?token=secret"

    with caplog.at_level(logging.DEBUG, logger="mineru_parser"):
        with pytest.raises(ResultDownloadConfigurationError):
            downloader.resolve(url)

    assert session.requests == []
    assert char not in caplog.text
    for record in caplog.records:
        assert char not in getattr(record, "url", "")


def test_retry_delay_exponent_overflow_is_capped():
    policy = DownloadRetryPolicy(
        backoff=1e6,
        max_attempts=2000,
        initial_interval=1.0,
        max_interval=8.0,
        jitter=0.0,
    )

    assert policy.delay(53, retry_after=None, random_value=0.5) == 8.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_timeout": 10**400},
        {"request_timeout": 10**400},
        {"request_timeout": (1.0, 10**400)},
    ],
)
def test_huge_timeout_config_raises_configuration_error(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        ResultDownloader(session=FakeSession(), **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_interval": 10**400},
        {"backoff": 10**400},
        {"jitter": 10**400},
        {"max_retry_after": 10**400},
    ],
)
def test_huge_retry_policy_config_raises_configuration_error(kwargs):
    with pytest.raises(ResultDownloadConfigurationError):
        DownloadRetryPolicy(**kwargs)


def test_dns_resolver_internal_type_error_propagates():
    resolver = RecordingResolver(error=TypeError("resolver bug"))
    downloader, session, _, _ = make_downloader(resolver=resolver)

    with pytest.raises(TypeError):
        downloader.resolve("https://example.com/x")

    assert session.requests == []


def test_random_fn_overflow_is_treated_as_zero():
    responses = [
        FakeResponse(status_code=503),
        FakeResponse(headers={"Content-Length": "2"}, chunks=[b"ok"]),
    ]
    downloader, _, clock, _ = make_downloader(
        responses,
        retry_policy=DownloadRetryPolicy(
            initial_interval=2.0, backoff=1.0, jitter=0.5
        ),
    )
    clock.random_value = 10**400

    downloader.resolve("https://example.com/x")

    assert clock.sleeps == [1.0]
