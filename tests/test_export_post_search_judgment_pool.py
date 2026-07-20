"""Tests for the manual relevance judgment-pool exporter."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import pytest

from app.schemas.post_search import (
    PostSearchHit,
    PostSearchResponse,
)
from scripts import export_post_search_judgment_pool as exporter


def make_draft(
    *,
    anchor_source_id: str = "anchor-1",
) -> dict[str, str]:
    return {
        "draft_id": "draft_001",
        "query": "手机文件安全怎么处理",
        "query_type": "content_intent",
        "anchor_source_id": anchor_source_id,
        "category": "问答",
        "city": "银川市",
        "district": "西夏区",
        "latitude": "38.49482",
        "longitude": "106.119637",
        "review_status": "query_drafted",
    }


def make_hit(
    source_id: str,
) -> PostSearchHit:
    return PostSearchHit(
        post_id=1,
        source="mysql_tiezi_geo_new",
        source_id=source_id,
        title=f"title-{source_id}",
        content="content",
        category="问答",
        city="银川市",
        district="西夏区",
        score=0.8,
        text_score=0.7,
        geo_score=0.0,
        hot_score=0.2,
        unlock_score=0.0,
        recall_sources=["keyword_content"],
    )


def make_response(
    source_ids: list[str],
) -> PostSearchResponse:
    return PostSearchResponse(
        request_id="request-1",
        query="手机文件安全怎么处理",
        total_candidates=len(source_ids),
        result_count=len(source_ids),
        items=[
            make_hit(source_id)
            for source_id in source_ids
        ],
        degraded=False,
    )


def make_anchor(
    source_id: str = "anchor-1",
) -> dict:
    return {
        "source_id": source_id,
        "title": "来源帖子",
        "content": "手机安全文件相关正文",
        "category": "问答",
        "city": "银川市",
        "district": "西夏区",
    }


def test_optional_float() -> None:
    assert exporter.optional_float("") is None
    assert exporter.optional_float("1.25") == 1.25


def test_load_drafts_only_reads_query_drafted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pool.csv"

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=make_draft().keys(),
        )
        writer.writeheader()
        writer.writerow(make_draft())
        writer.writerow(
            {
                **make_draft(
                    anchor_source_id="anchor-2",
                ),
                "draft_id": "draft_002",
                "review_status": "draft",
            }
        )

    rows = exporter.load_drafts(path)

    assert len(rows) == 1
    assert rows[0]["anchor_source_id"] == "anchor-1"


def test_search_draft_keeps_search_anchor() -> None:
    async def fake_search(_):
        return make_response(
            ["other", "anchor-1"]
        )

    async def fail_fetch(_):
        raise AssertionError(
            "anchor fetch should not be called"
        )

    rows = asyncio.run(
        exporter.search_draft(
            make_draft(),
            candidate_k=20,
            recall_k=1000,
            search=fake_search,
            fetch_anchor=fail_fetch,
        )
    )

    assert len(rows) == 2
    assert rows[1]["candidate_source_id"] == "anchor-1"
    assert rows[1]["candidate_rank"] == 2
    assert rows[1]["candidate_origin"] == "search_result"
    assert rows[1]["is_anchor"] == "yes"


def test_search_draft_injects_missing_anchor() -> None:
    async def fake_search(_):
        return make_response(
            ["other-1", "other-2"]
        )

    async def fake_fetch(source_id: str):
        assert source_id == "anchor-1"
        return make_anchor(source_id)

    rows = asyncio.run(
        exporter.search_draft(
            make_draft(),
            candidate_k=20,
            recall_k=1000,
            search=fake_search,
            fetch_anchor=fake_fetch,
        )
    )

    assert len(rows) == 3

    injected = rows[-1]

    assert injected["candidate_source_id"] == "anchor-1"
    assert injected["candidate_rank"] == ""
    assert injected["candidate_origin"] == "injected_anchor"
    assert injected["is_anchor"] == "yes"
    assert injected["score"] == ""
    assert injected["recall_sources"] == "[]"


def test_search_draft_rejects_missing_database_anchor() -> None:
    async def fake_search(_):
        return make_response(["other"])

    async def missing_anchor(_):
        return None

    with pytest.raises(
        RuntimeError,
        match="does not exist",
    ):
        asyncio.run(
            exporter.search_draft(
                make_draft(),
                candidate_k=20,
                recall_k=1000,
                search=fake_search,
                fetch_anchor=missing_anchor,
            )
        )


def test_write_pool_includes_candidate_origin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "judgments.csv"

    row = {
        column: ""
        for column in exporter.OUTPUT_COLUMNS
    }
    row["candidate_source_id"] = "anchor-1"
    row["candidate_origin"] = "injected_anchor"

    exporter.write_pool(
        path,
        [row],
        overwrite=False,
    )

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        loaded = list(csv.DictReader(file))

    assert len(loaded) == 1
    assert loaded[0]["candidate_origin"] == "injected_anchor"
