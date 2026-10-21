"""ZIP 成员发现、路径规范化与有界读取。

本模块只处理归档结构，不解析 JSON、不解释 Schema。所有路径字段的规则以
``canonicalize_member_path`` 为唯一实现；结构化异常字段保留完整 canonical
path，只有日志渲染与无法 canonical 化的原始名才做转义 / 截断。
"""

from __future__ import annotations

import io
import stat
import struct
import zipfile
import zlib

from .errors import (
    ResultExtractionArchiveError,
    ResultExtractionLimitError,
    ResultExtractionManifestError,
)
from .limits import ExtractionLimits

_MANIFEST_SUFFIX = "_content_list_v2.json"
_IMAGES_DIRNAME = "images"

_MAX_CANDIDATES_IN_ERROR = 20
_MAX_TOP_LEVEL_MEMBERS_IN_ERROR = 20
_MAX_CONTEXT_CHARS = 512

_EOCD_TAIL_BYTES = 64 * 1024
_EOCD_MIN_SIZE = 22
_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_HEADER_SIZE = 22

_CD_RECORD_MIN_BYTES = 46
_ENTRY_COUNT_OVERFLOW = 0xFFFF
_CD_SIZE_OVERFLOW = 0xFFFFFFFF

_EOCD_STRUCT = struct.Struct("<4s4H2LH")


# --- 路径规则 -------------------------------------------------------------


def canonicalize_member_path(raw: str) -> str | None:
    """把归档成员名归一为 ``/`` 分隔的 canonical path。

    无法安全归一（空名、绝对路径、反斜杠、NUL / C0 / C1 控制字符、``..``
    段）时返回 ``None``。本函数是路径规则的唯一实现，Extractor 内部与下游
    共用同一份代码；它不访问 ZIP、不读取任何成员。
    """
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("/"):
        return None
    if "\\" in raw:
        return None
    for char in raw:
        code = ord(char)
        if code <= 0x1F or 0x7F <= code <= 0x9F:
            return None
    parts = raw.split("/")
    if ".." in parts:
        return None
    cleaned = [part for part in parts if part and part != "."]
    if not cleaned:
        return None
    return "/".join(cleaned)


def _truncate(text: str) -> str:
    if len(text) <= _MAX_CONTEXT_CHARS:
        return text
    return text[: _MAX_CONTEXT_CHARS - 1] + "…"


def _escape_non_printable(raw: str) -> str:
    chunks: list[str] = []
    for char in raw:
        code = ord(char)
        if 0x20 <= code <= 0x7E:
            chunks.append(char)
        else:
            # 非打印字符统一按 UTF-8 字节转义为 \xNN，保持输出为可打印 ASCII。
            chunks.extend(f"\\x{byte:02x}" for byte in char.encode("utf-8"))
    return "".join(chunks)


def log_context_path(path: str) -> str:
    """日志渲染用路径：canonical path 只做 512 字符截断，不转义。"""
    return _truncate(path)


def safe_member_context(raw: str) -> str:
    """无法 canonical 化的原始成员名：先转义可打印 ASCII 之外的字符再截断。"""
    return _truncate(_escape_non_printable(raw))


# --- 常规文件判定 ---------------------------------------------------------


def _unix_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(_unix_mode(info))


def is_regular_file(info: zipfile.ZipInfo) -> bool:
    """按名称与 ``create_system`` 分派判定常规文件。

    目录项恒以名称是否以 ``/`` 结尾为准；Unix mode 规则只在
    ``create_system == 3`` 时生效，MS-DOS 属性位规则只在
    ``create_system == 0`` 时生效。
    """
    if info.filename.endswith("/"):
        return False
    if info.create_system == 0:
        return not (info.external_attr & 0x10)
    if info.create_system == 3:
        mode = _unix_mode(info)
        file_type = stat.S_IFMT(mode)
        if file_type == 0:
            # 归档未写文件类型位（含 mode == 0）：按常规文件处理。
            return True
        return stat.S_ISREG(mode)
    return True


# --- manifest 发现 --------------------------------------------------------


def discover_manifest(archive: zipfile.ZipFile) -> tuple[str, zipfile.ZipInfo]:
    """定位唯一顶层 ``*_content_list_v2.json``。

    位于子目录的成员不参与定位；候选必须能 canonical 化且是常规文件。
    """
    top_level: list[str] = []
    candidates: list[tuple[str, zipfile.ZipInfo]] = []

    for info in archive.infolist():
        raw = info.filename
        if "/" in raw:
            continue
        canonical = canonicalize_member_path(raw)
        if canonical is None:
            top_level.append("!" + safe_member_context(raw))
        else:
            top_level.append(canonical)
        if not raw.endswith(_MANIFEST_SUFFIX):
            continue
        if canonical is None:
            raise ResultExtractionArchiveError(
                "unsafe_member", member=safe_member_context(raw)
            )
        if not is_regular_file(info):
            raise ResultExtractionArchiveError("unsafe_member", member=canonical)
        candidates.append((canonical, info))

    if not candidates:
        top_level.sort()
        raise ResultExtractionManifestError(
            "not_found",
            top_level_members=tuple(
                top_level[:_MAX_TOP_LEVEL_MEMBERS_IN_ERROR]
            ),
            top_level_member_count=len(top_level),
        )

    if len(candidates) > 1:
        paths = sorted(path for path, _ in candidates)
        raise ResultExtractionManifestError(
            "ambiguous",
            candidates=tuple(paths[:_MAX_CANDIDATES_IN_ERROR]),
            candidate_count=len(candidates),
        )

    return candidates[0]


