"""Audit MySQL source posts against PostgreSQL synchronized posts."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from app.infrastructure.mysql_source import (
    connect_mysql_source,
    get_mysql_source_settings,
    quote_mysql_identifier,
)
from app.infrastructure.postgres import connect_postgres
from app.services.mysql_post_mapper import MYSQL_POST_SOURCE


SUPPORTED_CATEGORIES = {"求助", "问答", "吐槽"}

QUALITY_COUNTERS = (
    "empty_title_count",
    "empty_content_count",
    "empty_category_count",
    "missing_coordinates_count",
    "partial_coordinates_count",
    "invalid_latitude_count",
    "invalid_longitude_count",
    "zero_coordinate_count",
    "empty_city_count",
    "empty_district_count",
    "negative_likes_count",
    "negative_views_count",
    "negative_marks_count",
    "negative_dislikes_count",
)


def _as_int(value: Any) -> int:
    """Convert SQL count values into plain integers."""
    if value is None:
        return 0

    return int(value)


def _normalize_distribution(
    rows: list[dict[str, Any]],
    *,
    key_name: str,
) -> dict[str, int]:
    """Convert grouped SQL rows into a stable dictionary."""
    return {
        "<NULL>" if row[key_name] is None else str(row[key_name]): _as_int(
            row["row_count"]
        )
        for row in rows
    }


def read_mysql_snapshot(
    *,
    sample_size: int,
) -> dict[str, Any]:
    """Read source counts, distributions, IDs, and quality diagnostics."""
    get_mysql_source_settings.cache_clear()
    settings = get_mysql_source_settings()
    table = quote_mysql_identifier(settings.table)

    with connect_mysql_source() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT id) AS distinct_source_ids,
                    MIN(id) AS min_source_id,
                    MAX(id) AS max_source_id,
                    MIN(createtime) AS min_created_at,
                    MAX(createtime) AS max_created_at,
                    MIN(updatetime) AS min_updated_at,
                    MAX(updatetime) AS max_updated_at
                FROM {table}
                """
            )
            overall = cursor.fetchone()

            if overall is None:
                raise RuntimeError(
                    "MySQL overall audit query returned no result."
                )

            cursor.execute(
                f"""
                SELECT
                    SUM(
                        title IS NULL
                        OR CHAR_LENGTH(TRIM(CAST(title AS CHAR))) = 0
                    ) AS empty_title_count,

                    SUM(
                        detail IS NULL
                        OR CHAR_LENGTH(TRIM(CAST(detail AS CHAR))) = 0
                    ) AS empty_content_count,

                    SUM(
                        typecategory IS NULL
                        OR CHAR_LENGTH(
                            TRIM(CAST(typecategory AS CHAR))
                        ) = 0
                    ) AS empty_category_count,

                    SUM(
                        from_lat IS NULL
                        AND from_lng IS NULL
                    ) AS missing_coordinates_count,

                    SUM(
                        (
                            from_lat IS NULL
                            AND from_lng IS NOT NULL
                        )
                        OR
                        (
                            from_lat IS NOT NULL
                            AND from_lng IS NULL
                        )
                    ) AS partial_coordinates_count,

                    SUM(
                        from_lat IS NOT NULL
                        AND (
                            from_lat < -90
                            OR from_lat > 90
                        )
                    ) AS invalid_latitude_count,

                    SUM(
                        from_lng IS NOT NULL
                        AND (
                            from_lng < -180
                            OR from_lng > 180
                        )
                    ) AS invalid_longitude_count,

                    SUM(
                        from_lat = 0
                        AND from_lng = 0
                    ) AS zero_coordinate_count,

                    SUM(
                        city IS NULL
                        OR CHAR_LENGTH(TRIM(CAST(city AS CHAR))) = 0
                    ) AS empty_city_count,

                    SUM(
                        district IS NULL
                        OR CHAR_LENGTH(
                            TRIM(CAST(district AS CHAR))
                        ) = 0
                    ) AS empty_district_count,

                    SUM(likes < 0) AS negative_likes_count,
                    SUM(views < 0) AS negative_views_count,
                    SUM(marks < 0) AS negative_marks_count,
                    SUM(dislikes < 0) AS negative_dislikes_count
                FROM {table}
                """
            )
            quality = cursor.fetchone()

            if quality is None:
                raise RuntimeError(
                    "MySQL quality audit query returned no result."
                )

            cursor.execute(
                f"""
                SELECT
                    typecategory,
                    COUNT(*) AS row_count
                FROM {table}
                GROUP BY typecategory
                ORDER BY typecategory
                """
            )
            categories = _normalize_distribution(
                list(cursor.fetchall()),
                key_name="typecategory",
            )

            cursor.execute(
                f"""
                SELECT
                    visiblestatus,
                    COUNT(*) AS row_count
                FROM {table}
                GROUP BY visiblestatus
                ORDER BY visiblestatus
                """
            )
            visible_statuses = _normalize_distribution(
                list(cursor.fetchall()),
                key_name="visiblestatus",
            )

            cursor.execute(
                f"""
                SELECT id
                FROM {table}
                ORDER BY id
                """
            )
            source_ids = {
                str(row["id"])
                for row in cursor.fetchall()
            }

            cursor.execute(
                f"""
                SELECT
                    id,
                    title,
                    typecategory,
                    from_lat,
                    from_lng,
                    city,
                    district
                FROM {table}
                WHERE
                    title IS NULL
                    OR CHAR_LENGTH(TRIM(CAST(title AS CHAR))) = 0
                    OR detail IS NULL
                    OR CHAR_LENGTH(TRIM(CAST(detail AS CHAR))) = 0
                    OR typecategory IS NULL
                    OR CHAR_LENGTH(
                        TRIM(CAST(typecategory AS CHAR))
                    ) = 0
                    OR from_lat IS NULL
                    OR from_lng IS NULL
                    OR from_lat < -90
                    OR from_lat > 90
                    OR from_lng < -180
                    OR from_lng > 180
                    OR (
                        from_lat = 0
                        AND from_lng = 0
                    )
                    OR city IS NULL
                    OR CHAR_LENGTH(TRIM(CAST(city AS CHAR))) = 0
                    OR district IS NULL
                    OR CHAR_LENGTH(
                        TRIM(CAST(district AS CHAR))
                    ) = 0
                    OR likes < 0
                    OR views < 0
                    OR marks < 0
                    OR dislikes < 0
                ORDER BY id
                LIMIT %s
                """,
                (sample_size,),
            )
            issue_samples = list(cursor.fetchall())

    return {
        "database": settings.database,
        "table": settings.table,
        "row_count": _as_int(overall["row_count"]),
        "distinct_source_ids": _as_int(
            overall["distinct_source_ids"]
        ),
        "min_source_id": overall["min_source_id"],
        "max_source_id": overall["max_source_id"],
        "min_created_at": overall["min_created_at"],
        "max_created_at": overall["max_created_at"],
        "min_updated_at": overall["min_updated_at"],
        "max_updated_at": overall["max_updated_at"],
        "quality": {
            key: _as_int(quality[key])
            for key in QUALITY_COUNTERS
        },
        "categories": categories,
        "visible_statuses": visible_statuses,
        "source_ids": source_ids,
        "issue_samples": issue_samples,
    }


