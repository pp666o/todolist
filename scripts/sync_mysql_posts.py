"""Synchronize posts from remote MySQL into PostgreSQL."""

import argparse
import asyncio
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


def read_mysql_posts(limit: int, after_id: int) -> list[dict[str, Any]]:
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
        raise RuntimeError("PostgreSQL synchronization summary was empty.")

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


async def synchronize(limit: int, after_id: int) -> None:
    """Read, validate, and upsert one MySQL batch."""
    raw_rows = read_mysql_posts(limit=limit, after_id=after_id)

    if not raw_rows:
        print("No MySQL rows matched the requested range.")
        return

    posts = [map_mysql_post_row(row) for row in raw_rows]

    unique_source_ids = {post.source_id for post in posts}
    if len(unique_source_ids) != len(posts):
        raise RuntimeError("Duplicate source IDs were found in the MySQL batch.")

    category_counts = Counter(post.category for post in posts)
    status_counts = Counter(post.visible_status for post in posts)

    print("========== MySQL batch ==========")
    print("requested limit:", limit)
    print("after_id:", after_id)
    print("loaded rows:", len(raw_rows))
    print("mapped posts:", len(posts))
    print("first source_id:", posts[0].source_id)
    print("last source_id:", posts[-1].source_id)
    print("categories:", dict(category_counts))
    print("visible statuses:", dict(status_counts))

    affected = await post_repository.upsert_many(posts)

    print("\n========== PostgreSQL write ==========")
    print("upserted rows:", affected)

    summary = await read_postgres_summary()

    print("\n========== PostgreSQL summary ==========")
    for key, value in summary.items():
        print(f"{key}: {value}")

    if int(summary["row_count"]) != int(summary["distinct_source_ids"]):
        raise RuntimeError(
            "PostgreSQL row count and distinct source ID count differ."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize one MySQL post batch into PostgreSQL."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum rows to synchronize.",
    )
    parser.add_argument(
        "--after-id",
        type=int,
        default=0,
        help="Only synchronize MySQL rows with id greater than this value.",
    )

    args = parser.parse_args()

    if not 1 <= args.limit <= 10000:
        parser.error("--limit must be between 1 and 10000.")

    if args.after_id < 0:
        parser.error("--after-id cannot be negative.")

    return args


def main() -> None:
    args = parse_args()
    asyncio.run(
        synchronize(
            limit=args.limit,
            after_id=args.after_id,
        )
    )


if __name__ == "__main__":
    main()
