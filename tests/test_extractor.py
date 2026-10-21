"""Result Extractor 契约测试：全部使用内存 ZIP，无网络、无磁盘依赖。"""

from __future__ import annotations

import io
import json
import logging
import struct
import tracemalloc
import warnings
import zipfile

import pytest

import mineru_parser
from mineru_parser import (
    DEFAULT_EXTRACTION_LIMITS,
    ExtractionLimits,
    MinerUError,
    MinerUParserError,
    ResultDownloadError,
    ResultExtractionArchiveError,
    ResultExtractionConfigurationError,
    ResultExtractionError,
    ResultExtractionLimitError,
    ResultExtractionManifestError,
    ResultExtractionValidationError,
    canonicalize_member_path,
    extract_result,
)
from mineru_parser.extractor import _manifest, _members
from mineru_parser.extractor.extractor import (
    _error_log_fields,
    _metric_tags,
    _outcome_for,
    _validate_stream,
)
from mineru_parser.schema.content_v2 import ParagraphBlock, TitleBlock

MANIFEST_NAME = "doc_content_list_v2.json"


# --- 测试辅助 -------------------------------------------------------------


def paragraph(text: str = "hello", **extra) -> dict:
    block = {
        "type": "paragraph",
        "content": {
            "paragraph_content": [{"type": "text", "content": text}],
        },
        "bbox": [0, 0, 10, 10],
    }
    block.update(extra)
    return block


def document(*blocks: dict, pages: int = 1) -> bytes:
    if not blocks:
        return b"[]"
    return json.dumps([list(blocks)] * pages).encode()


def member(
    name: str,
    data: bytes = b"",
    *,
    create_system: int | None = None,
    external_attr: int | None = None,
) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    if create_system is not None:
        info.create_system = create_system
    if external_attr is not None:
        info.external_attr = external_attr
    return info, data


def symlink(name: str, target: bytes = b"target") -> tuple[zipfile.ZipInfo, bytes]:
    return member(name, target, create_system=3, external_attr=0o120777 << 16)


def make_zip(
    *entries: tuple[zipfile.ZipInfo, bytes],
    compression: int = zipfile.ZIP_STORED,
    comment: bytes | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for info, data in entries:
            info.compress_type = compression
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                archive.writestr(info, data)
        if comment is not None:
            archive.comment = comment
    return buffer.getvalue()


def package(manifest: bytes | None = None, images: dict[str, bytes] | None = None) -> bytes:
    entries = [member(MANIFEST_NAME, document(paragraph()) if manifest is None else manifest)]
    for path, data in (images or {}).items():
        entries.append(member(path, data))
    return make_zip(*entries)


def _central_directory_start(data: bytes) -> int:
    eocd = data.rfind(b"PK\x05\x06")
    assert eocd >= 0
    return struct.unpack_from("<L", data, eocd + 16)[0]


def _patch_central_directory(
    data: bytes,
    target: str,
    offset: int,
    value: bytes,
) -> bytes:
    eocd = data.rfind(b"PK\x05\x06")
    count = struct.unpack_from("<H", data, eocd + 10)[0]
    position = _central_directory_start(data)
    for _ in range(count):
        assert data[position : position + 4] == b"PK\x01\x02"
        name_len = struct.unpack_from("<H", data, position + 28)[0]
        extra_len = struct.unpack_from("<H", data, position + 30)[0]
        comment_len = struct.unpack_from("<H", data, position + 32)[0]
        name = data[position + 46 : position + 46 + name_len].decode("utf-8")
        if name == target:
            mutable = bytearray(data)
            start = position + offset
            mutable[start : start + len(value)] = value
            return bytes(mutable)
        position += 46 + name_len + extra_len + comment_len
    raise AssertionError(f"member {target!r} not found")


def _patch_eocd(data: bytes, offset: int, value: bytes) -> bytes:
    eocd = data.rfind(b"PK\x05\x06")
    mutable = bytearray(data)
    mutable[eocd + offset : eocd + offset + len(value)] = value
    return bytes(mutable)


def _corrupt_member_data(data: bytes, target: str) -> bytes:
    eocd = data.rfind(b"PK\x05\x06")
    count = struct.unpack_from("<H", data, eocd + 10)[0]
    position = _central_directory_start(data)
    for _ in range(count):
        name_len = struct.unpack_from("<H", data, position + 28)[0]
        extra_len = struct.unpack_from("<H", data, position + 30)[0]
        comment_len = struct.unpack_from("<H", data, position + 32)[0]
        name = data[position + 46 : position + 46 + name_len].decode("utf-8")
        if name == target:
            local_offset = struct.unpack_from("<L", data, position + 42)[0]
            local_name_len = struct.unpack_from("<H", data, local_offset + 26)[0]
            local_extra_len = struct.unpack_from("<H", data, local_offset + 28)[0]
            data_start = local_offset + 30 + local_name_len + local_extra_len
            mutable = bytearray(data)
            mutable[data_start] ^= 0xFF
            return bytes(mutable)
        position += 46 + name_len + extra_len + comment_len
    raise AssertionError(f"member {target!r} not found")


class Metrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, dict[str, str]]] = []

    def __call__(self, name: str, value: float, tags) -> None:
        self.calls.append((name, value, dict(tags)))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    def by_name(self, name: str):
        return [call for call in self.calls if call[0] == name]


