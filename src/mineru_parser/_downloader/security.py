"""URL / IDNA / DNS / IP 校验与 URL 脱敏。

本模块不发 HTTP、不读响应体、不依赖重试控制流。URL 语法错误按调用方
指定的异常类型抛出：初始 URL 使用配置错误，重定向目标使用安全错误；
IDNA 规范化失败始终是安全错误。
"""

from __future__ import annotations

import ipaddress
import socket
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import idna

from .errors import (
    ResultDownloadConfigurationError,
    ResultDownloadError,
    ResultDownloadSecurityError,
)

type DnsResolver = Callable[[str, int], Sequence[str]]

_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_PORT = 65535

_TRANSITION_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64
    ipaddress.ip_network("2002::/16"),  # 6to4
    ipaddress.ip_network("2001::/32"),  # Teredo
)


class _DnsTransientError(Exception):
    """DNS 解析失败或返回空结果；由调用方转换为可重试错误。"""


@dataclass(frozen=True, slots=True)
class _ParsedTarget:
    scheme: str
    host: str  # 已规范化的 ASCII host（IP 为压缩形式）
    port: int | None  # 显式端口；缺省为 None
    path: str
    query: str

    @property
    def effective_port(self) -> int:
        return self.port if self.port is not None else _DEFAULT_PORTS[self.scheme]

    def request_url(self) -> str:
        netloc = f"[{self.host}]" if ":" in self.host else self.host
        if self.port is not None:
            netloc = f"{netloc}:{self.port}"
        return urlunsplit((self.scheme, netloc, self.path or "/", self.query, ""))


def _sanitize_log_text(value: str) -> str:
    """移除 Unicode 控制字符，避免日志注入（CWE-117）。"""
    return "".join(
        char for char in value if unicodedata.category(char) != "Cc"
    )