async def read_postgres_snapshot(
    *,
    sample_size: int,
) -> dict[str, Any]:
    """Read synchronized PostgreSQL diagnostics."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT source_id)
                        AS distinct_source_ids,
                    COUNT(*) FILTER (
                        WHERE embedding IS NOT NULL
                    ) AS embedded_count,
                    COUNT(*) FILTER (
                        WHERE source_id !~ '^[0-9]+$'
                    ) AS non_numeric_source_id_count
                FROM posts
                WHERE source = %s
                """,
                (MYSQL_POST_SOURCE,),
            )
            overall = await cursor.fetchone()

            if overall is None:
                raise RuntimeError(
                    "PostgreSQL overall audit query returned no result."
                )

            await cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE title IS NULL
                           OR btrim(title) = ''
                    ) AS empty_title_count,

                    COUNT(*) FILTER (
                        WHERE content IS NULL
                           OR btrim(content) = ''
                    ) AS empty_content_count,

                    COUNT(*) FILTER (
                        WHERE category IS NULL
                           OR btrim(category) = ''
                    ) AS empty_category_count,

                    COUNT(*) FILTER (
                        WHERE latitude IS NULL
                          AND longitude IS NULL
                    ) AS missing_coordinates_count,

                    COUNT(*) FILTER (
                        WHERE (
                            latitude IS NULL
                            AND longitude IS NOT NULL
                        )
                        OR (
                            latitude IS NOT NULL
                            AND longitude IS NULL
                        )
                    ) AS partial_coordinates_count,

                    COUNT(*) FILTER (
                        WHERE latitude IS NOT NULL
                          AND (
                              latitude < -90
                              OR latitude > 90
                          )
                    ) AS invalid_latitude_count,

                    COUNT(*) FILTER (
                        WHERE longitude IS NOT NULL
                          AND (
                              longitude < -180
                              OR longitude > 180
                          )
                    ) AS invalid_longitude_count,

                    COUNT(*) FILTER (
                        WHERE latitude = 0
                          AND longitude = 0
                    ) AS zero_coordinate_count,

                    COUNT(*) FILTER (
                        WHERE city IS NULL
                           OR btrim(city) = ''
                    ) AS empty_city_count,

                    COUNT(*) FILTER (
                        WHERE district IS NULL
                           OR btrim(district) = ''
                    ) AS empty_district_count,

                    COUNT(*) FILTER (
                        WHERE likes < 0
                    ) AS negative_likes_count,

                    COUNT(*) FILTER (
                        WHERE views < 0
                    ) AS negative_views_count,

                    COUNT(*) FILTER (
                        WHERE marks < 0
                    ) AS negative_marks_count,

                    COUNT(*) FILTER (
                        WHERE dislikes < 0
                    ) AS negative_dislikes_count
                FROM posts
                WHERE source = %s
                """,
                (MYSQL_POST_SOURCE,),
            )
            quality = await cursor.fetchone()

            if quality is None:
                raise RuntimeError(
                    "PostgreSQL quality audit query returned no result."
                )

            await cursor.execute(
                """
                SELECT
                    category,
                    COUNT(*) AS row_count
                FROM posts
                WHERE source = %s
                GROUP BY category
                ORDER BY category
                """,
                (MYSQL_POST_SOURCE,),
            )
            categories = _normalize_distribution(
                list(await cursor.fetchall()),
                key_name="category",
            )

            await cursor.execute(
                """
                SELECT
                    visible_status,
                    COUNT(*) AS row_count
                FROM posts
                WHERE source = %s
                GROUP BY visible_status
                ORDER BY visible_status
                """,
                (MYSQL_POST_SOURCE,),
            )
            visible_statuses = _normalize_distribution(
                list(await cursor.fetchall()),
                key_name="visible_status",
            )

            await cursor.execute(
                """
                SELECT source_id
                FROM posts
                WHERE source = %s
                ORDER BY source_id
                """,
                (MYSQL_POST_SOURCE,),
            )
            source_ids = {
                str(row["source_id"])
                for row in await cursor.fetchall()
            }

            await cursor.execute(
                """
                SELECT
                    source_id,
                    title,
                    category,
                    latitude,
                    longitude,
                    city,
                    district
                FROM posts
                WHERE source = %s
                  AND (
                      title IS NULL
                      OR btrim(title) = ''
                      OR content IS NULL
                      OR btrim(content) = ''
                      OR category IS NULL
                      OR btrim(category) = ''
                      OR latitude IS NULL
                      OR longitude IS NULL
                      OR latitude < -90
                      OR latitude > 90
                      OR longitude < -180
                      OR longitude > 180
                      OR (
                          latitude = 0
                          AND longitude = 0
                      )
                      OR city IS NULL
                      OR btrim(city) = ''
                      OR district IS NULL
                      OR btrim(district) = ''
                      OR likes < 0
                      OR views < 0
                      OR marks < 0
                      OR dislikes < 0
                  )
                ORDER BY source_id
                LIMIT %s
                """,
                (MYSQL_POST_SOURCE, sample_size),
            )
            issue_samples = list(await cursor.fetchall())

    return {
        "source": MYSQL_POST_SOURCE,
        "row_count": _as_int(overall["row_count"]),
        "distinct_source_ids": _as_int(
            overall["distinct_source_ids"]
        ),
        "embedded_count": _as_int(overall["embedded_count"]),
        "non_numeric_source_id_count": _as_int(
            overall["non_numeric_source_id_count"]
        ),
        "quality": {
            key: _as_int(quality[key])
            for key in QUALITY_COUNTERS
        },
        "categories": categories,
        "visible_statuses": visible_statuses,
        "source_ids": source_ids,
        "issue_samples": issue_samples,
    }


def evaluate_audit(
    mysql_snapshot: dict[str, Any],
    postgres_snapshot: dict[str, Any],
    *,
    sample_size: int,
) -> tuple[list[str], list[str]]:
    """Return fatal errors and non-fatal warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    mysql_count = int(mysql_snapshot["row_count"])
    postgres_count = int(postgres_snapshot["row_count"])

    if mysql_count == 0:
        errors.append("MySQL source table is empty.")

    if mysql_count != int(mysql_snapshot["distinct_source_ids"]):
        errors.append(
            "MySQL row count differs from distinct source ID count."
        )

    if postgres_count != int(
        postgres_snapshot["distinct_source_ids"]
    ):
        errors.append(
            "PostgreSQL row count differs from distinct source ID count."
        )

    if mysql_count != postgres_count:
        errors.append(
            "MySQL/PostgreSQL row counts differ: "
            f"mysql={mysql_count}, postgres={postgres_count}."
        )

    if int(postgres_snapshot["non_numeric_source_id_count"]) != 0:
        errors.append(
            "PostgreSQL contains non-numeric MySQL source IDs."
        )

    mysql_categories = mysql_snapshot["categories"]
    postgres_categories = postgres_snapshot["categories"]

    if set(mysql_categories) != SUPPORTED_CATEGORIES:
        errors.append(
            "MySQL category set is unexpected: "
            f"{sorted(mysql_categories)}."
        )

    if mysql_categories != postgres_categories:
        errors.append(
            "MySQL/PostgreSQL category distributions differ: "
            f"mysql={mysql_categories}, "
            f"postgres={postgres_categories}."
        )

    if (
        mysql_snapshot["visible_statuses"]
        != postgres_snapshot["visible_statuses"]
    ):
        errors.append(
            "MySQL/PostgreSQL visible-status distributions differ: "
            f"mysql={mysql_snapshot['visible_statuses']}, "
            f"postgres={postgres_snapshot['visible_statuses']}."
        )

    for side_name, snapshot in (
        ("MySQL", mysql_snapshot),
        ("PostgreSQL", postgres_snapshot),
    ):
        for counter_name in QUALITY_COUNTERS:
            count = int(snapshot["quality"][counter_name])

            if count:
                errors.append(
                    f"{side_name} {counter_name}={count}."
                )

    mysql_ids = set(mysql_snapshot["source_ids"])
    postgres_ids = set(postgres_snapshot["source_ids"])

    missing_ids = sorted(
        mysql_ids - postgres_ids,
        key=lambda value: int(value),
    )
    extra_ids = sorted(
        postgres_ids - mysql_ids,
        key=lambda value: int(value),
    )

    if missing_ids:
        errors.append(
            "PostgreSQL is missing MySQL source IDs: "
            f"count={len(missing_ids)}, "
            f"sample={missing_ids[:sample_size]}."
        )

    if extra_ids:
        errors.append(
            "PostgreSQL contains extra MySQL-derived source IDs: "
            f"count={len(extra_ids)}, "
            f"sample={extra_ids[:sample_size]}."
        )

    if int(postgres_snapshot["embedded_count"]) == 0:
        warnings.append(
            "No synchronized posts currently have embeddings."
        )

    return errors, warnings


