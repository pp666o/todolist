"""Offline evaluation for the geo-aware post-search service."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.post import PostCategory
from app.features.post_search.post_search import (
    PostSearchRequest,
    PostSearchResponse,
)
from app.features.post_search import post_search_service as service_module
from app.features.post_search.post_search_service import post_search_service


DEFAULT_CASES_PATH = Path(
    "data/evaluation/post_search_cases.jsonl"
)

SearchCallable = Callable[
    [PostSearchRequest],
    Awaitable[PostSearchResponse],
]


class EvaluationCase(BaseModel):
    """One manually judged post-search evaluation case."""

    case_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=500)

    top_k: int = Field(default=10, ge=1, le=100)
    recall_k: int = Field(default=200, ge=1, le=2000)

    category: PostCategory | None = None
    visible_statuses: list[str] = Field(default_factory=list)

    city: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, gt=0, le=500)

    should_return_results: bool
    relevance: dict[str, int] = Field(default_factory=dict)
    binary_relevance_threshold: int = Field(
        default=1,
        ge=1,
        le=3,
    )
    notes: str | None = None

    @field_validator("case_id", "query")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("value must not be blank")

        return normalized

    @field_validator("city", "district", "notes")
    @classmethod
    def strip_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @field_validator("visible_statuses")
    @classmethod
    def normalize_visible_statuses(
        cls,
        values: list[str],
    ) -> list[str]:
        return list(
            dict.fromkeys(
                value.strip()
                for value in values
                if value and value.strip()
            )
        )

    @field_validator("relevance")
    @classmethod
    def validate_relevance(
        cls,
        values: dict[str, int],
    ) -> dict[str, int]:
        normalized: dict[str, int] = {}

        for raw_source_id, raw_grade in values.items():
            source_id = str(raw_source_id).strip()

            if not source_id:
                raise ValueError(
                    "relevance source_id must not be blank"
                )

            grade = int(raw_grade)

            if not 0 <= grade <= 3:
                raise ValueError(
                    "relevance grade must be between 0 and 3"
                )

            normalized[source_id] = grade

        return normalized

    @model_validator(mode="after")
    def validate_case(self) -> "EvaluationCase":
        if self.top_k > self.recall_k:
            raise ValueError("top_k cannot exceed recall_k")

        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None

        if has_latitude != has_longitude:
            raise ValueError(
                "latitude and longitude must be provided together"
            )

        if self.radius_km is not None and not has_latitude:
            raise ValueError(
                "radius_km requires latitude and longitude"
            )

        binary_positive_judgments = [
            grade
            for grade in self.relevance.values()
            if grade >= self.binary_relevance_threshold
        ]

        if (
            self.should_return_results
            and not binary_positive_judgments
        ):
            raise ValueError(
                "a positive case requires at least one "
                "relevance grade greater than or equal to "
                "binary_relevance_threshold"
            )

        positive_judgments = [
            grade
            for grade in self.relevance.values()
            if grade > 0
        ]

        if (
            not self.should_return_results
            and positive_judgments
        ):
            raise ValueError(
                "a no-result case cannot contain "
                "positive relevance judgments"
            )

        return self

    def to_request(self) -> PostSearchRequest:
        """Convert the evaluation case to the production request."""
        return PostSearchRequest(
            query=self.query,
            top_k=self.top_k,
            recall_k=self.recall_k,
            category=self.category,
            visible_statuses=self.visible_statuses,
            city=self.city,
            district=self.district,
            latitude=self.latitude,
            longitude=self.longitude,
            radius_km=self.radius_km,
        )

    model_config = ConfigDict(extra="forbid")


def load_cases(path: Path) -> list[EvaluationCase]:
    """Load validated JSONL cases and reject duplicate case IDs."""
    if not path.exists():
        raise FileNotFoundError(
            f"Evaluation case file does not exist: {path}"
        )

    cases: list[EvaluationCase] = []
    seen_case_ids: set[str] = set()

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()

        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON at {path}:{line_number}: {exc}"
            ) from exc

        try:
            case = EvaluationCase.model_validate(payload)
        except Exception as exc:
            raise ValueError(
                f"Invalid evaluation case at "
                f"{path}:{line_number}: {exc}"
            ) from exc

        if case.case_id in seen_case_ids:
            raise ValueError(
                f"Duplicate case_id at {path}:{line_number}: "
                f"{case.case_id}"
            )

        seen_case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ValueError(
            f"No evaluation cases were loaded from {path}"
        )

    return cases


def relevant_source_ids(
    relevance: dict[str, int],
    binary_relevance_threshold: int = 1,
) -> set[str]:
    """Return source IDs meeting the binary relevance threshold."""
    return {
        source_id
        for source_id, grade in relevance.items()
        if grade >= binary_relevance_threshold
    }


def precision_at_k(
    returned_source_ids: Sequence[str],
    relevance: dict[str, int],
    k: int,
    binary_relevance_threshold: int = 1,
) -> float | None:
    """Calculate binary Precision@K."""
    relevant = relevant_source_ids(
        relevance,
        binary_relevance_threshold,
    )

    if not relevant:
        return None

    hits = sum(
        source_id in relevant
        for source_id in returned_source_ids[:k]
    )

    return hits / k


def recall_at_k(
    returned_source_ids: Sequence[str],
    relevance: dict[str, int],
    k: int,
    binary_relevance_threshold: int = 1,
) -> float | None:
    """Calculate binary Recall@K."""
    relevant = relevant_source_ids(
        relevance,
        binary_relevance_threshold,
    )

    if not relevant:
        return None

    hits = len(
        relevant.intersection(returned_source_ids[:k])
    )

    return hits / len(relevant)


def reciprocal_rank_at_k(
    returned_source_ids: Sequence[str],
    relevance: dict[str, int],
    k: int,
    binary_relevance_threshold: int = 1,
) -> float | None:
    """Calculate reciprocal rank of the first binary-relevant item."""
    relevant = relevant_source_ids(
        relevance,
        binary_relevance_threshold,
    )

    if not relevant:
        return None

    for rank, source_id in enumerate(
        returned_source_ids[:k],
        start=1,
    ):
        if source_id in relevant:
            return 1.0 / rank

    return 0.0


def dcg_at_k(
    grades: Sequence[int],
    k: int,
) -> float:
    """Calculate discounted cumulative gain."""
    return sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(
            grades[:k],
            start=1,
        )
    )


def ndcg_at_k(
    returned_source_ids: Sequence[str],
    relevance: dict[str, int],
    k: int,
) -> float | None:
    """Calculate graded NDCG@K."""
    positive_grades = [
        grade
        for grade in relevance.values()
        if grade > 0
    ]

    if not positive_grades:
        return None

    returned_grades = [
        relevance.get(source_id, 0)
        for source_id in returned_source_ids[:k]
    ]

    ideal_grades = sorted(
        positive_grades,
        reverse=True,
    )

    ideal_dcg = dcg_at_k(ideal_grades, k)

    if ideal_dcg <= 0:
        return 0.0

    return dcg_at_k(returned_grades, k) / ideal_dcg


def percentile(
    values: Sequence[float],
    percentile_value: float,
) -> float | None:
    """Calculate an interpolated percentile without NumPy."""
    if not values:
        return None

    if not 0 <= percentile_value <= 100:
        raise ValueError(
            "percentile_value must be between 0 and 100"
        )

    ordered = sorted(float(value) for value in values)

    if len(ordered) == 1:
        return ordered[0]

    position = (
        len(ordered) - 1
    ) * percentile_value / 100.0

    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return (
        ordered[lower_index] * (1.0 - fraction)
        + ordered[upper_index] * fraction
    )


def round_optional(
    value: float | None,
    digits: int = 6,
) -> float | None:
    if value is None:
        return None

    return round(value, digits)


async def evaluate_case(
    case: EvaluationCase,
    *,
    search: SearchCallable,
    repeat: int,
) -> dict[str, Any]:
    """Evaluate one case and retain latency from every repetition."""
    if repeat < 1:
        raise ValueError("repeat must be at least 1")

    request = case.to_request()

    responses: list[PostSearchResponse] = []
    latency_ms: list[float] = []

    for _ in range(repeat):
        started_at = time.perf_counter()

        try:
            response = await search(request)
        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000.0

            latency_ms.append(elapsed_ms)

            return {
                "case_id": case.case_id,
                "query": case.query,
                "success": False,
                "should_return_results": (
                    case.should_return_results
                ),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": [
                    round(value, 3)
                    for value in latency_ms
                ],
            }

        elapsed_ms = (
            time.perf_counter() - started_at
        ) * 1000.0

        latency_ms.append(elapsed_ms)
        responses.append(response)

    response = responses[0]

    returned_source_ids = [
        item.source_id
        for item in response.items
    ]

    rankings = [
        [item.source_id for item in repeated.items]
        for repeated in responses
    ]

    relevant_ranks = {
        source_id: (
            returned_source_ids.index(source_id) + 1
            if source_id in returned_source_ids
            else None
        )
        for source_id, grade in case.relevance.items()
        if grade >= case.binary_relevance_threshold
    }

    geo_hits = 0
    geo_evaluated_items = 0

    if case.radius_km is not None:
        for item in response.items:
            if item.distance_km is None:
                continue

            geo_evaluated_items += 1

            if item.distance_km <= case.radius_km + 1e-6:
                geo_hits += 1

    result_presence_matches = (
        (response.result_count > 0)
        == case.should_return_results
    )

    return {
        "case_id": case.case_id,
        "query": case.query,
        "binary_relevance_threshold": (
            case.binary_relevance_threshold
        ),
        "success": True,
        "should_return_results": (
            case.should_return_results
        ),
        "result_presence_matches": (
            result_presence_matches
        ),
        "request": request.model_dump(mode="json"),
        "request_id": response.request_id,
        "total_candidates": response.total_candidates,
        "result_count": response.result_count,
        "returned_source_ids": returned_source_ids,
        "relevant_ranks": relevant_ranks,
        "precision_at_k": round_optional(
            precision_at_k(
                returned_source_ids,
                case.relevance,
                case.top_k,
                case.binary_relevance_threshold,
            )
        ),
        "recall_at_k": round_optional(
            recall_at_k(
                returned_source_ids,
                case.relevance,
                case.top_k,
                case.binary_relevance_threshold,
            )
        ),
        "mrr_at_k": round_optional(
            reciprocal_rank_at_k(
                returned_source_ids,
                case.relevance,
                case.top_k,
                case.binary_relevance_threshold,
            )
        ),
        "ndcg_at_k": round_optional(
            ndcg_at_k(
                returned_source_ids,
                case.relevance,
                case.top_k,
            )
        ),
        "geo_hits": geo_hits,
        "geo_evaluated_items": geo_evaluated_items,
        "geo_range_hit_rate": (
            round(geo_hits / geo_evaluated_items, 6)
            if geo_evaluated_items
            else None
        ),
        "degraded": response.degraded,
        "degraded_reason": response.degraded_reason,
        "ranking_stable_across_repeats": all(
            ranking == rankings[0]
            for ranking in rankings
        ),
        "latency_ms": [
            round(value, 3)
            for value in latency_ms
        ],
        "notes": case.notes,
    }


def mean_defined(
    results: Sequence[dict[str, Any]],
    field_name: str,
) -> float | None:
    values = [
        float(result[field_name])
        for result in results
        if result.get(field_name) is not None
    ]

    if not values:
        return None

    return statistics.fmean(values)


def build_summary(
    case_results: Sequence[dict[str, Any]],
    *,
    redis_mode: str,
) -> dict[str, Any]:
    """Build macro metrics and operational statistics."""
    successful = [
        result
        for result in case_results
        if result.get("success") is True
    ]

    failed = [
        result
        for result in case_results
        if result.get("success") is not True
    ]

    positive_results = [
        result
        for result in successful
        if result["should_return_results"]
    ]

    all_latencies = [
        float(latency)
        for result in case_results
        for latency in result.get("latency_ms", [])
    ]

    total_geo_hits = sum(
        int(result.get("geo_hits", 0))
        for result in successful
    )
    total_geo_items = sum(
        int(result.get("geo_evaluated_items", 0))
        for result in successful
    )

    no_result_count = sum(
        result["result_count"] == 0
        for result in successful
    )

    expectation_matches = sum(
        bool(result["result_presence_matches"])
        for result in successful
    )

    degraded_count = sum(
        bool(result["degraded"])
        for result in successful
    )

    stable_count = sum(
        bool(result["ranking_stable_across_repeats"])
        for result in successful
    )

    redis_degradation_success_rate: float | None = None

    if redis_mode == "forced-failure":
        if positive_results:
            degradation_successes = sum(
                bool(result["degraded"])
                and result["result_count"] > 0
                for result in positive_results
            )

            redis_degradation_success_rate = (
                degradation_successes
                / len(positive_results)
            )

    return {
        "case_count": len(case_results),
        "successful_case_count": len(successful),
        "failed_case_count": len(failed),
        "request_success_rate": (
            len(successful) / len(case_results)
            if case_results
            else 0.0
        ),
        "positive_case_count": len(positive_results),
        "macro_precision_at_k": round_optional(
            mean_defined(successful, "precision_at_k")
        ),
        "macro_recall_at_k": round_optional(
            mean_defined(successful, "recall_at_k")
        ),
        "mrr_at_k": round_optional(
            mean_defined(successful, "mrr_at_k")
        ),
        "macro_ndcg_at_k": round_optional(
            mean_defined(successful, "ndcg_at_k")
        ),
        "geo_range_hit_rate": (
            round(total_geo_hits / total_geo_items, 6)
            if total_geo_items
            else None
        ),
        "no_result_rate": (
            round(no_result_count / len(successful), 6)
            if successful
            else None
        ),
        "result_expectation_accuracy": (
            round(
                expectation_matches / len(successful),
                6,
            )
            if successful
            else None
        ),
        "degraded_response_rate": (
            round(degraded_count / len(successful), 6)
            if successful
            else None
        ),
        "redis_degradation_success_rate": (
            round(
                redis_degradation_success_rate,
                6,
            )
            if redis_degradation_success_rate is not None
            else None
        ),
        "ranking_stability_rate": (
            round(stable_count / len(successful), 6)
            if successful
            else None
        ),
        "latency_ms": {
            "count": len(all_latencies),
            "mean": round(
                statistics.fmean(all_latencies),
                3,
            )
            if all_latencies
            else None,
            "p50": round_optional(
                percentile(all_latencies, 50),
                3,
            ),
            "p95": round_optional(
                percentile(all_latencies, 95),
                3,
            ),
            "max": round(max(all_latencies), 3)
            if all_latencies
            else None,
        },
    }


async def evaluate_cases(
    cases: Sequence[EvaluationCase],
    *,
    search: SearchCallable,
    repeat: int,
    redis_mode: str,
) -> dict[str, Any]:
    """Evaluate cases sequentially for stable latency measurement."""
    case_results: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] "
            f"{case.case_id}: {case.query}",
            flush=True,
        )

        result = await evaluate_case(
            case,
            search=search,
            repeat=repeat,
        )
        case_results.append(result)

        if result["success"]:
            print(
                "  result_count="
                f"{result['result_count']}, "
                "recall@k="
                f"{result['recall_at_k']}, "
                "mrr="
                f"{result['mrr_at_k']}, "
                "degraded="
                f"{result['degraded']}",
                flush=True,
            )
        else:
            print(
                "  ERROR: "
                f"{result['error_type']}: "
                f"{result['error_message']}",
                flush=True,
            )

    return {
        "schema_version": 1,
        "redis_mode": redis_mode,
        "repeat": repeat,
        "summary": build_summary(
            case_results,
            redis_mode=redis_mode,
        ),
        "cases": case_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the production PostSearchService against "
            "a manually judged JSONL dataset."
        )
    )

    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help=(
            "JSONL evaluation cases. "
            f"Default: {DEFAULT_CASES_PATH}"
        ),
    )

    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "Number of search repetitions per case for latency "
            "and ranking-stability measurement."
        ),
    )

    parser.add_argument(
        "--redis-mode",
        choices=("live", "forced-failure"),
        default="live",
        help=(
            "Use live Redis, or simulate a Redis read failure "
            "inside the evaluator process."
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report output path.",
    )

    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    return args


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.cases)

    original_realtime_reader = (
        service_module.get_post_realtime_features
    )

    if args.redis_mode == "forced-failure":

        async def forced_redis_failure(
            _: Sequence[str],
        ) -> dict[str, dict[str, int]]:
            raise ConnectionError(
                "forced evaluation Redis failure"
            )

        service_module.get_post_realtime_features = (
            forced_redis_failure
        )

    try:
        return await evaluate_cases(
            cases,
            search=post_search_service.search,
            repeat=args.repeat,
            redis_mode=args.redis_mode,
        )
    finally:
        service_module.get_post_realtime_features = (
            original_realtime_reader
        )


def main() -> None:
    args = parse_args()
    report = asyncio.run(async_main(args))

    serialized = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
    )

    print("\n========== Evaluation summary ==========")
    print(
        json.dumps(
            report["summary"],
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.output is not None:
        args.output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        args.output.write_text(
            serialized + "\n",
            encoding="utf-8",
        )
        print(f"\n[OK] report written to {args.output}")


if __name__ == "__main__":
    main()
