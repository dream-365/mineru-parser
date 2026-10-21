"""``ResultDownloader``：把绝对 HTTP(S) URL 解析为内存流。"""

from __future__ import annotations

import io
import logging
import math
import random
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlsplit

import requests
from urllib3 import exceptions as urllib3_exceptions

from .._http import parse_retry_after, status_class, to_finite_float
from .._telemetry import MetricHook, Telemetry
from .._version import __version__ as _FALLBACK_VERSION
from .errors import (
    ResultDownloadConfigurationError,
    ResultDownloadContentTypeError,
    ResultDownloadError,
    ResultDownloadHTTPError,
    ResultDownloadSecurityError,
    ResultDownloadTimeoutError,
    ResultDownloadTooLargeError,
    ResultDownloadTransientError,
)
from .policy import DEFAULT_DOWNLOAD_RETRY_POLICY, DownloadRetryPolicy
from .security import (
    DnsResolver,
    _DnsTransientError,
    _UrlGuard,
    default_dns_resolver,
    normalize_allowed_hosts,
    redact_url,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "cookie2"}
)
_RESERVED_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "range"}
)
_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_DIGITS_RE = re.compile(r"^[0-9]+$")
_DEFAULT_PORTS = {"http": 80, "https": 443}


# --- 构造参数校验 ---------------------------------------------------------


def _validate_positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResultDownloadConfigurationError(f"{name} must be a positive integer.")
    return value


