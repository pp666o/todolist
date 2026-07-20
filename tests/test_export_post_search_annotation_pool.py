"""Tests for the query-rewriting annotation-pool exporter."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import export_post_search_annotation_pool as exporter


def make_post(
    *,
    source_id: str = "5891",
    title: str = "进行欢迎有关这样",
    content: str = "这是帖子正文。",
) -> dict:
    return {
        "source_id": source_id,
        "title": title,
        "content": content,
        "category": "求助",
        "city": "晋中市",
        "district": "榆次区",
        "address": "西南街道",
        "latitude": 37.689434,
        "longitude": 112.761673,
    }


def test_normalize_text_collapses_whitespace() -> None:
    assert exporter.normalize_text(
        "  第一行\n  第二行\t第三行  ",
        max_chars=100,
    ) == "第一行 第二行 第三行"


def test_normalize_text_truncates() -> None:
    assert exporter.normalize_text(
        "abcdef",
        max_chars=5,
    ) == "abcd…"


def test_build_annotation_rows_uses_source_id() -> None:
    rows = exporter.build_annotation_rows(
        [
            make_post(
                source_id="5891",
            )
        ]
    )

    assert len(rows) == 1
    assert rows[0]["draft_id"] == "draft_001"
    assert rows[0]["anchor_source_id"] == "5891"
    assert rows[0]["query"] == ""
    assert rows[0]["anchor_proposed_grade"] == 3
    assert rows[0]["review_status"] == "draft"


def test_build_annotation_rows_removes_duplicates() -> None:
    rows = exporter.build_annotation_rows(
        [
            make_post(
                source_id="5891",
            ),
            make_post(
                source_id="5891",
                title="重复帖子",
            ),
        ]
    )

    assert len(rows) == 1


def test_build_annotation_rows_skips_empty_posts() -> None:
    rows = exporter.build_annotation_rows(
        [
            make_post(
                source_id="",
            ),
            make_post(
                source_id="2",
                title=" ",
            ),
            make_post(
                source_id="3",
                content=" ",
            ),
        ]
    )

    assert rows == []


def test_write_csv_uses_declared_columns(
    tmp_path: Path,
) -> None:
    rows = exporter.build_annotation_rows(
        [make_post()]
    )
    path = tmp_path / "pool.csv"

    exporter.write_csv(
        path,
        rows,
        overwrite=False,
    )

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        loaded = list(
            csv.DictReader(file)
        )

    assert len(loaded) == 1
    assert tuple(loaded[0].keys()) == (
        exporter.ANNOTATION_COLUMNS
    )
    assert loaded[0]["anchor_source_id"] == "5891"


def test_write_csv_refuses_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pool.csv"
    path.write_text(
        "existing",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match="--overwrite",
    ):
        exporter.write_csv(
            path,
            [],
            overwrite=False,
        )


def test_write_jsonl(
    tmp_path: Path,
) -> None:
    rows = exporter.build_annotation_rows(
        [make_post()]
    )
    path = tmp_path / "pool.jsonl"

    exporter.write_jsonl(
        path,
        rows,
        overwrite=False,
    )

    content = path.read_text(
        encoding="utf-8",
    )

    assert '"anchor_source_id": "5891"' in content
    assert content.endswith("\n")
