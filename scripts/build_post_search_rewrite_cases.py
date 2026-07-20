"""Build the formal natural-query post-search evaluation dataset."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from scripts.evaluate_post_search import EvaluationCase


DEFAULT_QUERY_POOL = Path(
    "data/evaluation/annotation_work/query_rewrite_pool.csv"
)
DEFAULT_JUDGMENT_POOL = Path(
    "data/evaluation/annotation_work/relevance_judgment_pool.csv"
)
DEFAULT_OUTPUT = Path(
    "data/evaluation/post_search_rewrite_cases.jsonl"
)

VALID_GRADES = {"0", "1", "2", "3"}


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV does not exist: {path}")

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def require_text(
    row: dict[str, str],
    field: str,
) -> str:
    value = row.get(field, "").strip()

    if not value:
        raise ValueError(
            f"Required field is blank: field={field}, row={row}"
        )

    return value


def optional_float(value: str) -> float | None:
    normalized = value.strip()

    if not normalized:
        return None

    return float(normalized)


def select_compact_candidates(
    rows: Sequence[dict[str, str]],
    *,
    top_k: int,
) -> list[dict[str, str]]:
    """Select search Top-K plus an anchor missed by that Top-K."""
    search_rows = [
        row
        for row in rows
        if row.get("candidate_origin") == "search_result"
    ]

    search_rows.sort(
        key=lambda row: int(
            require_text(row, "candidate_rank")
        )
    )

    selected = search_rows[:top_k]
    selected_ids = {
        require_text(row, "candidate_source_id")
        for row in selected
    }

    anchor_rows = [
        row
        for row in rows
        if row.get("is_anchor") == "yes"
    ]

    if len(anchor_rows) != 1:
        raise ValueError(
            "Each draft must contain exactly one anchor: "
            f"found={len(anchor_rows)}"
        )

    anchor = anchor_rows[0]
    anchor_source_id = require_text(
        anchor,
        "candidate_source_id",
    )

    if anchor_source_id not in selected_ids:
        selected.append(anchor)

    return selected


def validate_reviewed_candidate(
    row: dict[str, str],
) -> None:
    grade = row.get("relevance_grade", "").strip()

    if row.get("review_status") != "assistant_reviewed":
        raise ValueError(
            "Candidate is not reviewed: "
            f"draft_id={row.get('draft_id')}, "
            f"source_id={row.get('candidate_source_id')}"
        )

    if grade not in VALID_GRADES:
        raise ValueError(
            "Candidate has invalid relevance grade: "
            f"draft_id={row.get('draft_id')}, "
            f"source_id={row.get('candidate_source_id')}, "
            f"grade={grade!r}"
        )


def build_case(
    draft: dict[str, str],
    candidate_rows: Sequence[dict[str, str]],
    *,
    top_k: int,
    recall_k: int,
    binary_relevance_threshold: int,
    radius_km: float,
) -> dict[str, Any]:
    draft_id = require_text(draft, "draft_id")
    query = require_text(draft, "query")
    query_type = require_text(draft, "query_type")
    anchor_source_id = require_text(
        draft,
        "anchor_source_id",
    )

    selected = select_compact_candidates(
        candidate_rows,
        top_k=top_k,
    )

    for row in selected:
        validate_reviewed_candidate(row)

    relevance = {
        require_text(row, "candidate_source_id"): int(
            require_text(row, "relevance_grade")
        )
        for row in selected
    }

    if anchor_source_id not in relevance:
        raise ValueError(
            f"Anchor missing from compact pool: {draft_id}"
        )

    if not any(
        grade >= binary_relevance_threshold
        for grade in relevance.values()
    ):
        raise ValueError(
            "Case has no grade meeting binary threshold: "
            f"{draft_id}"
        )

    case: dict[str, Any] = {
        "case_id": f"rewrite_{query_type}_{draft_id}",
        "query": query,
        "top_k": top_k,
        "recall_k": recall_k,
        "should_return_results": True,
        "binary_relevance_threshold": (
            binary_relevance_threshold
        ),
        "relevance": relevance,
        "notes": (
            f"人工自然改写；query_type={query_type}；"
            f"anchor_source_id={anchor_source_id}；"
            "相关性池为当前规则搜索Top-K并集未召回anchor；"
            "grade>=2计入二值相关，grade=1仅参与分级NDCG"
        ),
    }

    if query_type == "geo_intent":
        latitude = optional_float(
            draft.get("latitude", "")
        )
        longitude = optional_float(
            draft.get("longitude", "")
        )

        if latitude is None or longitude is None:
            raise ValueError(
                f"Geo case lacks coordinates: {draft_id}"
            )

        case.update(
            {
                "city": require_text(draft, "city"),
                "district": require_text(
                    draft,
                    "district",
                ),
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
            }
        )

    if query_type == "category_intent":
        case["category"] = require_text(
            draft,
            "category",
        )

    validated = EvaluationCase.model_validate(case)

    return validated.model_dump(
        mode="json",
        exclude_none=True,
    )


def build_cases(
    drafts: Sequence[dict[str, str]],
    judgments: Sequence[dict[str, str]],
    *,
    top_k: int,
    recall_k: int,
    binary_relevance_threshold: int,
    radius_km: float,
) -> list[dict[str, Any]]:
    judgment_groups: dict[
        str,
        list[dict[str, str]],
    ] = defaultdict(list)

    for row in judgments:
        draft_id = require_text(row, "draft_id")
        judgment_groups[draft_id].append(row)

    cases: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()

    drafted_rows = [
        row
        for row in drafts
        if row.get("review_status") == "query_drafted"
        and row.get("query", "").strip()
    ]

    drafted_rows.sort(
        key=lambda row: require_text(row, "draft_id")
    )

    if not drafted_rows:
        raise ValueError("No query_drafted rows were found")

    for draft in drafted_rows:
        draft_id = require_text(draft, "draft_id")
        candidate_rows = judgment_groups.get(draft_id)

        if not candidate_rows:
            raise ValueError(
                f"No judgment candidates found: {draft_id}"
            )

        case = build_case(
            draft,
            candidate_rows,
            top_k=top_k,
            recall_k=recall_k,
            binary_relevance_threshold=(
                binary_relevance_threshold
            ),
            radius_km=radius_km,
        )

        case_id = str(case["case_id"])

        if case_id in seen_case_ids:
            raise ValueError(
                f"Duplicate case_id generated: {case_id}"
            )

        seen_case_ids.add(case_id)
        cases.append(case)

    return cases


def write_jsonl(
    path: Path,
    cases: Sequence[dict[str, Any]],
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
        encoding="utf-8",
    ) as file:
        for case in cases:
            file.write(
                json.dumps(
                    case,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert reviewed natural-query candidates into "
            "the formal post-search JSONL evaluation dataset."
        )
    )

    parser.add_argument(
        "--query-pool",
        type=Path,
        default=DEFAULT_QUERY_POOL,
    )
    parser.add_argument(
        "--judgment-pool",
        type=Path,
        default=DEFAULT_JUDGMENT_POOL,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--recall-k",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--binary-relevance-threshold",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--radius-km",
        type=float,
        default=20.0,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")

    if not args.top_k <= args.recall_k <= 2000:
        parser.error(
            "--recall-k must be between top-k and 2000"
        )

    if not 1 <= args.binary_relevance_threshold <= 3:
        parser.error(
            "--binary-relevance-threshold must be 1, 2, or 3"
        )

    if not 0 < args.radius_km <= 500:
        parser.error(
            "--radius-km must be greater than 0 and at most 500"
        )

    return args


def main() -> None:
    args = parse_args()

    drafts = load_csv(args.query_pool)
    judgments = load_csv(args.judgment_pool)

    cases = build_cases(
        drafts,
        judgments,
        top_k=args.top_k,
        recall_k=args.recall_k,
        binary_relevance_threshold=(
            args.binary_relevance_threshold
        ),
        radius_km=args.radius_km,
    )

    write_jsonl(
        args.output,
        cases,
        overwrite=args.overwrite,
    )

    query_types = Counter(
        str(case["case_id"]).removeprefix("rewrite_").rsplit(
            "_draft_",
            maxsplit=1,
        )[0]
        for case in cases
    )

    grade_distribution = Counter(
        grade
        for case in cases
        for grade in case["relevance"].values()
    )

    print("========== Rewrite evaluation dataset ==========")
    print("case_count:", len(cases))
    print("query_types:", dict(query_types))
    print(
        "judgment_count:",
        sum(len(case["relevance"]) for case in cases),
    )
    print(
        "grade_distribution:",
        dict(sorted(grade_distribution.items())),
    )
    print("output:", args.output)
    print("[OK] formal rewrite evaluation dataset built")


if __name__ == "__main__":
    main()