def _validate_max_redirects(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResultDownloadConfigurationError("max_redirects must be an integer >= 0.")
    return value


def _validate_timeout(
    value: object,
    name: str,
    *,
    allow_none: bool = False,
    allow_tuple: bool = True,
) -> float | tuple[float, float] | None:
    if value is None and allow_none:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = to_finite_float(value)
        if number is None or number <= 0:
            raise ResultDownloadConfigurationError(
                f"{name} must be a positive finite number."
            )
        return number
    if allow_tuple and isinstance(value, (tuple, list)) and len(value) == 2:
        numbers = []
        for item in value:
            number = to_finite_float(item)
            if number is None or number <= 0:
                raise ResultDownloadConfigurationError(
                    f"{name} tuple values must both be positive finite numbers."
                )
            numbers.append(number)
        return (numbers[0], numbers[1])
    raise ResultDownloadConfigurationError(
        f"{name} must be a positive number or a (connect, read) tuple."
    )


def _normalize_headers(values: object) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ResultDownloadConfigurationError(
            "headers must be a mapping of string keys to string values."
        )
    result: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ResultDownloadConfigurationError(
                "headers keys and values must be strings."
            )
        if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
            raise ResultDownloadConfigurationError(
                "headers must not contain CR or LF characters."
            )
        if not _TOKEN_RE.fullmatch(key):
            raise ResultDownloadConfigurationError(
                "headers keys must be valid HTTP tokens."
            )
        lowered = key.lower()
        if lowered in seen:
            raise ResultDownloadConfigurationError(
                "headers must not contain case-insensitive duplicates."
            )
        if lowered in _RESERVED_HEADERS:
            raise ResultDownloadConfigurationError(
                f"header {key!r} is reserved and must not be set."
            )
        seen.add(lowered)
        result[key] = value
    return result


def _normalize_content_types(values: object) -> frozenset[str] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ResultDownloadConfigurationError(
            "allowed_content_types must be a collection, not a string."
        )
    try:
        items = list(values)  # type: ignore[arg-type]
    except TypeError:
        raise ResultDownloadConfigurationError(
            "allowed_content_types must be a collection of media types."
        ) from None
    if not items:
        raise ResultDownloadConfigurationError(
            "allowed_content_types must not be empty when enabled."
        )
    normalized = set()
    for item in items:
        if not isinstance(item, str):
            raise ResultDownloadConfigurationError(
                "allowed_content_types entries must be strings."
            )
        text = item.strip().lower()
        if not text or ";" in text:
            raise ResultDownloadConfigurationError(
                "allowed_content_types entries must be media types without parameters."
            )
        parts = text.split("/")
        if len(parts) != 2:
            raise ResultDownloadConfigurationError(
                "allowed_content_types entries must be type/subtype."
            )
        main, sub = parts
        if main == "*":
            if sub != "*":
                raise ResultDownloadConfigurationError(
                    "allowed_content_types must not use */subtype."
                )
            normalized.add("*/*")
            continue
        if not _TOKEN_RE.fullmatch(main):
            raise ResultDownloadConfigurationError(
                "allowed_content_types contains an invalid type."
            )
        if sub == "*":
            normalized.add(f"{main}/*")
            continue
        if not _TOKEN_RE.fullmatch(sub):
            raise ResultDownloadConfigurationError(
                "allowed_content_types contains an invalid subtype."
            )
        normalized.add(f"{main}/{sub}")
    return frozenset(normalized)


def _package_version() -> str:
    try:
        return version("mineru-parser")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": f"mineru-parser/{_package_version()}",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }


def _merge_headers(
    defaults: Mapping[str, str],
    user_headers: Mapping[str, str],
) -> dict[str, str]:
    merged = dict(defaults)
    for key, value in user_headers.items():
        for existing in [item for item in merged if item.lower() == key.lower()]:
            del merged[existing]
        merged[key] = value
    return merged


def _lower_header_name(key: object) -> str:
    # requests 接受 bytes 形式的 header 名；先解码再比较，避免
    # str(b"Cookie") == "b'cookie'" 绕过敏感头检查。
    if isinstance(key, (bytes, bytearray)):
        return bytes(key).decode("latin-1").lower()
    return str(key).lower()


def _validate_injected_session(session: object) -> None:
    headers = getattr(session, "headers", None)
    if headers:
        for key in headers:
            if _lower_header_name(key) in _SENSITIVE_HEADERS:
                raise ResultDownloadConfigurationError(
                    "Injected session must not carry Authorization, "
                    "Proxy-Authorization, Cookie or Cookie2 global headers."
                )
    if getattr(session, "auth", None) is not None:
        raise ResultDownloadConfigurationError(
            "Injected session must not configure session.auth; pass "
            "credentials through headers instead."
        )


def _require_callable(value: object, name: str) -> None:
    if not callable(value):
        raise ResultDownloadConfigurationError(f"{name} must be callable.")


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(
        exc, (requests.exceptions.Timeout, urllib3_exceptions.TimeoutError)
    ):
        return True
    # requests 在流式读取时把 urllib3 的 ReadTimeoutError 包装成
    # ConnectionError，原始异常保存在 args[0] 中。
    return any(
        isinstance(arg, urllib3_exceptions.TimeoutError)
        for arg in getattr(exc, "args", ())
    )


# --- 内部数据模型 ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Runtime:
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    wall_clock: Callable[[], float]
    random_fn: Callable[[], float]


@dataclass(frozen=True, slots=True)
class _BodyResult:
    buffer: io.BytesIO
    bytes_read: int


@dataclass(frozen=True, slots=True)
class _DownloadOutcome:
    buffer: io.BytesIO
    final_url: str
    status_code: int
    content_type: str | None
    redirects: int
    bytes_read: int


class _Retryable(Exception):
    """内部可重试失败；不得泄漏到公共 API。"""

    def __init__(
        self,
        summary: str,
        *,
        error_type: str,
        status_code: int | None = None,
        retry_after: float | None = None,
        is_timeout: bool = False,
    ) -> None:
        super().__init__(summary)
        self.summary = summary
        self.error_type = error_type
        self.status_code = status_code
        self.retry_after = retry_after
        self.is_timeout = is_timeout


class _IncompleteBody(_Retryable):
    def __init__(self, *, declared: int, received: int) -> None:
        super().__init__(
            f"incomplete body: expected {declared} bytes, received {received}",
            error_type="IncompleteBody",
        )


# --- 响应头辅助 -----------------------------------------------------------


def _header(headers: object, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if value is not None:
        return value if isinstance(value, str) else str(value)
    items = getattr(headers, "items", None)
    if items is None:
        return None
    lowered = name.lower()
    for key, item in items():
        if str(key).lower() == lowered:
            return item if isinstance(item, str) else str(item)
    return None


def usable_content_length(headers: object) -> int | None:
    """返回可用的 ``Content-Length``；不可用时返回 ``None``。"""
    transfer_encoding = _header(headers, "Transfer-Encoding")
    if transfer_encoding is not None and transfer_encoding.strip():
        return None
    content_encoding = _header(headers, "Content-Encoding")
    if content_encoding is not None:
        normalized = content_encoding.strip().lower()
        if normalized not in ("", "identity"):
            return None
    raw = _header(headers, "Content-Length")
    if raw is None:
        return None
    text = raw.strip()
    if not _DIGITS_RE.fullmatch(text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _same_origin(first: str, second: str) -> bool:
    left = _origin_key(first)
    right = _origin_key(second)
    return left is not None and left == right


def _origin_key(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        port = parsed.port or _DEFAULT_PORTS.get(scheme, 0)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    return scheme, host, port


# --- 公共组件 -------------------------------------------------------------


class ResultDownloader:
    """同步下载器：``resolve(url) -> io.BytesIO``。

    实例可顺序复用，但**不承诺线程安全**；并发场景请每线程使用独立实例。
    未注入 ``session`` 时自建 Session 并由本实例负责关闭；注入的 Session
    生命周期归调用方所有，且必须把其内部重试次数设为 0——本实例的
    ``DownloadRetryPolicy`` 是唯一重试层。

    ``allow_private_hosts=True`` 会跳过**所有**非公网 IP 检查（回环、私网、
    链路本地、多播、保留、site-local、NAT64 等），属于高风险配置，仅建议
    在测试中使用。

    安全边界：URL、DNS 结果、重定向目标与响应头均按不可信输入处理。
    SSRF 校验基于本地 DNS 解析与直连语义；自建 Session 沿用 ``requests``
    默认的 ``trust_env=True``，代理会重新解析目标，需要强保证时应注入
    ``trust_env=False`` 的 Session 或在代理层限制出站。预校验与
    ``requests`` 的实际连接是两次解析，存在 DNS Rebinding 残余风险。

    超时边界：``total_timeout`` 覆盖整个 ``resolve()`` 调用（含重试、
    重定向与退避），但单次阻塞的 DNS 解析不受 ``request_timeout`` 控制，
    单次 socket 读取最多超出 ``total_timeout`` 一个 read 超时分量。
    """

    def __init__(
        self,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        chunk_size: int = 64 * 1024,
        request_timeout: float | tuple[float, float] = (5.0, 30.0),
        total_timeout: float | None = 300.0,
        retry_policy: DownloadRetryPolicy | None = None,
        allowed_content_types: Collection[str] | None = None,
        allowed_hosts: Collection[str] | None = None,
        allow_private_hosts: bool = False,
        allow_https_downgrade: bool = False,
        max_redirects: int = 5,
        headers: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        random_fn: Callable[[], float] = random.random,
        dns_resolver: DnsResolver | None = None,
        on_metric: MetricHook | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._max_bytes = _validate_positive_int(max_bytes, "max_bytes")
        self._chunk_size = _validate_positive_int(chunk_size, "chunk_size")
        self._request_timeout = _validate_timeout(request_timeout, "request_timeout")
        self._total_timeout = _validate_timeout(
            total_timeout,
            "total_timeout",
            allow_none=True,
            allow_tuple=False,
        )
        if retry_policy is None:
            retry_policy = DEFAULT_DOWNLOAD_RETRY_POLICY
        if not isinstance(retry_policy, DownloadRetryPolicy):
            raise ResultDownloadConfigurationError(
                "retry_policy must be a DownloadRetryPolicy instance."
            )
        self._retry_policy = retry_policy
        self._allowed_content_types = _normalize_content_types(allowed_content_types)
        self._allowed_hosts = normalize_allowed_hosts(allowed_hosts)
        if not isinstance(allow_private_hosts, bool):
            raise ResultDownloadConfigurationError(
                "allow_private_hosts must be a bool."
            )
        if not isinstance(allow_https_downgrade, bool):
            raise ResultDownloadConfigurationError(
                "allow_https_downgrade must be a bool."
            )
        self._allow_private_hosts = allow_private_hosts
        self._allow_https_downgrade = allow_https_downgrade
        self._max_redirects = _validate_max_redirects(max_redirects)
        self._headers = _merge_headers(_default_headers(), _normalize_headers(headers))

        _require_callable(sleep, "sleep")
        _require_callable(monotonic, "monotonic")
        _require_callable(wall_clock, "wall_clock")
        _require_callable(random_fn, "random_fn")
        if dns_resolver is None:
            dns_resolver = default_dns_resolver
        else:
            _require_callable(dns_resolver, "dns_resolver")
        if on_metric is not None:
            _require_callable(on_metric, "on_metric")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ResultDownloadConfigurationError(
                "correlation_id must be a string or None."
            )

        if session is None:
            session = requests.Session()
            self._owns_session = True
        else:
            _validate_injected_session(session)
            self._owns_session = False

        self._session = session
        self._runtime = _Runtime(
            sleep=sleep,
            monotonic=monotonic,
            wall_clock=wall_clock,
            random_fn=random_fn,
        )
        self._guard = _UrlGuard(
            allow_private_hosts=allow_private_hosts,
            allowed_hosts=self._allowed_hosts,
            allow_https_downgrade=allow_https_downgrade,
            dns_resolver=dns_resolver,
        )
        self._telemetry = Telemetry(
            on_metric=on_metric,
            correlation_id=correlation_id,
        )

    # --- 生命周期 ---------------------------------------------------------

    def close(self) -> None:
        """关闭自建 Session；注入 Session 不接管。可重复调用。"""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> ResultDownloader:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- 只读配置 ---------------------------------------------------------

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def retry_policy(self) -> DownloadRetryPolicy:
        return self._retry_policy

    # --- 下载 -------------------------------------------------------------

    def resolve(self, url: str) -> io.BytesIO:
        """下载 ``url`` 并返回游标位于 0 的独立 ``BytesIO``。

        只有完整读取并关闭响应后才返回；任何失败都不返回部分数据。
        返回的缓冲区所有权归调用方。对结果包下载而言，空流（``204`` /
        ``205`` / ``Content-Length: 0``）通常意味着服务端异常或错误页，
        调用方应自行判定，下载器不会把它当作错误。
        """
        started = self._runtime.monotonic()
        deadline = (
            None if self._total_timeout is None else started + self._total_timeout
        )
        attempts = 0
        last_error: str | None = None
        last_status: int | None = None
        last_retry_after: float | None = None
        last_was_timeout = False
        bytes_read = 0
        outcome = "unexpected"
        display_url = redact_url(url)

        try:
            # 只做语法 / 配置校验；DNS 与 IP 校验在每次尝试内执行
            target = self._guard.validate_url_syntax(url)
            while attempts < self._retry_policy.max_attempts:
                self._check_deadline(
                    deadline, attempts, last_error, last_status, last_retry_after
                )
                attempts += 1
                try:
                    result = self._download_once(
                        target,
                        deadline,
                        attempts,
                        last_error,
                        last_status,
                        last_retry_after,
                    )
                except _Retryable as exc:
                    last_error = exc.summary
                    last_status = exc.status_code
                    last_retry_after = exc.retry_after
                    last_was_timeout = exc.is_timeout
                    retry_error = exc
                else:
                    bytes_read = result.bytes_read
                    outcome = "success"
                    self._emit_success(display_url, result, started, attempts)
                    return result.buffer

                if attempts >= self._retry_policy.max_attempts:
                    break
                # 在 except 块之外计算延迟并休眠：否则此处抛出的
                # ResultDownloadTimeoutError 会通过 __context__ 链持有
                # 原始 requests 异常（其中可能包含签名 URL）。
                delay = self._retry_delay(attempts, retry_error.retry_after)
                self._sleep_within_deadline(
                    delay,
                    deadline,
                    attempts,
                    last_error,
                    retry_error.status_code,
                    retry_error.retry_after,
                )
                self._emit_retry(display_url, attempts, retry_error, delay)

            raise self._exhausted(
                last_error,
                attempts,
                last_status,
                last_retry_after,
                last_was_timeout,
            )
        except ResultDownloadError as exc:
            outcome = _outcome_for(exc)
            exception_bytes = getattr(exc, "received_bytes", None)
            if exception_bytes:
                bytes_read = exception_bytes
            self._emit_error(display_url, exc, attempts)
            raise
        except BaseException as exc:
            outcome = "unexpected"
            self._emit_unexpected(display_url, exc, attempts)
            raise
        finally:
            self._emit_metrics(outcome, started, bytes_read, attempts)

    # --- 单次尝试 ---------------------------------------------------------

    def _download_once(
        self,
        original_url: str,
        deadline: float | None,
        attempt: int,
        last_error: str | None,
        last_status: int | None,
        last_retry_after: float | None,
    ) -> _DownloadOutcome:
        current = original_url
        redirects = 0
        allow_sensitive = True
        needs_validation = True

        while True:
            self._check_deadline(
                deadline, attempt, last_error, last_status, last_retry_after
            )
            if needs_validation:
                try:
                    current = self._guard.validate_target(current)
                except _DnsTransientError:
                    raise _Retryable(
                        "DNS resolution failed.", error_type="DnsTransientError"
                    ) from None
                self._check_deadline(
                    deadline, attempt, last_error, last_status, last_retry_after
                )

            headers = self._headers_for(allow_sensitive)
            try:
                response = self._session.get(
                    current,
                    stream=True,
                    allow_redirects=False,
                    timeout=self._request_timeout,
                    headers=headers,
                )
            except requests.RequestException as exc:
                failure = self._classify_transport(exc)
            else:
                failure = None
            if failure is not None:
                # 在 except 块之外抛出，避免 __context__ 保留原始 requests
                # 异常（其中可能包含签名 URL）。
                raise failure

            try:
                # session.get 阻塞期间也可能耗尽总预算（例如慢速响应头）。
                self._check_deadline(
                    deadline, attempt, last_error, last_status, last_retry_after
                )
                status = response.status_code

                if status in _REDIRECT_STATUSES:
                    if redirects >= self._max_redirects:
                        raise ResultDownloadSecurityError("Too many redirects.")
                    location = _header(response.headers, "Location")
                    if location is None or not location.strip():
                        raise ResultDownloadHTTPError(
                            "Redirect response is missing a Location header.",
                            status_code=status,
                            url=redact_url(current),
                        )
                    try:
                        next_url = self._guard.validate_redirect(current, location)
                    except _DnsTransientError:
                        raise _Retryable(
                            "DNS resolution failed for redirect target.",
                            error_type="DnsTransientError",
                        ) from None
                    if not _same_origin(current, next_url):
                        allow_sensitive = False
                    current = next_url
                    redirects += 1
                    # validate_redirect 已完成 DNS / IP / allowed_hosts 校验，
                    # 下一轮无需重复解析同一目标。
                    needs_validation = False
                    continue

                if 200 <= status < 300:
                    content_type = _header(response.headers, "Content-Type")
                    if status == 206:
                        raise ResultDownloadHTTPError(
                            "Partial content is not accepted.",
                            status_code=206,
                            url=redact_url(current),
                        )
                    declared = usable_content_length(response.headers)
                    if status in (204, 205) or declared == 0:
                        # 空响应不读取响应体，也不做内容类型检查；但仍需在
                        # 返回成功前确认总预算未被回包耗时耗尽。
                        self._check_deadline(
                            deadline,
                            attempt,
                            last_error,
                            last_status,
                            last_retry_after,
                        )
                        return _DownloadOutcome(
                            buffer=io.BytesIO(),
                            final_url=current,
                            status_code=status,
                            content_type=content_type,
                            redirects=redirects,
                            bytes_read=0,
                        )
                    self._check_content_type(content_type)
                    try:
                        body = self._read_body(
                            response,
                            declared,
                            deadline,
                            attempt,
                            last_error,
                            last_status,
                            last_retry_after,
                        )
                    except (
                        requests.RequestException,
                        urllib3_exceptions.HTTPError,
                    ) as exc:
                        failure = self._classify_transport(exc)
                    else:
                        failure = None
                    if failure is not None:
                        raise failure
                    return _DownloadOutcome(
                        buffer=body.buffer,
                        final_url=current,
                        status_code=status,
                        content_type=content_type,
                        redirects=redirects,
                        bytes_read=body.bytes_read,
                    )

                if status in _RETRYABLE_STATUSES:
                    raise _Retryable(
                        f"HTTP {status}",
                        error_type="HTTPStatus",
                        status_code=status,
                        retry_after=self._retry_after(response.headers),
                    )

                raise ResultDownloadHTTPError(
                    f"HTTP {status}",
                    status_code=status,
                    url=redact_url(current),
                )
            finally:
                response.close()

    # --- 响应体 -----------------------------------------------------------

    def _check_content_type(self, content_type: str | None) -> None:
        if self._allowed_content_types is None:
            return
        raw = (content_type or "").split(";", 1)[0]
        normalized = raw.strip().lower()
        allowed = tuple(sorted(self._allowed_content_types))
        if not normalized:
            raise ResultDownloadContentTypeError(
                "Response is missing a usable Content-Type.",
                content_type=None,
                allowed=allowed,
            )
        for item in self._allowed_content_types:
            if item == "*/*" or normalized == item:
                return
            if item.endswith("/*") and normalized.startswith(item[:-1]):
                return
        raise ResultDownloadContentTypeError(
            f"Response Content-Type {normalized!r} is not allowed.",
            content_type=normalized,
            allowed=allowed,
        )

    def _read_body(
        self,
        response: object,
        declared: int | None,
        deadline: float | None,
        attempt: int,
        last_error: str | None,
        last_status: int | None,
        last_retry_after: float | None,
    ) -> _BodyResult:
        if declared is not None and declared > self._max_bytes:
            raise ResultDownloadTooLargeError(
                f"Response declares {declared} bytes, exceeding "
                f"max_bytes={self._max_bytes}.",
                max_bytes=self._max_bytes,
                declared_bytes=declared,
            )

        buffer = io.BytesIO()
        received = 0
        try:
            effective_chunk = min(self._chunk_size, self._max_bytes)
            for chunk in self._iter_body(response, effective_chunk):
                if not chunk:
                    continue
                received += len(chunk)
                if received > self._max_bytes:
                    raise ResultDownloadTooLargeError(
                        f"Response exceeded max_bytes={self._max_bytes}.",
                        max_bytes=self._max_bytes,
                        received_bytes=received,
                        declared_bytes=declared,
                    )
                buffer.write(chunk)
                self._check_deadline(
                    deadline, attempt, last_error, last_status, last_retry_after
                )

            if declared is not None and declared > 0 and received < declared:
                raise _IncompleteBody(declared=declared, received=received)

            self._check_deadline(
                deadline, attempt, last_error, last_status, last_retry_after
            )
            buffer.seek(0)
            return _BodyResult(buffer=buffer, bytes_read=received)
        except BaseException:
            buffer.close()
            raise

    def _iter_body(self, response: object, chunk_size: int):
        """优先用 ``raw.read1`` 增量读取，使总预算检查能覆盖慢速滴流响应。

        ``iter_content`` 会一直缓冲到 ``chunk_size`` 才返回，慢速服务端可用
        每个分块都小于 read timeout 的间隔把单次调用拖到远超预算；
        ``read1`` 只要有数据就返回，因此每个分块后都能检查 deadline。
        """
        raw = getattr(response, "raw", None)
        read1 = getattr(raw, "read1", None)
        if raw is not None and callable(read1):
            while True:
                chunk = read1(chunk_size, decode_content=True)
                if not chunk:
                    return
                yield chunk
        else:
            yield from response.iter_content(chunk_size=chunk_size)  # type: ignore[attr-defined]

    # --- 重试 / 超时 ------------------------------------------------------

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        return self._retry_policy.delay(
            attempt,
            retry_after=retry_after,
            random_value=self._random_value(),
        )

    def _random_value(self) -> float:
        try:
            value = float(self._runtime.random_fn())
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if not math.isfinite(value):
            # AC-1.10：非有限值按 0 处理，绝不传给 sleep
            return 0.0
        return min(1.0, max(0.0, value))

    def _check_deadline(
        self,
        deadline: float | None,
        attempts: int,
        last_error: str | None,
        last_status: int | None,
        last_retry_after: float | None,
    ) -> None:
        if deadline is None:
            return
        if self._runtime.monotonic() >= deadline:
            raise ResultDownloadTimeoutError(
                "Download exceeded its total timeout.",
                attempts=attempts,
                last_error=last_error,
                last_status_code=last_status,
                retry_after=last_retry_after,
            )

    def _sleep_within_deadline(
        self,
        delay: float,
        deadline: float | None,
        attempts: int,
        last_error: str | None,
        last_status: int | None,
        retry_after: float | None,
    ) -> None:
        if deadline is not None:
            remaining = deadline - self._runtime.monotonic()
            if delay >= remaining:
                raise ResultDownloadTimeoutError(
                    "Next retry would exceed the total timeout.",
                    attempts=attempts,
                    last_error=last_error,
                    last_status_code=last_status,
                    retry_after=retry_after,
                )
        self._runtime.sleep(delay)

    def _exhausted(
        self,
        last_error: str | None,
        attempts: int,
        last_status: int | None,
        last_retry_after: float | None,
        last_was_timeout: bool,
    ) -> ResultDownloadError:
        summary = last_error or "unknown error"
        message = f"Download failed after {attempts} attempt(s): {summary}"
        error_type = (
            ResultDownloadTimeoutError
            if last_was_timeout
            else ResultDownloadTransientError
        )
        return error_type(
            message,
            attempts=attempts,
            last_error=last_error,
            last_status_code=last_status,
            retry_after=last_retry_after,
        )

    def _classify_transport(
        self, exc: requests.RequestException | urllib3_exceptions.HTTPError
    ) -> Exception:
        if isinstance(
            exc, (requests.exceptions.SSLError, urllib3_exceptions.SSLError)
        ):
            return ResultDownloadSecurityError("TLS verification failed.")
        if isinstance(
            exc,
            (
                requests.exceptions.InvalidURL,
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema,
                requests.exceptions.InvalidHeader,
            ),
        ):
            return ResultDownloadConfigurationError(
                "Request URL or headers are invalid."
            )
        if isinstance(exc, requests.exceptions.TooManyRedirects):
            return ResultDownloadSecurityError("Too many redirects.")
        # 仅保留异常类名，绝不拼接 str(exc) 或 URL
        return _Retryable(
            type(exc).__name__,
            error_type=type(exc).__name__,
            is_timeout=_is_timeout_error(exc),
        )

    # --- 请求头 -----------------------------------------------------------

    def _headers_for(self, allow_sensitive: bool) -> dict[str, str]:
        headers = dict(self._headers)
        if not allow_sensitive:
            for key in list(headers):
                if key.lower() in _SENSITIVE_HEADERS:
                    del headers[key]
        return headers

    def _retry_after(self, headers: object) -> float | None:
        return parse_retry_after(
            _header(headers, "Retry-After"),
            now=self._runtime.wall_clock(),
        )

    # --- 遥测 -------------------------------------------------------------

    def _duration_ms(self, started: float) -> float:
        return round((self._runtime.monotonic() - started) * 1000, 3)

    def _emit_success(
        self,
        display_url: str,
        result: _DownloadOutcome,
        started: float,
        attempts: int,
    ) -> None:
        self._telemetry.log(
            "mineru.download",
            url=display_url,
            final_url=redact_url(result.final_url),
            status_code=result.status_code,
            content_type=result.content_type,
            bytes=result.bytes_read,
            duration_ms=self._duration_ms(started),
            attempts=attempts,
            redirects=result.redirects,
            outcome="success",
        )

    def _emit_retry(
        self,
        display_url: str,
        attempt: int,
        exc: _Retryable,
        delay: float,
    ) -> None:
        self._telemetry.log(
            "mineru.download.retry",
            level=logging.WARNING,
            url=display_url,
            attempt=attempt,
            error_type=exc.error_type,
            status_code=exc.status_code,
            delay_ms=round(delay * 1000, 3),
        )
        self._telemetry.metric(
            "mineru.download.retry.total",
            1,
            {
                "error_type": exc.error_type,
                "status_class": status_class(exc.status_code),
            },
        )

    def _emit_error(
        self,
        display_url: str,
        exc: ResultDownloadError,
        attempts: int,
    ) -> None:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(exc, "last_status_code", None)
        self._telemetry.log(
            "mineru.download.error",
            level=logging.WARNING,
            url=display_url,
            error_type=type(exc).__name__,
            status_code=status,
            attempts=attempts,
        )

    def _emit_unexpected(
        self,
        display_url: str,
        exc: BaseException,
        attempts: int,
    ) -> None:
        self._telemetry.log(
            "mineru.download.error",
            level=logging.ERROR,
            url=display_url,
            error_type=type(exc).__name__,
            attempts=attempts,
        )

    def _emit_metrics(
        self,
        outcome: str,
        started: float,
        bytes_read: int,
        attempts: int,
    ) -> None:
        tags = {"outcome": outcome}
        duration_ms = self._duration_ms(started)
        self._telemetry.metric("mineru.download.total", 1, tags)
        self._telemetry.metric("mineru.download.duration_ms", duration_ms, tags)
        self._telemetry.metric("mineru.download.bytes", bytes_read, tags)
        self._telemetry.metric("mineru.download.attempts", attempts, tags)


def _outcome_for(exc: ResultDownloadError) -> str:
    # 必须先判断子类 ResultDownloadTimeoutError，再判断其基类
    if isinstance(exc, ResultDownloadTimeoutError):
        return "timeout"
    if isinstance(exc, ResultDownloadTransientError):
        return "transient"
    if isinstance(exc, ResultDownloadConfigurationError):
        return "config_error"
    if isinstance(exc, ResultDownloadSecurityError):
        return "security_error"
    if isinstance(exc, ResultDownloadTooLargeError):
        return "too_large"
    if isinstance(exc, ResultDownloadContentTypeError):
        return "content_type_error"
    if isinstance(exc, ResultDownloadHTTPError):
        return "http_error"
    return "unexpected"


__all__ = ["ResultDownloader", "usable_content_length"]