def print_snapshot_summary(
    mysql_snapshot: dict[str, Any],
    postgres_snapshot: dict[str, Any],
) -> None:
    """Print concise human-readable audit summaries."""
    print("========== MySQL source ==========")
    print("database:", mysql_snapshot["database"])
    print("table:", mysql_snapshot["table"])
    print("row_count:", mysql_snapshot["row_count"])
    print(
        "distinct_source_ids:",
        mysql_snapshot["distinct_source_ids"],
    )
    print("min_source_id:", mysql_snapshot["min_source_id"])
    print("max_source_id:", mysql_snapshot["max_source_id"])
    print("categories:", mysql_snapshot["categories"])
    print(
        "visible_statuses:",
        mysql_snapshot["visible_statuses"],
    )
    print("quality:", mysql_snapshot["quality"])

    print("\n========== PostgreSQL target ==========")
    print("source:", postgres_snapshot["source"])
    print("row_count:", postgres_snapshot["row_count"])
    print(
        "distinct_source_ids:",
        postgres_snapshot["distinct_source_ids"],
    )
    print("embedded_count:", postgres_snapshot["embedded_count"])
    print(
        "non_numeric_source_id_count:",
        postgres_snapshot["non_numeric_source_id_count"],
    )
    print("categories:", postgres_snapshot["categories"])
    print(
        "visible_statuses:",
        postgres_snapshot["visible_statuses"],
    )
    print("quality:", postgres_snapshot["quality"])