# --- 公共契约与异常层次 ---------------------------------------------------


def test_public_exports():
    expected = [
        "DEFAULT_EXTRACTION_LIMITS",
        "ExtractedImage",
        "ExtractedResult",
        "ExtractionIssue",
        "ExtractionLimits",
        "ResultExtractionArchiveError",
        "ResultExtractionConfigurationError",
        "ResultExtractionError",
        "ResultExtractionLimitError",
        "ResultExtractionManifestError",
        "ResultExtractionValidationError",
        "canonicalize_member_path",
        "extract_result",
        "MinerUParserError",
    ]
    for name in expected:
        assert hasattr(mineru_parser, name)
        assert name in mineru_parser.__all__

    import mineru_parser.extractor as extractor_package

    for name in expected:
        if name == "MinerUParserError":
            continue
        assert hasattr(extractor_package, name)
        assert name in extractor_package.__all__


def test_error_hierarchy_and_common_root():
    assert issubclass(MinerUError, MinerUParserError)
    assert issubclass(ResultDownloadError, MinerUParserError)
    assert issubclass(ResultExtractionError, MinerUParserError)
    assert issubclass(ResultExtractionConfigurationError, ResultExtractionError)
    assert issubclass(ResultExtractionArchiveError, ResultExtractionError)
    assert issubclass(ResultExtractionManifestError, ResultExtractionError)
    assert issubclass(ResultExtractionValidationError, ResultExtractionError)
    assert issubclass(ResultExtractionLimitError, ResultExtractionError)

    assert not issubclass(ResultExtractionError, MinerUError)
    assert not issubclass(MinerUError, ResultExtractionError)
    assert not issubclass(ResultExtractionError, ResultDownloadError)
    assert not issubclass(ResultDownloadError, ResultExtractionError)


def test_limits_defaults_and_validation():
    assert DEFAULT_EXTRACTION_LIMITS == ExtractionLimits(
        max_manifest_bytes=16 * 1024 * 1024,
        max_image_bytes=32 * 1024 * 1024,
        max_total_image_bytes=160 * 1024 * 1024,
        max_images=10_000,
        max_members=100_000,
    )

    for field in (
        "max_manifest_bytes",
        "max_image_bytes",
        "max_total_image_bytes",
        "max_images",
        "max_members",
    ):
        with pytest.raises(ResultExtractionConfigurationError) as error:
            ExtractionLimits(**{field: 0})
        assert error.value.field == field
        with pytest.raises(ResultExtractionConfigurationError) as error:
            ExtractionLimits(**{field: True})
        assert error.value.field == field

    with pytest.raises(ResultExtractionConfigurationError) as error:
        ExtractionLimits(max_manifest_bytes=0, max_images=0)
    assert error.value.field == "max_manifest_bytes"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("images/a.jpg", "images/a.jpg"),
        ("images//a.jpg", "images/a.jpg"),
        ("images/./a.jpg", "images/a.jpg"),
        ("./images/a.jpg", "images/a.jpg"),
        ("images/sub/../a.jpg", None),
        ("../images/a.jpg", None),
        ("/images/a.jpg", None),
        ("images\\a.jpg", None),
        ("images/\x00a.jpg", None),
        ("images/\x01a.jpg", None),
        ("images/\x7fa.jpg", None),
        ("images/\x9fa.jpg", None),
        ("", None),
        (".", None),
        ("../", None),
        ("images/", "images"),
        ("Images/a.jpg", "Images/a.jpg"),
    ],
)
def test_canonicalize_member_path(raw, expected):
    assert canonicalize_member_path(raw) == expected


def test_canonicalize_is_idempotent():
    for raw in ("images/a.jpg", "./images//a.jpg", "images", "a/b/c"):
        once = canonicalize_member_path(raw)
        if once is not None:
            assert canonicalize_member_path(once) == once


# --- 基本提取 -------------------------------------------------------------


def test_extract_basic_contract():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph("first"), paragraph("second"))),
        member("images/b.jpg", b"B"),
        member("images/a.jpg", b"A"),
    )
    stream = io.BytesIO(archive)
    result = extract_result(stream)

    assert type(result) is dict
    assert set(result) == {"pages", "images"}
    assert len(result["pages"]) == 1
    assert all(isinstance(block, ParagraphBlock) for block in result["pages"][0])
    assert [image["path"] for image in result["images"]] == [
        "images/a.jpg",
        "images/b.jpg",
    ]
    assert [image["bytes"] for image in result["images"]] == [b"A", b"B"]
    assert all(type(image["bytes"]) is bytes for image in result["images"])
    assert stream.closed is False


def test_extract_is_deterministic_and_returns_fresh_objects():
    archive = package(images={"images/a.jpg": b"A"})
    first = extract_result(io.BytesIO(archive))
    second = extract_result(io.BytesIO(archive))
    assert first is not second
    assert first["images"][0] is not second["images"][0]
    assert [block.model_dump() for block in first["pages"][0]] == [
        block.model_dump() for block in second["pages"][0]
    ]
    assert first["images"] == second["images"]


