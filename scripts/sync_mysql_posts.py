"""Synchronize posts from remote MySQL into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter
from typing import Any

from app.infrastructure.mysql_source import (
    connect_mysql_source,
    get_mysql_source_settings,
    quote_mysql_identifier,
)
from app.infrastructure.postgres import connect_postgres
from app.repositories.post_repository import post_repository
from app.services.mysql_post_mapper import (
    MYSQL_POST_SOURCE,
    map_mysql_post_row,
)


DEFAULT_BATCH_SIZE = 1000
DEFAULT_MAX_ROWS = 1000
MAX_BATCH_SIZE = 10000


MYSQL_POST_COLUMNS = """
    id,
    title,
    detail,
    typecategory,
    tags,
    createtime,
    updatetime,
    from_lat,
    from_lng,
    country,
    province,
    city,
    district,
    address,
    likes,
    views,
    marks,
    dislikes,
    ratescore,
    visiblestatus,
    owenerid
"""


def read_mysql_posts(
    limit: int,
    after_id: int,
) -> list[dict[str, Any]]:
    """Read one deterministic batch from the remote MySQL source."""
    get_mysql_source_settings.cache_clear()
    settings = get_mysql_source_settings()
    table = quote_mysql_identifier(settings.table)

    with connect_mysql_source() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    {MYSQL_POST_COLUMNS}
                FROM {table}
                WHERE id > %s
                ORDER BY id
                LIMIT %s
                """,
                (after_id, limit),
            )
            return list(cursor.fetchall())


async def read_postgres_summary() -> dict[str, Any]:
    """Return synchronization statistics from PostgreSQL."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    count(*) AS row_count,
                    count(DISTINCT source_id) AS distinct_source_ids,
                    min(source_id::bigint) AS min_source_id,
                    max(source_id::bigint) AS max_source_id,
                    count(*) FILTER (
                        WHERE embedding IS NOT NULL
                    ) AS embedded_count
                FROM posts
                WHERE source = %s
                """,
                (MYSQL_POST_SOURCE,),
            )
            summary = await cursor.fetchone()

            await cursor.execute(
                """
                SELECT category, count(*) AS row_count
                FROM posts
                WHERE source = %s
                GROUP BY category
                ORDER BY category
                """,
                (MYSQL_POST_SOURCE,),
            )
            category_rows = await cursor.fetchall()

            await cursor.execute(
                """
                SELECT visible_status, count(*) AS row_count
                FROM posts
                WHERE source = %s
                GROUP BY visible_status
                ORDER BY visible_status
                """,
                (MYSQL_POST_SOURCE,),
            )
            status_rows = await cursor.fetchall()

    if summary is None:
        raise RuntimeError(
            "PostgreSQL synchronization summary was empty."
        )

    return {
        **summary,
        "categories": {
            row["category"]: int(row["row_count"])
            for row in category_rows
        },
        "visible_statuses": {
            row["visible_status"]: int(row["row_count"])
            for row in status_rows
        },
    }


def validate_sync_parameters(
    *,
    batch_size: int,
    after_id: int,
    max_rows: int | None,
) -> None:
    """Validate synchronization controls."""
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size must be between 1 and {MAX_BATCH_SIZE}."
        )

    if after_id < 0:
        raise ValueError("after_id cannot be negative.")

    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be positive when provided.")


def parse_numeric_source_ids(posts: list[Any]) -> list[int]:
    """Validate that mapped source IDs form a strictly increasing batch."""
    try:
        source_ids = [int(post.source_id) for post in posts]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "MySQL source IDs must be integer-compatible."
        ) from exc

    if len(set(source_ids)) != len(source_ids):
        raise RuntimeError(
            "Duplicate source IDs were found in the MySQL batch."
        )

    if any(
        current_id <= previous_id
        for previous_id, current_id in zip(
            source_ids,
            source_ids[1:],
        )
    ):
        raise RuntimeError(
            "MySQL source IDs were not strictly increasing."
        )

    return source_ids