async def run_audit(
    *,
    sample_size: int,
) -> int:
    """Run the complete read-only audit and return a process exit code."""
    mysql_snapshot = read_mysql_snapshot(
        sample_size=sample_size,
    )
    postgres_snapshot = await read_postgres_snapshot(
        sample_size=sample_size,
    )

    print_snapshot_summary(
        mysql_snapshot,
        postgres_snapshot,
    )

    errors, warnings = evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=sample_size,
    )

    if mysql_snapshot["issue_samples"]:
        print("\n========== MySQL issue samples ==========")
        for row in mysql_snapshot["issue_samples"]:
            print(row)

    if postgres_snapshot["issue_samples"]:
        print("\n========== PostgreSQL issue samples ==========")
        for row in postgres_snapshot["issue_samples"]:
            print(row)

    if warnings:
        print("\n========== Warnings ==========")
        for warning in warnings:
            print(f"[WARN] {warning}")

    if errors:
        print("\n========== Audit failures ==========")
        for error in errors:
            print(f"[ERROR] {error}")

        print("\n[ERROR] post data audit failed")
        return 1

    print("\n[OK] post data audit passed")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit remote MySQL posts against synchronized "
            "PostgreSQL posts."
        )
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Maximum IDs or invalid rows shown per issue.",
    )

    args = parser.parse_args()

    if not 1 <= args.sample_size <= 1000:
        parser.error("--sample-size must be between 1 and 1000.")

    return args


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(
        run_audit(
            sample_size=args.sample_size,
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