def test_empty_document_and_empty_page():
    assert extract_result(io.BytesIO(package(manifest=b"[]")))["pages"] == []
    assert extract_result(io.BytesIO(package(manifest=b"[[]]")))["pages"] == [[]]


def test_pages_are_pydantic_models_not_dicts():
    archive = package(
        manifest=json.dumps(
            [
                [
                    {
                        "type": "title",
                        "content": {
                            "title_content": [{"type": "text", "content": "T"}],
                        },
                        "bbox": [0, 0, 1, 1],
                    }
                ]
            ]
        ).encode()
        + b" \n"
    )
    result = extract_result(io.BytesIO(archive))
    assert isinstance(result["pages"][0][0], TitleBlock)


def test_bom_is_stripped():
    archive = package(manifest=b"\xef\xbb\xbf" + document(paragraph()))
    assert len(extract_result(io.BytesIO(archive))["pages"]) == 1


def test_stream_position_restored_on_success_and_failure():
    archive = package(images={"images/a.jpg": b"A"})
    stream = io.BytesIO(archive)
    stream.seek(3)
    extract_result(stream)
    assert stream.tell() == 3

    stream = io.BytesIO(b"not a zip")
    stream.seek(0)
    with pytest.raises(ResultExtractionArchiveError):
        extract_result(stream)
    assert stream.tell() == 0
    assert stream.closed is False


def test_stream_not_closed_on_failure():
    stream = io.BytesIO(b"")
    with pytest.raises(ResultExtractionArchiveError):
        extract_result(stream)
    assert stream.closed is False


class _NotSeekable(io.BytesIO):
    def seekable(self) -> bool:
        return False


class _NotReadable(io.BytesIO):
    def readable(self) -> bool:
        return False


class _BadTell(io.BytesIO):
    def tell(self):
        return "not-an-int"


def test_invalid_streams_rejected_before_zip_read():
    for stream in (
        io.StringIO("text"),
        _NotSeekable(b"x"),
        _NotReadable(b"x"),
        _BadTell(b"x"),
        io.BytesIO(b"x"),
        object(),
    ):
        if isinstance(stream, io.BytesIO) and not isinstance(
            stream, (_NotSeekable, _NotReadable, _BadTell)
        ):
            stream.close()
        with pytest.raises(ResultExtractionConfigurationError) as error:
            extract_result(stream)
        assert error.value.field == "stream"


def test_invalid_limits_argument_rejected():
    with pytest.raises(ResultExtractionConfigurationError) as error:
        extract_result(io.BytesIO(package()), limits=object())  # type: ignore[arg-type]
    assert error.value.field == "limits"


def test_invalid_hooks_rejected_before_telemetry():
    with pytest.raises(ResultExtractionConfigurationError) as error:
        extract_result(io.BytesIO(package()), on_metric="nope")  # type: ignore[arg-type]
    assert error.value.field == "on_metric"

    metrics = Metrics()
    with pytest.raises(ResultExtractionConfigurationError) as error:
        extract_result(io.BytesIO(package()), on_metric=metrics, correlation_id=1)  # type: ignore[arg-type]
    assert error.value.field == "correlation_id"
    assert metrics.calls == []


# --- manifest 定位 --------------------------------------------------------


def test_manifest_discovery_root():
    archive = package()
    assert len(extract_result(io.BytesIO(archive))["pages"]) == 1


def test_manifest_nested_not_found():
    archive = make_zip(
        member("result/doc_content_list_v2.json", document(paragraph())),
        member("images/a.jpg", b"A"),
    )
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "not_found"
    assert error.value.top_level_member_count == 0
    assert error.value.top_level_members == ()


def test_manifest_not_found_carries_top_level_members():
    entries = [member(f"file{i:02}.txt", b"x") for i in range(25)]
    entries.append(member("bad\x01name.txt", b"x"))
    archive = make_zip(*entries)
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "not_found"
    assert error.value.top_level_member_count == 26
    assert len(error.value.top_level_members) == 20
    assert error.value.top_level_members == tuple(
        sorted(error.value.top_level_members)
    )
    assert "!bad\\x01name.txt" in error.value.top_level_members


def test_manifest_ambiguous():
    archive = make_zip(
        member("b_content_list_v2.json", document(paragraph())),
        member("a_content_list_v2.json", document(paragraph())),
    )
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "ambiguous"
    assert error.value.candidate_count == 2
    assert error.value.candidates == (
        "a_content_list_v2.json",
        "b_content_list_v2.json",
    )


def test_duplicate_manifest_member_is_ambiguous():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member(MANIFEST_NAME, document(paragraph())),
    )
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "ambiguous"
    assert error.value.candidate_count == 2


@pytest.mark.parametrize(
    "name",
    [
        "doc_content_list.json",
        "doc_content_list_v2.JSON",
        "doc_content_list_v2.json.bak",
        "doc_content_list_v2.json/",
    ],
)
def test_manifest_suffix_is_strict(name):
    archive = make_zip(member(name, document(paragraph())))
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "not_found"