async def synchronize(
    *,
    batch_size: int,
    after_id: int,
    max_rows: int | None,
) -> dict[str, Any]:
    """Read and upsert one or more deterministic MySQL batches."""
    validate_sync_parameters(
        batch_size=batch_size,
        after_id=after_id,
        max_rows=max_rows,
    )

    started_at = time.monotonic()
    cursor_id = after_id

    batch_count = 0
    total_loaded = 0
    total_upserted = 0

    category_counts: Counter[str] = Counter()
    status_counts: Counter[str | None] = Counter()

    source_exhausted = False

    print("========== Synchronization configuration ==========")
    print("batch_size:", batch_size)
    print("after_id:", after_id)
    print(
        "max_rows:",
        "all available rows" if max_rows is None else max_rows,
    )

    while max_rows is None or total_loaded < max_rows:
        if max_rows is None:
            current_limit = batch_size
        else:
            current_limit = min(
                batch_size,
                max_rows - total_loaded,
            )

        raw_rows = read_mysql_posts(
            limit=current_limit,
            after_id=cursor_id,
        )

        if not raw_rows:
            source_exhausted = True
            break

        if len(raw_rows) > current_limit:
            raise RuntimeError(
                "MySQL returned more rows than the requested batch limit."
            )

        posts = [map_mysql_post_row(row) for row in raw_rows]
        source_ids = parse_numeric_source_ids(posts)

        first_source_id = source_ids[0]
        last_source_id = source_ids[-1]

        if first_source_id <= cursor_id:
            raise RuntimeError(
                "MySQL cursor did not advance beyond after_id."
            )

        affected = await post_repository.upsert_many(posts)

        if affected != len(posts):
            raise RuntimeError(
                "PostgreSQL upsert count did not match mapped post count."
            )

        batch_count += 1
        total_loaded += len(raw_rows)
        total_upserted += affected
        cursor_id = last_source_id

        category_counts.update(
            post.category for post in posts
        )
        status_counts.update(
            post.visible_status for post in posts
        )

        elapsed_seconds = time.monotonic() - started_at

        print(f"\n========== Batch {batch_count} ==========")
        print("requested rows:", current_limit)
        print("loaded rows:", len(raw_rows))
        print("first source_id:", first_source_id)
        print("last source_id:", last_source_id)
        print("upserted rows:", affected)
        print("total loaded:", total_loaded)
        print("total upserted:", total_upserted)
        print("elapsed seconds:", round(elapsed_seconds, 3))

        if len(raw_rows) < current_limit:
            source_exhausted = True
            break

    summary = await read_postgres_summary()

    if int(summary["row_count"]) != int(
        summary["distinct_source_ids"]
    ):
        raise RuntimeError(
            "PostgreSQL row count and distinct source ID count differ."
        )

    stopped_by_max_rows = (
        max_rows is not None
        and total_loaded >= max_rows
        and not source_exhausted
    )

    result = {
        "batch_count": batch_count,
        "loaded_rows": total_loaded,
        "upserted_rows": total_upserted,
        "initial_after_id": after_id,
        "last_source_id": cursor_id,
        "source_exhausted": source_exhausted,
        "stopped_by_max_rows": stopped_by_max_rows,
        "categories_in_run": dict(category_counts),
        "visible_statuses_in_run": dict(status_counts),
        "elapsed_seconds": round(
            time.monotonic() - started_at,
            3,
        ),
        "postgres_summary": summary,
    }

    print("\n========== Synchronization result ==========")
    for key, value in result.items():
        print(f"{key}: {value}")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize deterministic MySQL post batches "
            "into PostgreSQL."
        )
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "Rows read and committed per batch. "
            f"Default: {DEFAULT_BATCH_SIZE}."
        ),
    )

    parser.add_argument(
        "--after-id",
        type=int,
        default=0,
        help=(
            "Only synchronize MySQL rows with id greater "
            "than this value."
        ),
    )

    scope_group = parser.add_mutually_exclusive_group()

    scope_group.add_argument(
        "--all",
        action="store_true",
        help="Continue until no more MySQL rows are available.",
    )

    scope_group.add_argument(
        "--max-rows",
        "--limit",
        dest="max_rows",
        type=int,
        default=None,
        help=(
            "Maximum total rows synchronized in this run. "
            "--limit is retained for backward compatibility."
        ),
    )

    args = parser.parse_args()

    if args.all:
        args.max_rows = None
    elif args.max_rows is None:
        args.max_rows = DEFAULT_MAX_ROWS

    try:
        validate_sync_parameters(
            batch_size=args.batch_size,
            after_id=args.after_id,
            max_rows=args.max_rows,
        )
    except ValueError as exc:
        parser.error(str(exc))

    return args


def main() -> None:
    args = parse_args()

    asyncio.run(
        synchronize(
            batch_size=args.batch_size,
            after_id=args.after_id,
            max_rows=args.max_rows,
        )
    )


if __name__ == "__main__":
    main()
