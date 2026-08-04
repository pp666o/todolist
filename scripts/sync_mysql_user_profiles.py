"""Synchronize user and creator profiles from MySQL into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from statistics import fmean
from typing import Any

from psycopg.types.json import Jsonb

from app.infrastructure.mysql_source import (
    connect_mysql_source,
    get_mysql_source_settings,
    quote_mysql_identifier,
)
from app.infrastructure.postgres import connect_postgres


MYSQL_USER_PROFILE_SOURCE = "mysql_users_geo"
MYSQL_USER_TABLE = "users_geo"

DEFAULT_BATCH_SIZE = 1000
MAX_BATCH_SIZE = 5000

_ALLOWED_CATEGORIES = {
    "求助",
    "问答",
    "吐槽",
}

_MULTI_VALUE_SEPARATOR = re.compile(
    r"[,，;；|、/]+"
)


def normalize_text(value: Any) -> str | None:
    """Normalize an optional scalar text field."""
    if value is None:
        return None

    normalized = str(value).strip()

    return normalized or None


def age_to_bucket(value: Any) -> str:
    """Map an age value to a non-identifying age bucket."""
    try:
        age = int(value)
    except (TypeError, ValueError):
        return "unknown"

    if age < 18 or age > 120:
        return "unknown"
    if age <= 24:
        return "18-24"
    if age <= 34:
        return "25-34"
    if age <= 44:
        return "35-44"
    if age <= 54:
        return "45-54"
    if age <= 64:
        return "55-64"

    return "65+"


def parse_multi_value(value: Any) -> list[str]:
    """Parse JSON arrays or delimiter-separated text into unique values."""
    if value is None:
        return []

    raw_values: list[Any]

    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        text = str(value).strip()

        if not text:
            return []

        if text.startswith("[") and text.endswith("]"):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None

            if isinstance(decoded, list):
                raw_values = decoded
            else:
                raw_values = _MULTI_VALUE_SEPARATOR.split(text)
        else:
            raw_values = _MULTI_VALUE_SEPARATOR.split(text)

    result: list[str] = []
    seen: set[str] = set()

    for raw_value in raw_values:
        normalized = normalize_text(raw_value)

        if normalized is None:
            continue

        if len(normalized) > 128:
            normalized = normalized[:128]

        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return result


def safe_non_negative_float(value: Any) -> float:
    """Return a finite non-negative numeric value."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0

    if result < 0:
        return 0.0

    return result


def mean_non_negative(
    rows: list[dict[str, Any]],
    field: str,
) -> float:
    """Return the average non-negative value for one post field."""
    if not rows:
        return 0.0

    return float(
        fmean(
            safe_non_negative_float(row.get(field))
            for row in rows
        )
    )


def mean_optional_score(
    rows: list[dict[str, Any]],
) -> float | None:
    """Return the average available rate score."""
    values: list[float] = []

    for row in rows:
        raw_value = row.get("ratescore")

        if raw_value is None:
            continue

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        if value >= 0:
            values.append(value)

    if not values:
        return None

    return float(fmean(values))


def calculate_category_weights(
    posts: list[dict[str, Any]],
) -> dict[str, float]:
    """Calculate category proportions across authored posts."""
    category_counts = Counter(
        category
        for post in posts
        if (
            (category := normalize_text(
                post.get("typecategory")
            ))
            in _ALLOWED_CATEGORIES
        )
    )

    total = sum(category_counts.values())

    if total == 0:
        return {}

    return {
        category: round(count / total, 6)
        for category, count in sorted(
            category_counts.items()
        )
    }