def redact_url(url: object) -> str:
    """移除 query 与 fragment；无法安全解析时返回 ``"<invalid-url>"``。

    返回值始终剔除控制字符（含 C0/C1），可直接写入日志。
    """
    if not isinstance(url, str):
        return "<invalid-url>"
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    if (
        not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return "<invalid-url>"
    return _sanitize_log_text(
        urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    )


def _reject_control_chars(value: str, error: type[ResultDownloadError]) -> None:
    """在原始字符串上检查控制字符；``urlsplit`` 会静默移除部分控制字符。"""
    for char in value:
        if unicodedata.category(char) == "Cc":
            raise error("URL contains control characters.")


def canonicalize_host(host: str) -> str:
    """按 IDNA（``strict`` + ``std3_rules``）或 IP 压缩形式规范化主机。"""
    value = host.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    value = value.rstrip(".")
    if not value:
        raise ValueError("host must not be empty")
    if "%" in value:
        # zone ID（如 fe80::1%en0）与百分号编码一律拒绝
        raise ValueError("host must not contain a zone id")
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return idna.encode(value.lower(), strict=True, std3_rules=True).decode("ascii")
    if isinstance(ip, ipaddress.IPv6Address) and ip.scope_id is not None:
        raise ValueError("host must not contain a zone id")
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.compressed


def _is_public_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.is_site_local:
            return False
        # IPv6Address.__eq__(IPv6Network) 恒为 False，必须用 network 的
        # __contains__ 判断地址是否落在过渡网段内。
        if any(ip in network for network in _TRANSITION_NETWORKS):
            return False
    return True


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if "%" in value:
        raise ValueError("zone id is not allowed")
    ip = ipaddress.ip_address(value.strip())
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id is not None:
            raise ValueError("zone id is not allowed")
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
    return ip


def _parse_url(
    url: object,
    *,
    error: type[ResultDownloadError],
) -> _ParsedTarget:
    if not isinstance(url, str):
        raise error("URL must be a string.")
    _reject_control_chars(url, error)
    raw = url.strip()
    if not raw:
        raise error("URL must not be blank.")

    try:
        parsed = urlsplit(raw)
        port = parsed.port  # 触发非法端口校验
    except ValueError:
        raise error("URL is not a valid absolute URL.") from None

    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise error("URL scheme must be http or https.")
    if parsed.username is not None or parsed.password is not None:
        raise error("URL must not contain userinfo.")
    host = parsed.hostname
    if not host:
        raise error("URL must contain a host.")
    if any(char.isspace() or char in "\\%" for char in host):
        raise error("URL host contains invalid characters.")
    try:
        canonical_host = canonicalize_host(host)
    except (idna.IDNAError, UnicodeError, ValueError):
        # AC-6.1 / 3.7：IDNA 失败始终按安全错误处理
        raise ResultDownloadSecurityError(
            "URL host is not a valid IDNA host."
        ) from None
    if port is not None and not 1 <= port <= _MAX_PORT:
        raise error("URL port must be in [1, 65535].")
    return _ParsedTarget(
        scheme=scheme,
        host=canonical_host,
        port=port,
        path=parsed.path,
        query=parsed.query,
    )


def _normalize_allowed_host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultDownloadConfigurationError(
            "allowed_hosts entries must be non-empty host names or IP literals."
        )
    text = value.strip()
    if text.startswith("[") or text.endswith("]"):
        if not (text.startswith("[") and text.endswith("]")):
            raise ResultDownloadConfigurationError(
                "allowed_hosts contains an invalid IPv6 literal."
            )
        inner = text[1:-1]
        try:
            ipaddress.ip_address(inner)
            return canonicalize_host(inner)
        except (idna.IDNAError, UnicodeError, ValueError):
            raise ResultDownloadConfigurationError(
                "allowed_hosts contains an invalid IPv6 literal."
            ) from None
    if any(char.isspace() for char in text) or any(char in text for char in "\\%@*?#/"):
        raise ResultDownloadConfigurationError(
            "allowed_hosts entries must not contain a scheme, port, path, "
            "query, fragment or wildcard."
        )
    try:
        ipaddress.ip_address(text)
    except ValueError:
        if ":" in text:
            raise ResultDownloadConfigurationError(
                "allowed_hosts entries must not contain a port or an "
                "invalid IPv6 literal."
            ) from None
    try:
        return canonicalize_host(text)
    except (idna.IDNAError, UnicodeError, ValueError):
        raise ResultDownloadConfigurationError(
            "allowed_hosts contains an invalid host name."
        ) from None


def normalize_allowed_hosts(
    values: object,
) -> frozenset[str] | None:
    """校验并规范化 ``allowed_hosts``；``None`` 表示禁用。"""
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ResultDownloadConfigurationError(
            "allowed_hosts must be a collection of host names, not a string."
        )
    try:
        items = list(values)  # type: ignore[arg-type]
    except TypeError:
        raise ResultDownloadConfigurationError(
            "allowed_hosts must be a collection of host names."
        ) from None
    if not items:
        raise ResultDownloadConfigurationError(
            "allowed_hosts must not be empty when enabled."
        )
    return frozenset(_normalize_allowed_host(item) for item in items)


def default_dns_resolver(host: str, port: int) -> Sequence[str]:
    """系统解析器：提取并去重 ``getaddrinfo`` 返回的 IP。"""
    addresses: list[str] = []
    for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


class _UrlGuard:
    """URL 语法、主机允许列表、DNS 与逐跳重定向校验。"""

    def __init__(
        self,
        *,
        allow_private_hosts: bool,
        allowed_hosts: frozenset[str] | None,
        allow_https_downgrade: bool,
        dns_resolver: DnsResolver,
    ) -> None:
        self._allow_private_hosts = allow_private_hosts
        self._allowed_hosts = allowed_hosts
        self._allow_https_downgrade = allow_https_downgrade
        self._dns_resolver = dns_resolver

    def validate_url_syntax(self, url: object) -> str:
        """一次性的初始 URL 语法校验，返回去除外层空白的原始 URL。"""
        _parse_url(url, error=ResultDownloadConfigurationError)
        return url.strip()  # type: ignore[union-attr]

    def validate_target(self, url: str) -> str:
        """每次尝试 / 每一跳都执行的完整校验，返回 canonical 请求 URL。"""
        target = _parse_url(url, error=ResultDownloadSecurityError)
        if self._allowed_hosts is not None and target.host not in self._allowed_hosts:
            raise ResultDownloadSecurityError("URL host is not allowed.")
        self._check_addresses(target)
        return target.request_url()

    def validate_redirect(self, current: str, location: str) -> str:
        """校验 ``Location`` 并在 join 后重新执行完整目标校验。"""
        if not isinstance(location, str):
            raise ResultDownloadSecurityError("Redirect Location must be a string.")
        _reject_control_chars(location, ResultDownloadSecurityError)
        text = location.strip()
        if not text:
            raise ResultDownloadSecurityError("Redirect Location must not be empty.")
        try:
            next_url = urljoin(current, text)
            next_scheme = urlsplit(next_url).scheme.lower()
        except ValueError:
            raise ResultDownloadSecurityError(
                "Redirect target is not a valid URL."
            ) from None
        current_scheme = urlsplit(current).scheme.lower()
        if (
            current_scheme == "https"
            and next_scheme == "http"
            and not self._allow_https_downgrade
        ):
            raise ResultDownloadSecurityError(
                "HTTPS to HTTP redirects are not allowed."
            )
        return self.validate_target(next_url)

    # --- 内部 -------------------------------------------------------------

    def _check_addresses(self, target: _ParsedTarget) -> None:
        try:
            literal = _parse_ip(target.host)
        except ValueError:
            literal = None
        if literal is not None:
            if not self._allow_private_hosts and not _is_public_ip(literal):
                raise ResultDownloadSecurityError("URL host is not a public address.")
            return

        try:
            resolved = self._dns_resolver(target.host, target.effective_port)
        except (socket.gaierror, OSError):
            raise _DnsTransientError("DNS resolution failed.") from None
        # 只把“返回值不可迭代”当作无效结果；resolver 自身抛出的 TypeError
        # 属于未知异常，按 AC-4.11 原样向上传播。
        try:
            addresses = list(resolved)
        except TypeError:
            raise ResultDownloadSecurityError(
                "DNS resolver returned an invalid result."
            ) from None
        if not addresses:
            raise _DnsTransientError("DNS resolution returned no addresses.")
        for raw in addresses:
            if not isinstance(raw, str):
                raise ResultDownloadSecurityError(
                    "DNS resolver returned an invalid address."
                )
            try:
                ip = _parse_ip(raw)
            except ValueError:
                raise ResultDownloadSecurityError(
                    "DNS resolver returned an invalid address."
                ) from None
            if not self._allow_private_hosts and not _is_public_ip(ip):
                raise ResultDownloadSecurityError(
                    "URL host resolves to a non-public address."
                )


__all__ = [
    "DnsResolver",
    "canonicalize_host",
    "default_dns_resolver",
    "normalize_allowed_hosts",
    "redact_url",
]