def test_manifest_directory_with_suffix_is_not_candidate():
    archive = make_zip(
        member("doc_content_list_v2.json/", b""),
        member(MANIFEST_NAME, document(paragraph())),
    )
    assert len(extract_result(io.BytesIO(archive))["pages"]) == 1


def test_macos_resource_fork_ignored():
    archive = make_zip(
        member("__MACOSX/._doc_content_list_v2.json", b"junk"),
        member(MANIFEST_NAME, document(paragraph())),
    )
    assert len(extract_result(io.BytesIO(archive))["pages"]) == 1


def test_unsafe_manifest_member_names():
    for name in ("bad\\doc_content_list_v2.json", "bad\x01doc_content_list_v2.json"):
        archive = make_zip(member(name, document(paragraph())))
        with pytest.raises(ResultExtractionArchiveError) as error:
            extract_result(io.BytesIO(archive))
        assert error.value.reason == "unsafe_member"
        assert error.value.member is not None


def test_symlink_manifest_rejected():
    archive = make_zip(symlink(MANIFEST_NAME))
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "unsafe_member"
    assert error.value.member == MANIFEST_NAME


def test_msdos_archive_uses_dos_attributes_not_unix_mode():
    # 高位残留的 Unix symlink 位在 create_system == 0 时不得被解释。
    archive = make_zip(
        member(
            MANIFEST_NAME,
            document(paragraph()),
            create_system=0,
            external_attr=0o120777 << 16,
        )
    )
    assert len(extract_result(io.BytesIO(archive))["pages"]) == 1