# --- 图片收集 -------------------------------------------------------------


def collect_images(
    archive: zipfile.ZipFile,
    limits: ExtractionLimits,
) -> list[tuple[str, zipfile.ZipInfo]]:
    """收集顶层 ``images/`` 下的全部常规文件，返回按 canonical path 升序的条目。"""
    entries: list[tuple[str, zipfile.ZipInfo]] = []
    seen: set[str] = set()

    for info in archive.infolist():
        raw = info.filename
        canonical = canonicalize_member_path(raw)
        if canonical is None:
            # 段相等而非子串匹配：my_images/a.jpg 不属于图片根。
            if any(segment == _IMAGES_DIRNAME for segment in raw.split("/")):
                raise ResultExtractionArchiveError(
                    "unsafe_member", member=safe_member_context(raw)
                )
            continue
        if not canonical.startswith(_IMAGES_DIRNAME + "/"):
            continue
        if not is_regular_file(info):
            if _is_symlink(info):
                raise ResultExtractionArchiveError("unsafe_member", member=canonical)
            # 目录项等其他非常规文件：忽略。
            continue

        entries.append((canonical, info))
        if len(entries) > limits.max_images:
            raise ResultExtractionLimitError(
                "image_count",
                limit=limits.max_images,
                actual=len(entries),
            )
        if canonical in seen:
            raise ResultExtractionArchiveError("duplicate_member", member=canonical)
        seen.add(canonical)

    declared_total = sum(info.file_size for _, info in entries)
    if declared_total > limits.max_total_image_bytes:
        raise ResultExtractionLimitError(
            "total_image_bytes",
            limit=limits.max_total_image_bytes,
            actual=declared_total,
        )

    entries.sort(key=lambda item: item[0])
    return entries


# --- 有界成员读取 ---------------------------------------------------------


def read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    limit: int,
    resource: str,
    member: str,
) -> bytes:
    """有界读取一个成员，并把读取失败映射为分类异常。"""
    if info.flag_bits & 0x1:
        raise ResultExtractionArchiveError("encrypted_member", member=member)
    if info.file_size > limit:
        raise ResultExtractionLimitError(
            resource,
            limit=limit,
            actual=info.file_size,
            member=member,
        )

    try:
        with archive.open(info) as handle:
            data = handle.read(limit + 1)
    except NotImplementedError:
        # 不支持的压缩方法：原始消息不含成员名，仍按契约切断异常链。
        raise ResultExtractionArchiveError(
            "unsupported_compression", member=member
        ) from None
    except RuntimeError:
        # ``zipfile`` 的加密错误消息内嵌成员名，必须切断异常链。
        raise ResultExtractionArchiveError("encrypted_member", member=member) from None
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise ResultExtractionArchiveError("corrupt_member", member=member) from exc
    except OSError as exc:
        raise ResultExtractionArchiveError("read_failed", member=member) from exc

    if len(data) > limit:
        # 冗余断言：zipfile 把读取钳制在声明大小内，正常情况下不可达。
        raise ResultExtractionLimitError(
            resource,
            limit=limit,
            actual=len(data),
            member=member,
        )
    if len(data) != info.file_size:
        raise ResultExtractionArchiveError("corrupt_member", member=member)
    return data


# --- EOCD 成员数前置预检 --------------------------------------------------


def member_count_bound(stream: io.BufferedIOBase) -> int | None:
    """从流尾部 EOCD 推导成员数量上界；不可判定时返回 ``None``。

    只读尾部窗口，不改变调用方游标语义（编排层统一恢复）。判定公式为
    ``max(count_exact, ceil(cd_size / 46))``；``count_exact`` 在 16 位计数字段
    溢出时取 0。前置预检只为快速拒绝诚实归档，不是安全边界。
    """
    try:
        stream.seek(0, io.SEEK_END)
        size = stream.tell()
        if size < _EOCD_MIN_SIZE:
            return None
        window_size = min(size, _EOCD_TAIL_BYTES)
        stream.seek(size - window_size, io.SEEK_SET)
        window = stream.read(window_size)
    except MemoryError:
        raise
    except Exception:  # noqa: BLE001 - 预检不可判定时跳过，由后置检查兜底
        return None

    if not isinstance(window, (bytes, bytearray)) or len(window) != window_size:
        return None
    window = bytes(window)

    index = window.rfind(_EOCD_SIGNATURE)
    if index < 0 or index + _EOCD_HEADER_SIZE > len(window):
        return None

    (
        _signature,
        disk_number,
        cd_start_disk,
        entries_on_disk,
        entries_total,
        cd_size,
        _cd_offset,
        comment_length,
    ) = _EOCD_STRUCT.unpack_from(window, index)

    # 自洽性校验：EOCD 定长部分必须结束于窗口尾部；单盘归档。
    if index + _EOCD_HEADER_SIZE + comment_length != len(window):
        return None
    if disk_number != 0 or cd_start_disk != 0 or entries_on_disk != entries_total:
        return None
    if cd_size == _CD_SIZE_OVERFLOW:
        return None

    count_exact = 0 if entries_total == _ENTRY_COUNT_OVERFLOW else entries_total
    return max(
        count_exact,
        (cd_size + _CD_RECORD_MIN_BYTES - 1) // _CD_RECORD_MIN_BYTES,
    )


__all__ = [
    "canonicalize_member_path",
    "collect_images",
    "discover_manifest",
    "is_regular_file",
    "log_context_path",
    "member_count_bound",
    "read_member",
    "safe_member_context",
]