def calculate_tag_weights(
    posts: list[dict[str, Any]],
) -> dict[str, float]:
    """Calculate the fraction of authored posts containing each tag."""
    if not posts:
        return {}

    tag_post_counts: Counter[str] = Counter()

    for post in posts:
        for tag in parse_multi_value(post.get("tags")):
            tag_post_counts[tag] += 1

    post_count = len(posts)

    return {
        tag: round(count / post_count, 6)
        for tag, count in sorted(
            tag_post_counts.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    }


def latest_authored_at(
    posts: list[dict[str, Any]],
) -> datetime | None:
    """Return the greatest valid post creation timestamp."""
    values = [
        value
        for post in posts
        if isinstance(
            (value := post.get("createtime")),
            datetime,
        )
    ]

    if not values:
        return None

    return max(values)


def build_profile_record(
    user: dict[str, Any],
    posts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one privacy-reduced creator profile."""
    source_user_id = user.get("user_id")

    if source_user_id is None:
        raise ValueError("MySQL user row is missing user_id.")

    last_authored = latest_authored_at(posts)

    return {
        "source": MYSQL_USER_PROFILE_SOURCE,
        "source_user_id": str(source_user_id),
        "age_bucket": age_to_bucket(user.get("age")),
        "job": normalize_text(user.get("job")),
        "education": normalize_text(
            user.get("education")
        ),
        "hobby_tags": parse_multi_value(
            user.get("hobby")
        ),
        "character_tag": normalize_text(
            user.get("character")
        ),
        "user_level": user.get("level"),
        "country": normalize_text(user.get("country")),
        "province": normalize_text(
            user.get("province")
        ),
        "city": normalize_text(user.get("city")),
        "district": normalize_text(
            user.get("district")
        ),
        "school": normalize_text(user.get("school")),
        "authored_post_count": len(posts),
        "category_weights": calculate_category_weights(
            posts
        ),
        "tag_weights": calculate_tag_weights(posts),
        "avg_likes": mean_non_negative(
            posts,
            "likes",
        ),
        "avg_views": mean_non_negative(
            posts,
            "views",
        ),
        "avg_marks": mean_non_negative(
            posts,
            "marks",
        ),
        "avg_dislikes": mean_non_negative(
            posts,
            "dislikes",
        ),
        "avg_rate_score": mean_optional_score(posts),
        "last_authored_at": last_authored,
        "profile_version": 1,
        "source_updated_at": last_authored,
    }


def validate_sync_parameters(
    *,
    batch_size: int,
    after_user_id: int,
    max_rows: int | None,
) -> None:
    """Validate command-line synchronization controls."""
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size must be between 1 and {MAX_BATCH_SIZE}."
        )

    if after_user_id < 0:
        raise ValueError("after_user_id cannot be negative.")

    if max_rows is not None and max_rows < 1:
        raise ValueError(
            "max_rows must be positive when provided."
        )


def read_mysql_users(
    *,
    limit: int,
    after_user_id: int,
) -> list[dict[str, Any]]:
    """Read one deterministic MySQL user batch."""
    users_table = quote_mysql_identifier(
        MYSQL_USER_TABLE
    )

    with connect_mysql_source() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    user_id,
                    age,
                    job,
                    education,
                    hobby,
                    `character`,
                    level,
                    country,
                    province,
                    city,
                    district,
                    school
                FROM {users_table}
                WHERE user_id > %s
                ORDER BY user_id
                LIMIT %s
                """,
                (
                    after_user_id,
                    limit,
                ),
            )

            return list(cursor.fetchall())


def read_mysql_posts_for_users(
    user_ids: list[int],
) -> list[dict[str, Any]]:
    """Read authored posts for one user batch."""
    if not user_ids:
        return []

    settings = get_mysql_source_settings()
    posts_table = quote_mysql_identifier(
        settings.table
    )

    placeholders = ", ".join(
        ["%s"] * len(user_ids)
    )

    with connect_mysql_source() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    owenerid,
                    typecategory,
                    tags,
                    likes,
                    views,
                    marks,
                    dislikes,
                    ratescore,
                    createtime
                FROM {posts_table}
                WHERE owenerid IN ({placeholders})
                ORDER BY owenerid, id
                """,
                tuple(user_ids),
            )

            return list(cursor.fetchall())


async def upsert_profiles(
    profiles: list[dict[str, Any]],
) -> int:
    """Upsert one PostgreSQL user-profile batch."""
    if not profiles:
        return 0

    database_rows = [
        {
            **profile,
            "category_weights": Jsonb(
                profile["category_weights"]
            ),
            "tag_weights": Jsonb(
                profile["tag_weights"]
            ),
        }
        for profile in profiles
    ]

    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.executemany(
                """
                INSERT INTO public.user_profiles (
                    source,
                    source_user_id,
                    age_bucket,
                    job,
                    education,
                    hobby_tags,
                    character_tag,
                    user_level,
                    country,
                    province,
                    city,
                    district,
                    school,
                    authored_post_count,
                    category_weights,
                    tag_weights,
                    avg_likes,
                    avg_views,
                    avg_marks,
                    avg_dislikes,
                    avg_rate_score,
                    last_authored_at,
                    profile_version,
                    source_updated_at,
                    synced_at
                )
                VALUES (
                    %(source)s,
                    %(source_user_id)s,
                    %(age_bucket)s,
                    %(job)s,
                    %(education)s,
                    %(hobby_tags)s,
                    %(character_tag)s,
                    %(user_level)s,
                    %(country)s,
                    %(province)s,
                    %(city)s,
                    %(district)s,
                    %(school)s,
                    %(authored_post_count)s,
                    %(category_weights)s,
                    %(tag_weights)s,
                    %(avg_likes)s,
                    %(avg_views)s,
                    %(avg_marks)s,
                    %(avg_dislikes)s,
                    %(avg_rate_score)s,
                    %(last_authored_at)s,
                    %(profile_version)s,
                    %(source_updated_at)s,
                    now()
                )
                ON CONFLICT (
                    source,
                    source_user_id
                )
                DO UPDATE SET
                    age_bucket = EXCLUDED.age_bucket,
                    job = EXCLUDED.job,
                    education = EXCLUDED.education,
                    hobby_tags = EXCLUDED.hobby_tags,
                    character_tag = EXCLUDED.character_tag,
                    user_level = EXCLUDED.user_level,
                    country = EXCLUDED.country,
                    province = EXCLUDED.province,
                    city = EXCLUDED.city,
                    district = EXCLUDED.district,
                    school = EXCLUDED.school,
                    authored_post_count =
                        EXCLUDED.authored_post_count,
                    category_weights =
                        EXCLUDED.category_weights,
                    tag_weights = EXCLUDED.tag_weights,
                    avg_likes = EXCLUDED.avg_likes,
                    avg_views = EXCLUDED.avg_views,
                    avg_marks = EXCLUDED.avg_marks,
                    avg_dislikes = EXCLUDED.avg_dislikes,
                    avg_rate_score =
                        EXCLUDED.avg_rate_score,
                    last_authored_at =
                        EXCLUDED.last_authored_at,
                    profile_version =
                        EXCLUDED.profile_version,
                    source_updated_at =
                        EXCLUDED.source_updated_at,
                    synced_at = now()
                """,
                database_rows,
            )

        await connection.commit()

    return len(database_rows)


async def read_postgres_summary() -> dict[str, Any]:
    """Read synchronized profile statistics."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    count(*) AS row_count,
                    count(DISTINCT source_user_id)
                        AS distinct_source_user_ids,
                    count(*) FILTER (
                        WHERE authored_post_count > 0
                    ) AS creator_count,
                    min(authored_post_count) AS min_posts,
                    avg(authored_post_count) AS avg_posts,
                    max(authored_post_count) AS max_posts
                FROM public.user_profiles
                WHERE source = %s
                """,
                (MYSQL_USER_PROFILE_SOURCE,),
            )

            row = await cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "PostgreSQL profile summary returned no row."
        )

    return row


async def synchronize(
    *,
    batch_size: int,
    after_user_id: int,
    max_rows: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Synchronize MySQL user profiles in deterministic batches."""
    validate_sync_parameters(
        batch_size=batch_size,
        after_user_id=after_user_id,
        max_rows=max_rows,
    )

    current_user_id = after_user_id
    loaded_rows = 0
    upserted_rows = 0
    batch_count = 0

    while True:
        remaining = (
            None
            if max_rows is None
            else max_rows - loaded_rows
        )

        if remaining is not None and remaining <= 0:
            break

        requested_rows = (
            batch_size
            if remaining is None
            else min(batch_size, remaining)
        )

        users = read_mysql_users(
            limit=requested_rows,
            after_user_id=current_user_id,
        )

        if not users:
            break

        user_ids = [
            int(user["user_id"])
            for user in users
        ]

        posts = read_mysql_posts_for_users(user_ids)

        posts_by_user: dict[
            int,
            list[dict[str, Any]],
        ] = defaultdict(list)

        for post in posts:
            posts_by_user[
                int(post["owenerid"])
            ].append(post)

        profiles = [
            build_profile_record(
                user,
                posts_by_user.get(
                    int(user["user_id"]),
                    [],
                ),
            )
            for user in users
        ]

        if dry_run:
            batch_upserted = 0
        else:
            batch_upserted = await upsert_profiles(
                profiles
            )

        batch_count += 1
        loaded_rows += len(users)
        upserted_rows += batch_upserted
        current_user_id = user_ids[-1]

        print()
        print(f"========== Batch {batch_count} ==========")
        print("loaded_users:", len(users))
        print("loaded_posts:", len(posts))
        print("first_user_id:", user_ids[0])
        print("last_user_id:", user_ids[-1])
        print("upserted_profiles:", batch_upserted)
        print("total_loaded:", loaded_rows)
        print("total_upserted:", upserted_rows)

    result: dict[str, Any] = {
        "batch_count": batch_count,
        "loaded_rows": loaded_rows,
        "upserted_rows": upserted_rows,
        "last_user_id": current_user_id,
        "dry_run": dry_run,
    }

    if not dry_run:
        result["postgres_summary"] = (
            await read_postgres_summary()
        )

    return result


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize privacy-reduced MySQL user profiles "
            "into PostgreSQL."
        )
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
    )
    parser.add_argument(
        "--after-user-id",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--max-rows",
        type=int,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    return parser.parse_args()


def main() -> None:
    """Run the user-profile synchronizer."""
    args = parse_args()

    print("========== profile synchronization ==========")
    print("source:", MYSQL_USER_PROFILE_SOURCE)
    print("user_table:", MYSQL_USER_TABLE)
    print("batch_size:", args.batch_size)
    print("after_user_id:", args.after_user_id)
    print(
        "max_rows:",
        args.max_rows
        if args.max_rows is not None
        else "<all>",
    )
    print("dry_run:", args.dry_run)

    result = asyncio.run(
        synchronize(
            batch_size=args.batch_size,
            after_user_id=args.after_user_id,
            max_rows=args.max_rows,
            dry_run=args.dry_run,
        )
    )

    print()
    print("========== synchronization result ==========")

    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