def test_manifest_path_not_truncated_in_structured_fields():
    long_name = "a" * 600 + "_content_list_v2.json"
    archive = make_zip(
        member(long_name, json.dumps([[{"type": "nope"}]]).encode())
    )
    with pytest.raises(ResultExtractionValidationError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.manifest_path == long_name


# --- manifest 读取与校验 --------------------------------------------------


def test_manifest_too_large_declared():
    manifest = document(paragraph())
    archive = package(manifest=manifest)
    limits = ExtractionLimits(max_manifest_bytes=10)
    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(io.BytesIO(archive), limits=limits)
    assert error.value.resource == "manifest"
    assert error.value.actual == len(manifest)
    assert error.value.member == MANIFEST_NAME


def test_manifest_invalid_utf8():
    archive = package(manifest=b"\xff\xfe\x00")
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "invalid_encoding"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "payload",
    [
        b"{not json",
        b"[] trailing",
        b"[" * 5000 + b"]" * 5000,
    ],
)
def test_manifest_invalid_json(payload):
    archive = package(manifest=payload)
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "invalid_json"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_manifest_encrypted():
    archive = _patch_central_directory(
        package(), MANIFEST_NAME, 8, struct.pack("<H", 0x1)
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "encrypted_member"
    assert error.value.member == MANIFEST_NAME


def test_manifest_unsupported_compression():
    archive = _patch_central_directory(
        package(), MANIFEST_NAME, 10, struct.pack("<H", 99)
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "unsupported_compression"
    assert error.value.member == MANIFEST_NAME


def test_manifest_corrupt_crc():
    archive = _corrupt_member_data(package(), MANIFEST_NAME)
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "corrupt_member"


def test_read_member_length_mismatch_is_corrupt():
    class FakeHandle:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self, size: int) -> bytes:
            return self._data[:size]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeArchive:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def open(self, info):
            return FakeHandle(self._data)

    info = zipfile.ZipInfo("images/a.jpg")
    info.file_size = 5
    with pytest.raises(ResultExtractionArchiveError) as error:
        _members.read_member(
            FakeArchive(b"abc"),  # type: ignore[arg-type]
            info,
            limit=100,
            resource="image",
            member="images/a.jpg",
        )
    assert error.value.reason == "corrupt_member"


@pytest.mark.parametrize(
    ("raised", "reason"),
    [
        (NotImplementedError("no"), "unsupported_compression"),
        (RuntimeError("File is encrypted"), "encrypted_member"),
        (zipfile.BadZipFile("bad crc"), "corrupt_member"),
        (OSError("boom"), "read_failed"),
    ],
)
def test_read_member_error_mapping(raised, reason):
    class FakeArchive:
        def open(self, info):
            raise raised

    info = zipfile.ZipInfo("images/a.jpg")
    info.file_size = 1
    with pytest.raises(ResultExtractionArchiveError) as error:
        _members.read_member(
            FakeArchive(),  # type: ignore[arg-type]
            info,
            limit=10,
            resource="image",
            member="images/a.jpg",
        )
    assert error.value.reason == reason
    assert error.value.member == "images/a.jpg"


def test_zipfile_oserror_maps_to_invalid_zip(monkeypatch):
    archive = package()

    def explode(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(zipfile, "ZipFile", explode)
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "invalid_zip"


def test_read_member_redundant_actual_limit():
    class FakeHandle:
        def read(self, size: int) -> bytes:
            return b"abc"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeArchive:
        def open(self, info):
            return FakeHandle()

    info = zipfile.ZipInfo("images/a.jpg")
    info.file_size = 2
    with pytest.raises(ResultExtractionLimitError) as error:
        _members.read_member(
            FakeArchive(),  # type: ignore[arg-type]
            info,
            limit=2,
            resource="image",
            member="images/a.jpg",
        )
    assert error.value.resource == "image"
    assert error.value.actual == 3


# --- Schema 校验与错误清洗 ------------------------------------------------


@pytest.mark.parametrize(
    ("manifest", "category"),
    [
        ([[{"type": "bogus", "content": {}, "bbox": [0, 0, 1, 1]}]], "unknown_block_type"),
        ([[{"content": {}, "bbox": [0, 0, 1, 1]}]], "unknown_block_type"),
        (
            [[{"type": "paragraph", "content": {"paragraph_content": []}}]],
            "invalid_bbox",
        ),
        (
            [
                [
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": ["a", "b", "c", "d"],
                    }
                ]
            ],
            "invalid_bbox",
        ),
        ([paragraph()], "root_shape"),
        ({"not": "a list"}, "root_shape"),
        (
            [[{"type": "paragraph", "bbox": [0, 0, 1, 1]}]],
            "missing_field",
        ),
        (
            [[{"type": "table", "content": {"table_type": "bogus"}, "bbox": [0, 0, 1, 1]}]],
            "other",
        ),
    ],
)
def test_validation_category(manifest, category):
    archive = package(manifest=json.dumps(manifest).encode())
    with pytest.raises(ResultExtractionValidationError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.category == category
    assert error.value.manifest_path == MANIFEST_NAME


def test_validation_issues_are_sanitized_and_capped():
    blocks = [{"type": "nope", "content": {}, "bbox": [0, 0, 1, 1]} for _ in range(25)]
    archive = package(manifest=json.dumps([blocks]).encode())
    with pytest.raises(ResultExtractionValidationError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.issue_count == 25
    assert len(error.value.issues) == 20
    for issue in error.value.issues:
        assert set(issue) == {"loc", "type", "msg"}
        assert isinstance(issue["loc"], tuple)


def test_validation_error_does_not_leak_sentinel():
    sentinel = "SENTINEL-7f3a9c"
    manifest = json.dumps(
        [[{"type": sentinel, "content": {"paragraph_content": []}, "bbox": [0, 0, 1, 1]}]]
    ).encode()
    with pytest.raises(ResultExtractionValidationError) as error:
        extract_result(io.BytesIO(package(manifest=manifest)))

    exc = error.value
    assert exc.category == "unknown_block_type"
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert sentinel not in str(exc)
    for issue in exc.issues:
        assert sentinel not in issue["msg"]
        assert sentinel not in str(issue["loc"])
        assert sentinel not in issue["type"]


def test_missing_block_type_sentinel_and_context():
    sentinel = "SENTINEL-missing-type"
    # 哨兵放在 content 中：union_tag_not_found 的 msg 不内嵌输入值，但正文
    # 仍不得进入异常。
    manifest = json.dumps(
        [[{"content": {"paragraph_content": sentinel}, "bbox": [0, 0, 1, 1]}]]
    ).encode()
    with pytest.raises(ResultExtractionValidationError) as error:
        extract_result(io.BytesIO(package(manifest=manifest)))
    exc = error.value
    assert exc.category == "unknown_block_type"
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert sentinel not in str(exc)
    assert all(sentinel not in issue["msg"] for issue in exc.issues)


def test_extra_fields_are_ignored():
    manifest = json.dumps([[paragraph(extra_field="ignored")]]).encode()
    result = extract_result(io.BytesIO(package(manifest=manifest)))
    assert len(result["pages"][0]) == 1


def test_schema_adapter_is_module_level():
    import importlib

    reloaded = importlib.import_module("mineru_parser.extractor._manifest")
    assert reloaded is _manifest
    assert _manifest._SCHEMA is reloaded._SCHEMA


# --- 图片提取 -------------------------------------------------------------


def test_images_at_archive_root_only():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("images/a.jpg", b"A"),
        member("result/images/b.jpg", b"B"),
        member("Images/c.jpg", b"C"),
    )
    result = extract_result(io.BytesIO(archive))
    assert [image["path"] for image in result["images"]] == ["images/a.jpg"]


def test_images_sorted_and_nested_paths_canonicalized():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("images/z/b.jpg", b"B"),
        member("images/./a.jpg", b"A"),
        member("images/sub/c.jpg", b"C"),
        member("images/empty.bin", b""),
    )
    result = extract_result(io.BytesIO(archive))
    assert [image["path"] for image in result["images"]] == [
        "images/a.jpg",
        "images/empty.bin",
        "images/sub/c.jpg",
        "images/z/b.jpg",
    ]
    assert result["images"][1]["bytes"] == b""


def test_canonicalize_matches_internal_image_paths():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("./images//a.jpg", b"A"),
    )
    result = extract_result(io.BytesIO(archive))
    assert result["images"][0]["path"] == canonicalize_member_path("./images//a.jpg")


def test_missing_images_root_returns_empty():
    archive = make_zip(member(MANIFEST_NAME, document(paragraph())))
    assert extract_result(io.BytesIO(archive))["images"] == []

    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("images/", b""),
    )
    assert extract_result(io.BytesIO(archive))["images"] == []


