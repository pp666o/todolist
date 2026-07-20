"""Export ranked candidates for manual search relevance judgment."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.infrastructure.postgres import connect_postgres
from app.schemas.post_search import PostSearchRequest
from app.services.post_search_service import post_search_service


DEFAULT_INPUT = Path(
    "data/evaluation/annotation_work/query_rewrite_pool.csv"
)
DEFAULT_OUTPUT = Path(
    "data/evaluation/annotation_work/relevance_judgment_pool.csv"
)

OUTPUT_COLUMNS = (
    "draft_id",
    "query",
    "query_type",
    "anchor_source_id",
    "candidate_rank",
    "candidate_source_id",
    "candidate_origin",
    "is_anchor",
    "candidate_category",
    "candidate_city",
    "candidate_district",
    "candidate_title",
    "candidate_content_preview",
    "distance_km",
    "score",
    "text_score",
    "geo_score",
    "hot_score",
    "unlock_score",
    "recall_sources",
    "relevance_grade",
    "judgment_notes",
    "review_status",
    "reviewer",
)


def normalize_text(
    value: Any,
    *,
    max_chars: int,
) -> str:
    if value is None:
        return ""

    normalized = " ".join(str(value).split())

    if len(normalized) <= max_chars:
        return normalized

    return normalized[: max_chars - 1].rstrip() + "…"


def load_drafts(path: Path) -> list[dict[str, str]]:
    """Load rows that contain a drafted query."""
    if not path.exists():
        raise FileNotFoundError(
            f"Input annotation pool does not exist: {path}"
        )

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    drafted = [
        row
        for row in rows
        if row.get("query", "").strip()
        and row.get("review_status") == "query_drafted"
    ]

    if not drafted:
        raise ValueError(
            "No query_drafted rows were found in the input pool"
        )

    return drafted


def optional_float(value: str) -> float | None:
    normalized = value.strip()

    if not normalized:
        return None

    return float(normalized)


async def fetch_anchor_post(
    source_id: str,
) -> dict[str, Any] | None:
    """Fetch an annotation anchor independently of search ranking."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    source_id,
                    title,
                    content,
                    category,
                    city,
                    district
                FROM posts
                WHERE source = 'mysql_tiezi_geo_new'
                  AND source_id = %s
                LIMIT 1
                """,
                (source_id,),
            )
            row = await cursor.fetchone()

    return row


async def search_draft(
    draft: dict[str, str],
    *,
    candidate_k: int,
    recall_k: int,
    search: Callable[
        [PostSearchRequest],
        Awaitable[Any],
    ] | None = None,
    fetch_anchor: Callable[
        [str],
        Awaitable[dict[str, Any] | None],
    ] | None = None,
) -> list[dict[str, Any]]:
    """Run one query and inject its anchor when search misses it."""
    if search is None:
        search = post_search_service.search

    if fetch_anchor is None:
        fetch_anchor = fetch_anchor_post

    latitude = optional_float(
        draft.get("latitude", "")
    )
    longitude = optional_float(
        draft.get("longitude", "")
    )

    use_geo = draft.get("query_type") == "geo_intent"

    request = PostSearchRequest(
        query=draft["query"].strip(),
        top_k=candidate_k,
        recall_k=recall_k,
        category=(
            draft["category"]
            if draft.get("query_type") == "category_intent"
            else None
        ),
        city=(
            draft["city"]
            if use_geo and draft.get("city")
            else None
        ),
        district=(
            draft["district"]
            if use_geo and draft.get("district")
            else None
        ),
        latitude=latitude if use_geo else None,
        longitude=longitude if use_geo else None,
        radius_km=20.0 if use_geo else None,
    )

    response = await search(request)

    anchor_source_id = draft["anchor_source_id"].strip()
    output: list[dict[str, Any]] = []

    for rank, item in enumerate(
        response.items,
        start=1,
    ):
        output.append(
            {
                "draft_id": draft["draft_id"],
                "query": draft["query"],
                "query_type": draft["query_type"],
                "anchor_source_id": anchor_source_id,
                "candidate_rank": rank,
                "candidate_source_id": item.source_id,
                "candidate_origin": "search_result",
                "is_anchor": (
                    "yes"
                    if item.source_id == anchor_source_id
                    else "no"
                ),
                "candidate_category": item.category,
                "candidate_city": item.city or "",
                "candidate_district": item.district or "",
                "candidate_title": normalize_text(
                    item.title,
                    max_chars=300,
                ),
                "candidate_content_preview": normalize_text(
                    item.content,
                    max_chars=500,
                ),
                "distance_km": (
                    ""
                    if item.distance_km is None
                    else item.distance_km
                ),
                "score": item.score,
                "text_score": (
                    ""
                    if item.text_score is None
                    else item.text_score
                ),
                "geo_score": (
                    ""
                    if item.geo_score is None
                    else item.geo_score
                ),
                "hot_score": (
                    ""
                    if item.hot_score is None
                    else item.hot_score
                ),
                "unlock_score": (
                    ""
                    if item.unlock_score is None
                    else item.unlock_score
                ),
                "recall_sources": json.dumps(
                    item.recall_sources,
                    ensure_ascii=False,
                ),
                "relevance_grade": "",
                "judgment_notes": "",
                "review_status": "unjudged",
                "reviewer": "",
            }
        )

    anchor_found = any(
        row["candidate_source_id"] == anchor_source_id
        and row["candidate_origin"] == "search_result"
        for row in output
    )

    if not anchor_found:
        anchor = await fetch_anchor(anchor_source_id)

        if anchor is None:
            raise RuntimeError(
                "Annotation anchor does not exist in PostgreSQL: "
                f"{anchor_source_id}"
            )

        output.append(
            {
                "draft_id": draft["draft_id"],
                "query": draft["query"],
                "query_type": draft["query_type"],
                "anchor_source_id": anchor_source_id,
                "candidate_rank": "",
                "candidate_source_id": str(
                    anchor["source_id"]
                ),
                "candidate_origin": "injected_anchor",
                "is_anchor": "yes",
                "candidate_category": anchor["category"],
                "candidate_city": anchor.get("city") or "",
                "candidate_district": (
                    anchor.get("district") or ""
                ),
                "candidate_title": normalize_text(
                    anchor.get("title"),
                    max_chars=300,
                ),
                "candidate_content_preview": normalize_text(
                    anchor.get("content"),
                    max_chars=500,
                ),
                "distance_km": "",
                "score": "",
                "text_score": "",
                "geo_score": "",
                "hot_score": "",
                "unlock_score": "",
                "recall_sources": "[]",
                "relevance_grade": "",
                "judgment_notes": "",
                "review_status": "unjudged",
                "reviewer": "",
            }
        )

    return output


async def build_pool(
    drafts: list[dict[str, str]],
    *,
    candidate_k: int,
    recall_k: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for index, draft in enumerate(
        drafts,
        start=1,
    ):
        print(
            f"[{index}/{len(drafts)}] "
            f"{draft['draft_id']}: {draft['query']}",
            flush=True,
        )

        candidate_rows = await search_draft(
            draft,
            candidate_k=candidate_k,
            recall_k=recall_k,
        )

        search_rows = [
            row
            for row in candidate_rows
            if row["candidate_origin"] == "search_result"
        ]

        anchor_search_rows = [
            row
            for row in search_rows
            if row["is_anchor"] == "yes"
        ]

        anchor_found = bool(anchor_search_rows)
        anchor_rank = (
            anchor_search_rows[0]["candidate_rank"]
            if anchor_search_rows
            else None
        )

        anchor_injected = any(
            row["candidate_origin"] == "injected_anchor"
            for row in candidate_rows
        )

        print(
            f"  candidates={len(search_rows)}, "
            f"anchor_found={anchor_found}, "
            f"anchor_rank={anchor_rank}, "
            f"anchor_injected={anchor_injected}",
            flush=True,
        )

        rows.extend(candidate_rows)

    return rows


def write_pool(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    overwrite: bool,
) -> None:
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
            fieldnames=OUTPUT_COLUMNS,
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run drafted queries and export candidates for "
            "manual 0/1/2/3 relevance judgment."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--recall-k",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    if not 1 <= args.candidate_k <= 100:
        parser.error(
            "--candidate-k must be between 1 and 100"
        )

    if not args.candidate_k <= args.recall_k <= 2000:
        parser.error(
            "--recall-k must be between candidate-k and 2000"
        )

    return args


async def async_main(
    args: argparse.Namespace,
) -> tuple[int, int]:
    drafts = load_drafts(args.input)

    rows = await build_pool(
        drafts,
        candidate_k=args.candidate_k,
        recall_k=args.recall_k,
    )

    write_pool(
        args.output,
        rows,
        overwrite=args.overwrite,
    )

    return len(drafts), len(rows)


def main() -> None:
    args = parse_args()

    draft_count, candidate_count = asyncio.run(
        async_main(args)
    )

    print("========== Judgment pool ==========")
    print(f"draft_count: {draft_count}")
    print(f"candidate_count: {candidate_count}")
    print(f"output: {args.output}")
    print(
        "[OK] Candidate pool exported; "
        "relevance grades remain unfilled."
    )


if __name__ == "__main__":
    main()
