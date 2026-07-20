"""Tests for the MySQL-to-PostgreSQL synchronization runner."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.sync_mysql_posts as sync_module


def make_post(row: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        source_id=str(row["id"]),
        category=row.get("category", "求助"),
        visible_status=row.get("visible_status", "1"),
    )


def make_summary(row_count: int) -> dict[str, Any]:
    return {
        "row_count": row_count,
        "distinct_source_ids": row_count,
        "min_source_id": 1 if row_count else None,
        "max_source_id": row_count if row_count else None,
        "embedded_count": 0,
        "categories": {"求助": row_count},
        "visible_statuses": {"1": row_count},
    }


def test_synchronize_reads_all_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_rows = [
        {"id": 10},
        {"id": 20},
        {"id": 30},
        {"id": 40},
        {"id": 50},
    ]

    read_calls: list[tuple[int, int]] = []
    written_batches: list[list[str]] = []

    def fake_read(
        limit: int,
        after_id: int,
    ) -> list[dict[str, Any]]:
        read_calls.append((limit, after_id))
        return [
            row
            for row in source_rows
            if row["id"] > after_id
        ][:limit]

    async def fake_upsert(posts: list[Any]) -> int:
        written_batches.append(
            [post.source_id for post in posts]
        )
        return len(posts)

    async def fake_summary() -> dict[str, Any]:
        return make_summary(5)

    monkeypatch.setattr(
        sync_module,
        "read_mysql_posts",
        fake_read,
    )
    monkeypatch.setattr(
        sync_module,
        "map_mysql_post_row",
        make_post,
    )
    monkeypatch.setattr(
        sync_module.post_repository,
        "upsert_many",
        fake_upsert,
    )
    monkeypatch.setattr(
        sync_module,
        "read_postgres_summary",
        fake_summary,
    )

    result = asyncio.run(
        sync_module.synchronize(
            batch_size=2,
            after_id=0,
            max_rows=None,
        )
    )

    assert read_calls == [
        (2, 0),
        (2, 20),
        (2, 40),
    ]
    assert written_batches == [
        ["10", "20"],
        ["30", "40"],
        ["50"],
    ]
    assert result["batch_count"] == 3
    assert result["loaded_rows"] == 5
    assert result["upserted_rows"] == 5
    assert result["last_source_id"] == 50
    assert result["source_exhausted"] is True
    assert result["stopped_by_max_rows"] is False


def test_synchronize_respects_max_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_rows = [
        {"id": 1},
        {"id": 2},
        {"id": 3},
        {"id": 4},
    ]

    read_calls: list[tuple[int, int]] = []
    written_source_ids: list[str] = []

    def fake_read(
        limit: int,
        after_id: int,
    ) -> list[dict[str, Any]]:
        read_calls.append((limit, after_id))
        return [
            row
            for row in source_rows
            if row["id"] > after_id
        ][:limit]

    async def fake_upsert(posts: list[Any]) -> int:
        written_source_ids.extend(
            post.source_id for post in posts
        )
        return len(posts)

    async def fake_summary() -> dict[str, Any]:
        return make_summary(3)

    monkeypatch.setattr(
        sync_module,
        "read_mysql_posts",
        fake_read,
    )
    monkeypatch.setattr(
        sync_module,
        "map_mysql_post_row",
        make_post,
    )
    monkeypatch.setattr(
        sync_module.post_repository,
        "upsert_many",
        fake_upsert,
    )
    monkeypatch.setattr(
        sync_module,
        "read_postgres_summary",
        fake_summary,
    )

    result = asyncio.run(
        sync_module.synchronize(
            batch_size=2,
            after_id=0,
            max_rows=3,
        )
    )

    assert read_calls == [
        (2, 0),
        (1, 2),
    ]
    assert written_source_ids == ["1", "2", "3"]
    assert result["batch_count"] == 2
    assert result["loaded_rows"] == 3
    assert result["last_source_id"] == 3
    assert result["source_exhausted"] is False
    assert result["stopped_by_max_rows"] is True


@pytest.mark.parametrize(
    ("batch_size", "after_id", "max_rows"),
    [
        (0, 0, 1),
        (10001, 0, 1),
        (1000, -1, 1),
        (1000, 0, 0),
    ],
)
def test_validate_sync_parameters_rejects_invalid_values(
    batch_size: int,
    after_id: int,
    max_rows: int,
) -> None:
    with pytest.raises(ValueError):
        sync_module.validate_sync_parameters(
            batch_size=batch_size,
            after_id=after_id,
            max_rows=max_rows,
        )


def test_parse_args_keeps_legacy_limit_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "sync_mysql_posts.py",
            "--limit",
            "321",
            "--after-id",
            "12345",
        ],
    )

    args = sync_module.parse_args()

    assert args.batch_size == sync_module.DEFAULT_BATCH_SIZE
    assert args.max_rows == 321
    assert args.after_id == 12345


def test_parse_args_all_selects_unbounded_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "sync_mysql_posts.py",
            "--all",
            "--batch-size",
            "500",
            "--after-id",
            "100",
        ],
    )

    args = sync_module.parse_args()

    assert args.batch_size == 500
    assert args.max_rows is None
    assert args.after_id == 100