def test_duplicate_image_path_rejected():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("images/a.jpg", b"A"),
        member("images/./a.jpg", b"A2"),
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "duplicate_member"
    assert error.value.member == "images/a.jpg"


@pytest.mark.parametrize(
    "name",
    [
        "images/../secret.jpg",
        "/images/a.jpg",
        "docs/images/../notes.txt",
        "images/sub/../../escape.jpg",
    ],
)
def test_unsafe_image_path_rejected(name):
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member(name, b"X"),
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "unsafe_member"


def test_unrelated_unsafe_member_ignored():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("my_images/../notes.txt", b"X"),
        member("images\\a.jpg", b"X"),
    )
    assert extract_result(io.BytesIO(archive))["images"] == []


def test_symlink_image_rejected():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        symlink("images/a.jpg"),
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "unsafe_member"
    assert error.value.member == "images/a.jpg"


def test_encrypted_image():
    archive = _patch_central_directory(
        package(images={"images/a.jpg": b"A"}),
        "images/a.jpg",
        8,
        struct.pack("<H", 0x1),
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "encrypted_member"
    assert error.value.member == "images/a.jpg"


def test_unsupported_compression_image():
    archive = _patch_central_directory(
        package(images={"images/a.jpg": b"A"}),
        "images/a.jpg",
        10,
        struct.pack("<H", 99),
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "unsupported_compression"


def test_corrupt_image_crc():
    archive = _corrupt_member_data(
        package(images={"images/a.jpg": b"ABCDEFGH"}), "images/a.jpg"
    )
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "corrupt_member"


def test_image_limits():
    archive = package(images={"images/a.jpg": b"AAA", "images/b.jpg": b"BBB"})

    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(io.BytesIO(archive), limits=ExtractionLimits(max_images=1))
    assert (error.value.resource, error.value.limit, error.value.actual) == (
        "image_count",
        1,
        2,
    )
    assert error.value.member is None

    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(io.BytesIO(archive), limits=ExtractionLimits(max_image_bytes=2))
    assert error.value.resource == "image"
    assert error.value.actual == 3
    assert error.value.member == "images/a.jpg"

    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(
            io.BytesIO(archive),
            limits=ExtractionLimits(max_total_image_bytes=5),
        )
    assert error.value.resource == "total_image_bytes"
    assert error.value.actual == 6
    assert error.value.member is None


def test_no_cross_validation_between_pages_and_images():
    manifest = json.dumps(
        [[
            {
                "type": "image",
                "content": {"image_source": {"path": "images/missing.jpg"}},
                "bbox": [0, 0, 1, 1],
            }
        ]]
    ).encode()
    archive = make_zip(
        member(MANIFEST_NAME, manifest),
        member("images/unreferenced.jpg", b"U"),
    )
    result = extract_result(io.BytesIO(archive))
    assert [image["path"] for image in result["images"]] == [
        "images/unreferenced.jpg"
    ]


# --- 归档与限额 -----------------------------------------------------------


@pytest.mark.parametrize("payload", [b"", b"<html>error</html>", b"PK", b"x" * 30])
def test_invalid_zip(payload):
    with pytest.raises(ResultExtractionArchiveError) as error:
        extract_result(io.BytesIO(payload))
    assert error.value.reason == "invalid_zip"


def test_unrelated_member_ignored_even_if_encrypted_or_corrupt():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("images/a.jpg", b"A"),
        member("unrelated.bin", b"junk"),
    )
    archive = _patch_central_directory(
        archive, "unrelated.bin", 8, struct.pack("<H", 0x1)
    )
    archive = _corrupt_member_data(archive, "unrelated.bin")
    result = extract_result(io.BytesIO(archive))
    assert result["images"][0]["bytes"] == b"A"


def test_member_count_precheck_before_zipfile(monkeypatch):
    archive = make_zip(
        *[member(f"file{i}.txt", b"x") for i in range(4)]
    )

    def explode(*args, **kwargs):
        raise AssertionError("ZipFile must not be constructed")

    monkeypatch.setattr(zipfile, "ZipFile", explode)
    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(io.BytesIO(archive), limits=ExtractionLimits(max_members=2))
    assert error.value.resource == "member_count"
    assert error.value.actual > 2


def test_member_count_postcheck(monkeypatch):
    archive = make_zip(*[member(f"file{i}.txt", b"x") for i in range(3)])
    monkeypatch.setattr(
        "mineru_parser.extractor.extractor.member_count_bound",
        lambda stream: None,
    )
    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(io.BytesIO(archive), limits=ExtractionLimits(max_members=2))
    assert error.value.resource == "member_count"
    assert error.value.actual == 3


def test_eocd_precheck_uses_cd_size_bound():
    archive = make_zip(member("a.txt", b"x"), member("b.txt", b"x"))
    archive = _patch_eocd(archive, 12, struct.pack("<L", 46_000))
    with pytest.raises(ResultExtractionLimitError) as error:
        extract_result(io.BytesIO(archive), limits=ExtractionLimits(max_members=10))
    assert error.value.resource == "member_count"
    assert error.value.actual == 1000


def test_eocd_precheck_skips_on_cd_size_overflow():
    archive = make_zip(member("a.txt", b"x"))
    archive = _patch_eocd(archive, 12, struct.pack("<L", 0xFFFFFFFF))
    assert _members.member_count_bound(io.BytesIO(archive)) is None


def test_eocd_precheck_entry_count_overflow_uses_cd_size():
    archive = make_zip(member("a.txt", b"x"))
    archive = _patch_eocd(archive, 8, struct.pack("<H", 0xFFFF))
    archive = _patch_eocd(archive, 10, struct.pack("<H", 0xFFFF))
    bound = _members.member_count_bound(io.BytesIO(archive))
    assert bound is not None
    assert bound >= 1


@pytest.mark.parametrize("payload", [b"", b"short", b"not a zip at all" * 10])
def test_eocd_precheck_skips_unreadable(payload):
    assert _members.member_count_bound(io.BytesIO(payload)) is None


def test_fake_eocd_in_archive_comment_fails_closed():
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        comment=b"PK\x05\x06" + b"\x00" * 18,
    )
    assert _members.member_count_bound(io.BytesIO(archive)) == 0
    with pytest.raises(ResultExtractionManifestError) as error:
        extract_result(io.BytesIO(archive))
    assert error.value.reason == "not_found"


