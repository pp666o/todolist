"""Export a stratified pool of real posts for manual query rewriting."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from pathlib import Path
from typing import Any, Sequence

from app.infrastructure.postgres import connect_postgres


DEFAULT_OUTPUT = Path(
    "data/evaluation/annotation_work/query_rewrite_pool.csv"
)

ANNOTATION_COLUMNS = (
    "draft_id",
    "anchor_source_id",
    "category",
    "city",
    "district",
    "address",
    "latitude",
    "longitude",
    "title",
    "content_preview",
    "query",
    "query_type",
    "intent_notes",
    "anchor_proposed_grade",
    "anchor_grade_confirmed",
    "review_status",
    "reviewer",
)

QUERY_TYPE_GUIDANCE = (
    "title_rewrite",
    "partial_keywords",
    "content_intent",
    "synonym_expression",
    "geo_intent",
    "category_intent",
)


def normalize_text(
    value: Any,
    *,
    max_chars: int,
) -> str:
    """Collapse whitespace and safely truncate text for annotation."""
    if value is None:
        return ""

    normalized = re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()

    if len(normalized) <= max_chars:
        return normalized

    if max_chars <= 1:
        return normalized[:max_chars]

    return normalized[: max_chars - 1].rstrip() + "…"


def build_annotation_rows(
    posts: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert database posts into deterministic annotation rows."""
    rows: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()

    for post in posts:
        source_id = str(post.get("source_id", "")).strip()

        if not source_id or source_id in seen_source_ids:
            continue

        title = normalize_text(
            post.get("title"),
            max_chars=300,
        )
        content_preview = normalize_text(
            post.get("content"),
            max_chars=500,
        )

        if not title or not content_preview:
            continue

        seen_source_ids.add(source_id)

        rows.append(
            {
                "draft_id": f"draft_{len(rows) + 1:03d}",
                "anchor_source_id": source_id,
                "category": normalize_text(
                    post.get("category"),
                    max_chars=30,
                ),
                "city": normalize_text(
                    post.get("city"),
                    max_chars=100,
                ),
                "district": normalize_text(
                    post.get("district"),
                    max_chars=100,
                ),
                "address": normalize_text(
                    post.get("address"),
                    max_chars=200,
                ),
                "latitude": (
                    ""
                    if post.get("latitude") is None
                    else float(post["latitude"])
                ),
                "longitude": (
                    ""
                    if post.get("longitude") is None
                    else float(post["longitude"])
                ),
                "title": title,
                "content_preview": content_preview,
                "query": "",
                "query_type": "",
                "intent_notes": "",
                "anchor_proposed_grade": 3,
                "anchor_grade_confirmed": "",
                "review_status": "draft",
                "reviewer": "",
            }
        )

    return rows


async def fetch_posts(
    *,
    source: str,
    sample_size: int,
    per_group_limit: int,
    seed: str,
) -> list[dict[str, Any]]:
    """Fetch deterministic stratified samples from PostgreSQL."""
    query = """
        WITH eligible AS (
            SELECT
                source_id,
                title,
                content,
                category,
                city,
                district,
                address,
                latitude,
                longitude,
                likes,
                views,
                marks
            FROM posts
            WHERE source = %(source)s
              AND COALESCE(BTRIM(source_id), '') <> ''
              AND COALESCE(BTRIM(title), '') <> ''
              AND COALESCE(BTRIM(content), '') <> ''
              AND COALESCE(BTRIM(category), '') <> ''
              AND COALESCE(BTRIM(city), '') <> ''
              AND COALESCE(BTRIM(district), '') <> ''
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
        ),
        ranked AS (
            SELECT
                eligible.*,
                row_number() OVER (
                    PARTITION BY category, city, district
                    ORDER BY md5(
                        source_id || %(seed)s
                    )
                ) AS group_rank
            FROM eligible
        )
        SELECT
            source_id,
            title,
            content,
            category,
            city,
            district,
            address,
            latitude,
            longitude,
            likes,
            views,
            marks
        FROM ranked
        WHERE group_rank <= %(per_group_limit)s
        ORDER BY
            group_rank,
            md5(source_id || %(seed)s)
        LIMIT %(sample_size)s
    """

    parameters = {
        "source": source,
        "sample_size": sample_size,
        "per_group_limit": per_group_limit,
        "seed": seed,
    }

    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(query, parameters)
            rows = await cursor.fetchall()

    return list(rows)


def write_csv(
    path: Path,
    rows: Sequence[dict[str, Any]],
    *,
    overwrite: bool,
) -> None:
    """Write an annotation-friendly UTF-8 CSV."""
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {path}; "
            "pass --overwrite to replace it"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=ANNOTATION_COLUMNS,
        )
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(
    path: Path,
    rows: Sequence[dict[str, Any]],
    *,
    overwrite: bool,
) -> None:
    """Write a machine-readable mirror of the annotation pool."""
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {path}; "
            "pass --overwrite to replace it"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        for row in rows:
            file.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stratify real PostgreSQL posts into a manual "
            "query-rewriting annotation pool."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--source",
        default="mysql_tiezi_geo_new",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=30,
    )
    parser.add_argument(
        "--per-group-limit",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--seed",
        default="20260720",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    if not 1 <= args.sample_size <= 500:
        parser.error(
            "--sample-size must be between 1 and 500"
        )

    if not 1 <= args.per_group_limit <= 20:
        parser.error(
            "--per-group-limit must be between 1 and 20"
        )

    if args.output.suffix.lower() != ".csv":
        parser.error("--output must use the .csv suffix")

    return args


async def async_main(
    args: argparse.Namespace,
) -> tuple[Path, Path, int]:
    posts = await fetch_posts(
        source=args.source,
        sample_size=args.sample_size,
        per_group_limit=args.per_group_limit,
        seed=args.seed,
    )

    rows = build_annotation_rows(posts)

    if len(rows) != args.sample_size:
        raise RuntimeError(
            "PostgreSQL returned fewer valid annotation rows "
            f"than requested: requested={args.sample_size}, "
            f"valid={len(rows)}"
        )

    csv_path = args.output
    jsonl_path = csv_path.with_suffix(".jsonl")

    write_csv(
        csv_path,
        rows,
        overwrite=args.overwrite,
    )
    write_jsonl(
        jsonl_path,
        rows,
        overwrite=args.overwrite,
    )

    return csv_path, jsonl_path, len(rows)


def main() -> None:
    args = parse_args()

    csv_path, jsonl_path, row_count = asyncio.run(
        async_main(args)
    )

    print("========== Annotation pool ==========")
    print(f"row_count: {row_count}")
    print(f"csv: {csv_path}")
    print(f"jsonl: {jsonl_path}")
    print(
        "query_type guidance: "
        + ", ".join(QUERY_TYPE_GUIDANCE)
    )
    print(
        "[OK] Real-post annotation pool exported; "
        "queries and judgments remain unfilled."
    )


if __name__ == "__main__":
    main()
