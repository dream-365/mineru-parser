"""基于 Hypothesis 的性质测试与正文泄漏哨兵测试（AC-7.6 / AC-7.7）。"""

from __future__ import annotations

import io
import json
import zipfile

from hypothesis import given, settings, strategies as st
from pydantic import BaseModel

from mineru_parser import ExtractionLimits
from mineru_parser._extractor import (
    ResultExtractionError,
    ResultExtractionValidationError,
    canonicalize_member_path,
    extract_result,
)

MANIFEST_NAME = "doc_content_list_v2.json"

_positive_int = st.integers(min_value=1, max_value=4096)
_limits = st.builds(
    ExtractionLimits,
    max_manifest_bytes=_positive_int,
    max_image_bytes=_positive_int,
    max_total_image_bytes=_positive_int,
    max_images=_positive_int,
    max_members=_positive_int,
)


@settings(max_examples=60, deadline=None)
@given(data=st.binary(max_size=512), limits=_limits)
def test_property_invariants(data, limits):
    """任意字节串 + 任意合法限额：要么分类失败，要么满足全部不变式。"""
    try:
        result = extract_result(io.BytesIO(data), limits=limits)
    except ResultExtractionError:
        return

    assert type(result) is dict
    assert set(result) == {"pages", "images"}
    assert isinstance(result["pages"], list)
    for page in result["pages"]:
        assert isinstance(page, list)
        for block in page:
            assert isinstance(block, BaseModel)

    paths = [image["path"] for image in result["images"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    for image in result["images"]:
        assert isinstance(image["path"], str)
        assert canonicalize_member_path(image["path"]) == image["path"]
        assert isinstance(image["bytes"], bytes)
        assert type(image["bytes"]) is bytes


_safe_segment = st.from_regex(r"[A-Za-z0-9_-]{1,12}", fullmatch=True)


@settings(max_examples=40, deadline=None)
@given(
    entries=st.lists(
        st.tuples(_safe_segment, st.binary(max_size=128)),
        min_size=0,
        max_size=5,
        unique_by=lambda item: item[0],
    )
)
def test_property_success_path_invariants(entries):
    """合成归档的成功路径：排序、去重、字节精确、页面模型。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(
                [[
                    {
                        "type": "paragraph",
                        "content": {
                            "paragraph_content": [{"type": "text", "content": "x"}]
                        },
                        "bbox": [0, 0, 1, 1],
                    }
                ]]
            ).encode(),
        )
        for name, data in entries:
            archive.writestr(f"images/{name}.bin", data)

    result = extract_result(io.BytesIO(buffer.getvalue()))
    expected = {f"images/{name}.bin": data for name, data in entries}
    assert [image["path"] for image in result["images"]] == sorted(expected)
    for image in result["images"]:
        assert image["bytes"] == expected[image["path"]]
        assert len(image["bytes"]) == len(expected[image["path"]])


_sentinel = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=6,
    max_size=20,
).map(lambda value: "SENTINEL" + value)


@settings(max_examples=40, deadline=None)
@given(sentinel=_sentinel)
def test_no_content_leak_sentinel_union_tag_invalid(sentinel):
    payload = [
        [
            {
                "type": sentinel,
                "content": {"paragraph_content": []},
                "bbox": [0, 0, 1, 1],
            }
        ]
    ]
    _assert_no_leak(payload, sentinel, "unknown_block_type")


@settings(max_examples=40, deadline=None)
@given(sentinel=_sentinel)
def test_no_content_leak_sentinel_union_tag_not_found(sentinel):
    payload = [
        [
            {
                "content": {"paragraph_content": [{"type": "text", "content": sentinel}]},
                "bbox": [0, 0, 1, 1],
            }
        ]
    ]
    _assert_no_leak(payload, sentinel, "unknown_block_type")


def _assert_no_leak(payload, sentinel: str, category: str) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(MANIFEST_NAME, json.dumps(payload).encode())

    try:
        extract_result(io.BytesIO(archive.getvalue()))
    except ResultExtractionValidationError as exc:
        assert exc.category == category
        assert exc.__cause__ is None
        assert exc.__context__ is None
        assert sentinel not in str(exc)
        for issue in exc.issues:
            assert sentinel not in issue["msg"]
            assert sentinel not in str(issue["loc"])
            assert sentinel not in issue["type"]
    else:  # pragma: no cover - 哨兵输入必然触发校验失败
        raise AssertionError("expected validation failure")
