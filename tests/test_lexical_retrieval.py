"""Tests for PostgreSQL trigram lexical recall."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.algorithms.search.lexical import (
    extract_lexical_query_terms,
)

from app.infrastructure.search.lexical_retrieval import (
    lexical_search_filtered,
)

class FakeCursor:
    def __init__(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.rows = rows
        self.query: str | None = None
        self.parameters: (
            dict[str, Any] | None
        ) = None

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any],
    ) -> None:
        self.query = query
        self.parameters = parameters

    async def fetchall(
        self,
    ) -> list[dict[str, Any]]:
        return list(self.rows)


class FakeConnection:
    def __init__(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.cursor_instance = FakeCursor(
            rows
        )

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def run(coroutine):
    return asyncio.run(coroutine)


def make_row(
    *,
    source_id: str,
    latitude: float | None = 37.0,
    longitude: float | None = 112.0,
    lexical_score: float = 0.8,
) -> dict[str, Any]:
    return {
        "source": "mysql_tiezi_geo_new",
        "source_id": source_id,
        "latitude": latitude,
        "longitude": longitude,
        "lexical_score": lexical_score,
        "title_score": 1.0,
        "content_score": 0.8,
        "tag_score": 0.5,
    }


def test_extracts_chinese_text_and_tag_terms() -> None:
    terms = extract_lexical_query_terms(
        "手机里的文件安全问题应该怎么处理？"
    )

    # NFKC normalizes the full-width Chinese question
    # mark into the ASCII question mark.
    assert terms.normalized_query == (
        "手机里的文件安全问题应该怎么处理?"
    )
    assert "手机" in terms.tag_terms
    assert "文件" in terms.tag_terms
    assert "安全" in terms.tag_terms
    assert "文件安全" in terms.text_terms
    assert "文件安" in terms.text_terms
    assert "件安全" in terms.text_terms
    assert "机文" not in terms.tag_terms
    assert "件安" not in terms.tag_terms
    assert "怎么" not in terms.tag_terms
    assert "处理" not in terms.tag_terms


def test_extracts_ascii_tokens() -> None:
    terms = extract_lexical_query_terms(
        "Python API 开发工具"
    )

    assert "python" in terms.text_terms
    assert "api" in terms.text_terms
    assert "python" in terms.tag_terms


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
    ],
)
def test_blank_query_is_rejected(
    query: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="must not be blank",
    ):
        extract_lexical_query_terms(query)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "limit": 0,
        },
        {
            "limit": 2001,
        },
        {
            "limit": 10,
            "category": "其他",
        },
        {
            "limit": 10,
            "latitude": 30.0,
        },
        {
            "limit": 10,
            "radius_km": 10.0,
        },
        {
            "limit": 10,
            "overfetch_factor": 0.5,
        },
    ],
)
def test_invalid_search_parameters_are_rejected(
    kwargs: dict[str, Any],
) -> None:
    connection = FakeConnection([])

    with pytest.raises(ValueError):
        run(
            lexical_search_filtered(
                connection,
                query="文件安全",
                **kwargs,
            )
        )


def test_query_contains_trigram_and_tag_filters() -> None:
    connection = FakeConnection(
        [
            make_row(
                source_id="1",
            )
        ]
    )

    candidates = run(
        lexical_search_filtered(
            connection,
            query="程序开发需要哪些工具",
            category="求助",
            visible_statuses=[
                "1",
                "1",
            ],
            city="晋中市",
            district="榆次区",
            min_latitude=37.0,
            max_latitude=38.0,
            min_longitude=112.0,
            max_longitude=113.0,
            overfetch_factor=3.0,
            limit=2,
        )
    )

    cursor = connection.cursor_instance

    assert len(candidates) == 1
    assert cursor.query is not None
    assert cursor.parameters is not None

    assert "title_recall AS" in cursor.query
    assert "content_recall AS" in cursor.query
    assert "tag_recall AS" in cursor.query
    assert "candidate_ids AS" in cursor.query
    assert "similarity(" not in cursor.query
    assert "ILIKE" in cursor.query
    assert "p.tags &&" in cursor.query
    assert "p.category =" in cursor.query
    assert "p.visible_status =" in cursor.query
    assert "p.city =" in cursor.query
    assert "p.district =" in cursor.query
    assert "p.latitude BETWEEN" in cursor.query
    assert "p.longitude BETWEEN" in cursor.query

    assert (
        cursor.parameters["scan_limit"]
        == 6
    )
    assert (
        cursor.parameters["final_scan_limit"]
        == 18
    )
    assert (
        cursor.parameters["visible_statuses"]
        == ["1"]
    )
    assert "程序" in cursor.parameters[
        "tag_terms"
    ]


def test_exact_radius_filters_rows_and_respects_limit() -> None:
    connection = FakeConnection(
        [
            make_row(
                source_id="inside-1",
                latitude=37.0,
                longitude=112.0,
                lexical_score=0.9,
            ),
            make_row(
                source_id="outside",
                latitude=39.0,
                longitude=116.0,
                lexical_score=0.8,
            ),
            make_row(
                source_id="inside-2",
                latitude=37.01,
                longitude=112.01,
                lexical_score=0.7,
            ),
            make_row(
                source_id="inside-3",
                latitude=37.02,
                longitude=112.02,
                lexical_score=0.6,
            ),
        ]
    )

    candidates = run(
        lexical_search_filtered(
            connection,
            query="电脑维修服务",
            latitude=37.0,
            longitude=112.0,
            radius_km=10.0,
            limit=2,
        )
    )

    assert [
        candidate["source_id"]
        for candidate in candidates
    ] == [
        "inside-1",
        "inside-2",
    ]

    assert candidates[0][
        "distance_km"
    ] == pytest.approx(0.0)

    assert all(
        candidate["distance_km"] is not None
        and candidate["distance_km"] <= 10.0
        for candidate in candidates
    )