def test_no_disk_extraction(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("extraction to disk is forbidden")

    monkeypatch.setattr(zipfile.ZipFile, "extract", explode)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", explode)
    result = extract_result(io.BytesIO(package(images={"images/a.jpg": b"A"})))
    assert result["images"][0]["bytes"] == b"A"


def test_memory_bound_with_tracemalloc():
    payload = b"\x00" * (4 * 1024 * 1024)
    archive = make_zip(
        member(MANIFEST_NAME, document(paragraph())),
        member("images/big.bin", payload),
        compression=zipfile.ZIP_DEFLATED,
    )
    assert len(archive) < len(payload) // 10

    tracemalloc.start()
    try:
        result = extract_result(io.BytesIO(archive))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(result["images"][0]["bytes"]) == len(payload)
    assert peak < 32 * 1024 * 1024


# --- 生命周期与遥测 -------------------------------------------------------


def test_restore_failure_logged_without_overriding_result(monkeypatch, caplog):
    monkeypatch.setattr(
        "mineru_parser.extractor.extractor._restore_stream",
        lambda stream, position: (_ for _ in ()).throw(OSError("boom")),
    )
    with caplog.at_level(logging.WARNING, logger="mineru_parser"):
        result = extract_result(io.BytesIO(package()))
    assert len(result["pages"]) == 1
    assert any(record.message == "mineru.extract.restore_failed" for record in caplog.records)


def test_success_log_and_metrics(caplog):
    metrics = Metrics()
    caplog.set_level(logging.INFO, logger="mineru_parser")
    result = extract_result(
        io.BytesIO(package(images={"images/a.jpg": b"AAA"})),
        on_metric=metrics,
        correlation_id="corr-1",
    )
    assert len(result["pages"]) == 1

    assert metrics.names() == [
        "mineru.extract.total",
        "mineru.extract.duration_ms",
        "mineru.extract.pages",
        "mineru.extract.images",
        "mineru.extract.image_bytes",
    ]
    assert metrics.by_name("mineru.extract.total")[0][1] == 1
    assert metrics.by_name("mineru.extract.pages")[0][1] == 1
    assert metrics.by_name("mineru.extract.images")[0][1] == 1
    assert metrics.by_name("mineru.extract.image_bytes")[0][1] == 3
    assert all(tags == {"outcome": "success"} for _, _, tags in metrics.calls)

    success = [record for record in caplog.records if record.message == "mineru.extract"]
    assert len(success) == 1
    assert success[0].manifest == MANIFEST_NAME
    assert success[0].pages == 1
    assert success[0].images == 1
    assert success[0].image_bytes == 3
    assert success[0].outcome == "success"
    assert success[0].correlation_id == "corr-1"


_FAILURE_CASES = [
    (
        {"outcome": "archive_error", "reason": "invalid_zip"},
        ResultExtractionArchiveError,
        lambda metrics: extract_result(io.BytesIO(b"not zip"), on_metric=metrics),
    ),
    (
        {"outcome": "manifest_error", "reason": "not_found"},
        ResultExtractionManifestError,
        lambda metrics: extract_result(
            io.BytesIO(make_zip(member("x.txt", b"x"))), on_metric=metrics
        ),
    ),
    (
        {"outcome": "validation_error", "category": "unknown_block_type"},
        ResultExtractionValidationError,
        lambda metrics: extract_result(
            io.BytesIO(
                package(
                    manifest=json.dumps(
                        [[{"type": "nope", "content": {}, "bbox": [0, 0, 1, 1]}]]
                    ).encode()
                )
            ),
            on_metric=metrics,
        ),
    ),
    (
        {"outcome": "limit_error", "resource": "image_count"},
        ResultExtractionLimitError,
        lambda metrics: extract_result(
            io.BytesIO(package(images={"images/a.jpg": b"A", "images/b.jpg": b"B"})),
            limits=ExtractionLimits(max_images=1),
            on_metric=metrics,
        ),
    ),
    (
        {"outcome": "config_error"},
        ResultExtractionConfigurationError,
        lambda metrics: extract_result(
            io.BytesIO(package()),
            limits=object(),  # type: ignore[arg-type]
            on_metric=metrics,
        ),
    ),
]


@pytest.mark.parametrize(
    ("expected_tags", "error_type", "call"),
    _FAILURE_CASES,
    ids=[tags["outcome"] for tags, _, _ in _FAILURE_CASES],
)
def test_failure_metrics_and_outcome_mapping(expected_tags, error_type, call):
    metrics = Metrics()
    with pytest.raises(error_type):
        call(metrics)
    assert metrics.names() == [
        "mineru.extract.total",
        "mineru.extract.duration_ms",
        "mineru.extract.pages",
        "mineru.extract.images",
        "mineru.extract.image_bytes",
    ]
    for name in metrics.names():
        assert metrics.by_name(name)[0][2] == expected_tags
    assert metrics.by_name("mineru.extract.pages")[0][1] == 0
    assert metrics.by_name("mineru.extract.images")[0][1] == 0
    assert metrics.by_name("mineru.extract.image_bytes")[0][1] == 0


def test_metric_hook_failure_is_swallowed(caplog):
    def broken(name, value, tags):
        raise RuntimeError("hook boom")

    with caplog.at_level(logging.WARNING, logger="mineru_parser"):
        result = extract_result(io.BytesIO(package()), on_metric=broken)
    assert len(result["pages"]) == 1
    assert any(record.message == "mineru.metric.failed" for record in caplog.records)


def test_memory_error_propagates_unwrapped(monkeypatch):
    def explode(limits):
        raise MemoryError("oom")

    monkeypatch.setattr(
        "mineru_parser.extractor.extractor._resolve_limits", explode
    )
    with pytest.raises(MemoryError):
        extract_result(io.BytesIO(package()))


def test_keyboard_interrupt_is_not_swallowed(monkeypatch):
    def explode(limits):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "mineru_parser.extractor.extractor._resolve_limits", explode
    )
    metrics = Metrics()
    with pytest.raises(KeyboardInterrupt):
        extract_result(io.BytesIO(package()), on_metric=metrics)
    assert metrics.by_name("mineru.extract.total")[0][2] == {"outcome": "unexpected"}


def test_unexpected_exception_propagates(monkeypatch):
    metrics = Metrics()

    def explode(limits):
        raise ValueError("unexpected")

    monkeypatch.setattr(
        "mineru_parser.extractor.extractor._resolve_limits", explode
    )
    with pytest.raises(ValueError):
        extract_result(io.BytesIO(package()), on_metric=metrics)
    assert metrics.by_name("mineru.extract.total")[0][2] == {"outcome": "unexpected"}


def test_error_helpers_cover_all_branches():
    assert _outcome_for(ResultExtractionConfigurationError("stream")) == "config_error"
    assert _outcome_for(ResultExtractionArchiveError("invalid_zip")) == "archive_error"
    assert _outcome_for(ResultExtractionManifestError("not_found")) == "manifest_error"
    assert _outcome_for(ResultExtractionValidationError("m", category="other")) == (
        "validation_error"
    )
    assert _outcome_for(ResultExtractionLimitError("image")) == "limit_error"

    assert _metric_tags("success", None) == {"outcome": "success"}
    assert _metric_tags(
        "archive_error", ResultExtractionArchiveError("invalid_zip")
    ) == {"outcome": "archive_error", "reason": "invalid_zip"}
    assert _metric_tags("limit_error", ResultExtractionLimitError("manifest")) == {
        "outcome": "limit_error",
        "resource": "manifest",
    }
    assert _metric_tags(
        "validation_error",
        ResultExtractionValidationError("m", category="root_shape"),
    ) == {"outcome": "validation_error", "category": "root_shape"}

    fields = _error_log_fields(
        ResultExtractionLimitError(
            "manifest", limit=1, actual=2, member="a" * 600
        )
    )
    assert len(fields["member"]) == 512
    assert fields["member"].endswith("…")

    assert _validate_stream(io.BytesIO(b"x")) == 0
    with pytest.raises(ResultExtractionConfigurationError):
        _validate_stream(io.StringIO("x"))
    with pytest.raises(ResultExtractionConfigurationError):
        _validate_stream(None)  # type: ignore[arg-type]


# --- 真实样本 -------------------------------------------------------------


def test_real_sample_contract():
    from pathlib import Path

    archive = Path(__file__).parent / "data" / "result_001.zip"
    result = extract_result(io.BytesIO(archive.read_bytes()))

    assert len(result["pages"]) == 1
    assert len(result["pages"][0]) == 6
    assert [type(block).__name__ for block in result["pages"][0]] == [
        "TitleBlock",
        "ParagraphBlock",
        "ParagraphBlock",
        "ParagraphBlock",
        "ImageBlock",
        "ParagraphBlock",
    ]
    assert len(result["images"]) == 1
    assert result["images"][0]["path"].startswith("images/")
    assert len(result["images"][0]["bytes"]) == 13_936
