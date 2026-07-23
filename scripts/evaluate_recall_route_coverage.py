#!/usr/bin/env python3
"""Evaluate marginal candidate coverage across post recall routes."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.infrastructure.postgres import connect_postgres
from app.repositories.post_repository import (
    PostRepository,
    post_repository,
)
from app.search.candidate_merge import candidate_key
from app.search.embedding import (
    DEFAULT_MODEL_PATH,
    encode_query,
    load_model,
    resolve_device,
)
from app.search.geo import (
    calculate_bounding_box,
    haversine_km,
)
from app.search.lexical_retrieval import (
    lexical_search_filtered,
)
from app.search.semantic_retrieval import (
    MAX_EF_SEARCH,
    MAX_RECALL_LIMIT,
    semantic_search_filtered,
)
from scripts.evaluate_post_search import (
    EvaluationCase,
    load_cases,
    percentile,
    round_optional,
)


DEFAULT_CASES_PATH = Path(
    "data/evaluation/post_search_rewrite_cases.jsonl"
)
DEFAULT_OUTPUT_PATH = Path(
    "data/evaluation/results/recall_route_coverage.json"
)

DEFAULT_LIMIT = 200
DEFAULT_CUTOFFS = (20, 100, 200)
DEFAULT_EF_SEARCH = 200
DEFAULT_ITERATIVE_SCAN = "strict_order"
DEFAULT_LEXICAL_OVERFETCH_FACTOR = 4.0
DEFAULT_RADIUS_OVERFETCH_FACTOR = 2.0

ROUTES = (
    "freshness",
    "lexical",
    "semantic",
)

COMBINATIONS: dict[str, tuple[str, ...]] = {
    "freshness_lexical": (
        "freshness",
        "lexical",
    ),
    "freshness_semantic": (
        "freshness",
        "semantic",
    ),
    "freshness_lexical_semantic": (
        "freshness",
        "lexical",
        "semantic",
    ),
}

OVERLAP_PAIRS: dict[str, tuple[str, str]] = {
    "freshness_lexical": (
        "freshness",
        "lexical",
    ),
    "freshness_semantic": (
        "freshness",
        "semantic",
    ),
    "lexical_semantic": (
        "lexical",
        "semantic",
    ),
}

MARGINAL_CONFIGURATIONS: dict[
    str,
    tuple[str, tuple[str, ...]],
] = {
    "lexical_over_freshness": (
        "lexical",
        ("freshness",),
    ),
    "semantic_over_freshness": (
        "semantic",
        ("freshness",),
    ),
    "semantic_over_freshness_lexical": (
        "semantic",
        (
            "freshness",
            "lexical",
        ),
    ),
}

CandidateKey = tuple[str, str]


def normalize_positive_values(
    values: Sequence[int],
    *,
    name: str,
    maximum: int,
) -> list[int]:
    """Validate, deduplicate, and sort positive integer values."""

    if not values:
        raise ValueError(
            f"{name} must contain at least one value"
        )

    normalized = sorted(
        {
            int(value)
            for value in values
        }
    )

    if normalized[0] < 1:
        raise ValueError(
            f"{name} values must be greater than zero"
        )

    if normalized[-1] > maximum:
        raise ValueError(
            f"{name} values must not exceed {maximum}"
        )

    return normalized


def mean_defined(
    values: Sequence[float | None],
) -> float | None:
    """Return the arithmetic mean of defined values."""

    defined = [
        float(value)
        for value in values
        if value is not None
    ]

    if not defined:
        return None

    return statistics.fmean(defined)


def latency_summary(
    values: Sequence[float],
) -> dict[str, float | int | None]:
    """Return a compact latency distribution."""

    normalized = [
        float(value)
        for value in values
    ]

    return {
        "count": len(normalized),
        "mean": (
            round(
                statistics.fmean(normalized),
                3,
            )
            if normalized
            else None
        ),
        "p50": round_optional(
            percentile(normalized, 50),
            3,
        ),
        "p95": round_optional(
            percentile(normalized, 95),
            3,
        ),
        "max": (
            round(max(normalized), 3)
            if normalized
            else None
        ),
    }


def category_value(
    case: EvaluationCase,
) -> str | None:
    """Return the plain category value expected by PostgreSQL."""

    if case.category is None:
        return None

    value = getattr(
        case.category,
        "value",
        case.category,
    )

    return str(value)


def bounding_box_for_case(
    case: EvaluationCase,
) -> dict[str, float | None]:
    """Return a geographical bounding box for one case."""

    if (
        case.latitude is None
        or case.longitude is None
        or case.radius_km is None
    ):
        return {
            "min_latitude": None,
            "max_latitude": None,
            "min_longitude": None,
            "max_longitude": None,
        }

    return calculate_bounding_box(
        case.latitude,
        case.longitude,
        case.radius_km,
    )


def case_filter_configuration(
    case: EvaluationCase,
) -> dict[str, Any]:
    """Return the filters used by all candidate routes."""

    return {
        "category": category_value(case),
        "visible_statuses": list(
            case.visible_statuses
        ),
        "city": case.city,
        "district": case.district,
        "latitude": case.latitude,
        "longitude": case.longitude,
        "radius_km": case.radius_km,
    }


def ordered_candidate_keys(
    candidates: Sequence[Mapping[str, Any]],
) -> list[CandidateKey]:
    """Return unique business keys while preserving route order."""

    keys: list[CandidateKey] = []
    seen: set[CandidateKey] = set()

    for candidate in candidates:
        key = candidate_key(candidate)

        if key in seen:
            continue

        seen.add(key)
        keys.append(key)

    return keys


def prefix_key_set(
    route_keys: Sequence[CandidateKey],
    cutoff: int,
) -> set[CandidateKey]:
    """Return the business-key set in one route's top cutoff."""

    return set(route_keys[:cutoff])


def relevant_source_ids(
    case: EvaluationCase,
    *,
    exact_grade: int | None = None,
) -> set[str]:
    """Return binary-relevant or exact-grade source IDs."""

    if exact_grade is not None:
        return {
            source_id
            for source_id, grade in (
                case.relevance.items()
            )
            if grade == exact_grade
        }

    return {
        source_id
        for source_id, grade in case.relevance.items()
        if grade >= case.binary_relevance_threshold
    }


def coverage_metrics(
    *,
    route_names: Sequence[str],
    route_keys: Mapping[
        str,
        Sequence[CandidateKey],
    ],
    case: EvaluationCase,
    cutoff: int,
) -> dict[str, Any]:
    """Measure set coverage from the union of route Top-K sets.

    Combined-route coverage intentionally does not introduce a new
    ranking algorithm. For a cutoff K, each selected route contributes
    its own top K candidates, and metrics are calculated on the union.
    """

    candidate_keys: set[CandidateKey] = set()

    for route_name in route_names:
        candidate_keys.update(
            prefix_key_set(
                route_keys[route_name],
                cutoff,
            )
        )

    candidate_source_ids = {
        source_id
        for _, source_id in candidate_keys
    }

    relevant = relevant_source_ids(case)
    grade3 = relevant_source_ids(
        case,
        exact_grade=3,
    )

    relevant_hits = sorted(
        candidate_source_ids & relevant
    )
    grade3_hits = sorted(
        candidate_source_ids & grade3
    )

    return {
        "candidate_count": len(candidate_keys),
        "relevant_hit_count": len(
            relevant_hits
        ),
        "relevant_source_ids": relevant_hits,
        "recall": (
            round_optional(
                len(relevant_hits) / len(relevant)
            )
            if relevant
            else None
        ),
        "grade3_hit": (
            float(bool(grade3_hits))
            if grade3
            else None
        ),
        "grade3_source_ids": grade3_hits,
    }


def overlap_metrics(
    *,
    left_keys: Sequence[CandidateKey],
    right_keys: Sequence[CandidateKey],
    cutoff: int,
) -> dict[str, Any]:
    """Measure overlap and Jaccard similarity between two routes."""

    left = prefix_key_set(
        left_keys,
        cutoff,
    )
    right = prefix_key_set(
        right_keys,
        cutoff,
    )

    intersection = left & right
    union = left | right

    return {
        "left_candidate_count": len(left),
        "right_candidate_count": len(right),
        "intersection_count": len(intersection),
        "union_count": len(union),
        "jaccard": (
            round_optional(
                len(intersection) / len(union)
            )
            if union
            else None
        ),
    }


def marginal_metrics(
    *,
    additional_route: str,
    baseline_routes: Sequence[str],
    route_keys: Mapping[
        str,
        Sequence[CandidateKey],
    ],
    case: EvaluationCase,
    cutoff: int,
) -> dict[str, Any]:
    """Measure candidates uniquely contributed by one route."""

    additional = prefix_key_set(
        route_keys[additional_route],
        cutoff,
    )

    baseline: set[CandidateKey] = set()

    for route_name in baseline_routes:
        baseline.update(
            prefix_key_set(
                route_keys[route_name],
                cutoff,
            )
        )

    marginal_keys = additional - baseline

    marginal_source_ids = {
        source_id
        for _, source_id in marginal_keys
    }

    relevant = relevant_source_ids(case)
    grade3 = relevant_source_ids(
        case,
        exact_grade=3,
    )

    relevant_hits = sorted(
        marginal_source_ids & relevant
    )
    grade3_hits = sorted(
        marginal_source_ids & grade3
    )

    return {
        "candidate_count": len(marginal_keys),
        "relevant_hit_count": len(
            relevant_hits
        ),
        "relevant_source_ids": relevant_hits,
        "grade3_hit_count": len(
            grade3_hits
        ),
        "grade3_source_ids": grade3_hits,
    }


def analyze_case_routes(
    *,
    case: EvaluationCase,
    route_candidates: Mapping[
        str,
        Sequence[Mapping[str, Any]],
    ],
    cutoffs: Sequence[int],
    latency_ms: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build route, overlap, and marginal metrics for one case."""

    route_keys = {
        route_name: ordered_candidate_keys(
            route_candidates[route_name]
        )
        for route_name in ROUTES
    }

    route_coverage: dict[
        str,
        dict[str, Any],
    ] = {}

    for route_name in ROUTES:
        route_coverage[route_name] = {
            str(cutoff): coverage_metrics(
                route_names=(route_name,),
                route_keys=route_keys,
                case=case,
                cutoff=cutoff,
            )
            for cutoff in cutoffs
        }

    combination_coverage: dict[
        str,
        dict[str, Any],
    ] = {}

    for combination_name, route_names in (
        COMBINATIONS.items()
    ):
        combination_coverage[
            combination_name
        ] = {
            str(cutoff): coverage_metrics(
                route_names=route_names,
                route_keys=route_keys,
                case=case,
                cutoff=cutoff,
            )
            for cutoff in cutoffs
        }

    overlaps: dict[str, dict[str, Any]] = {}

    for cutoff in cutoffs:
        cutoff_key = str(cutoff)
        overlaps[cutoff_key] = {}

        for pair_name, (
            left_route,
            right_route,
        ) in OVERLAP_PAIRS.items():
            overlaps[cutoff_key][
                pair_name
            ] = overlap_metrics(
                left_keys=route_keys[left_route],
                right_keys=route_keys[right_route],
                cutoff=cutoff,
            )

    marginals: dict[str, dict[str, Any]] = {}

    for cutoff in cutoffs:
        cutoff_key = str(cutoff)
        marginals[cutoff_key] = {}

        for marginal_name, (
            additional_route,
            baseline_routes,
        ) in MARGINAL_CONFIGURATIONS.items():
            marginals[cutoff_key][
                marginal_name
            ] = marginal_metrics(
                additional_route=additional_route,
                baseline_routes=baseline_routes,
                route_keys=route_keys,
                case=case,
                cutoff=cutoff,
            )

    return {
        "case_id": case.case_id,
        "query": case.query,
        "filters": case_filter_configuration(
            case
        ),
        "relevant_source_ids": sorted(
            relevant_source_ids(case)
        ),
        "grade3_source_ids": sorted(
            relevant_source_ids(
                case,
                exact_grade=3,
            )
        ),
        "route_returned_count": {
            route_name: len(
                route_keys[route_name]
            )
            for route_name in ROUTES
        },
        "route_business_keys": {
            route_name: [
                {
                    "source": source,
                    "source_id": source_id,
                }
                for source, source_id in (
                    route_keys[route_name]
                )
            ]
            for route_name in ROUTES
        },
        "route_source_ids": {
            route_name: [
                source_id
                for _, source_id in (
                    route_keys[route_name]
                )
            ]
            for route_name in ROUTES
        },
        "coverage": {
            "routes": route_coverage,
            "combinations": (
                combination_coverage
            ),
        },
        "overlaps": overlaps,
        "marginals": marginals,
        "latency_ms": {
            key: round(float(value), 3)
            for key, value in (
                latency_ms or {}
            ).items()
        },
    }


def summarize_coverage_group(
    *,
    case_results: Sequence[dict[str, Any]],
    group_name: str,
    member_names: Sequence[str],
    cutoffs: Sequence[int],
) -> dict[str, Any]:
    """Summarize route or route-combination coverage."""

    summary: dict[str, Any] = {}

    for member_name in member_names:
        summary[member_name] = {}

        for cutoff in cutoffs:
            cutoff_key = str(cutoff)

            rows = [
                result["coverage"][
                    group_name
                ][member_name][cutoff_key]
                for result in case_results
            ]

            summary[member_name][
                cutoff_key
            ] = {
                "macro_recall": round_optional(
                    mean_defined(
                        [
                            row["recall"]
                            for row in rows
                        ]
                    )
                ),
                "grade3_hit_rate": round_optional(
                    mean_defined(
                        [
                            row["grade3_hit"]
                            for row in rows
                        ]
                    )
                ),
                "mean_candidate_count": (
                    round(
                        statistics.fmean(
                            [
                                row[
                                    "candidate_count"
                                ]
                                for row in rows
                            ]
                        ),
                        3,
                    )
                    if rows
                    else None
                ),
                "relevant_hit_occurrences": sum(
                    int(
                        row[
                            "relevant_hit_count"
                        ]
                    )
                    for row in rows
                ),
            }

    return summary


def summarize_case_results(
    case_results: Sequence[dict[str, Any]],
    cutoffs: Sequence[int],
) -> dict[str, Any]:
    """Build the aggregate route-coverage report."""

    overlap_summary: dict[str, Any] = {}
    marginal_summary: dict[str, Any] = {}

    for cutoff in cutoffs:
        cutoff_key = str(cutoff)
        overlap_summary[cutoff_key] = {}
        marginal_summary[cutoff_key] = {}

        for pair_name in OVERLAP_PAIRS:
            rows = [
                result["overlaps"][
                    cutoff_key
                ][pair_name]
                for result in case_results
            ]

            overlap_summary[
                cutoff_key
            ][pair_name] = {
                "mean_intersection_count": (
                    round(
                        statistics.fmean(
                            [
                                row[
                                    "intersection_count"
                                ]
                                for row in rows
                            ]
                        ),
                        3,
                    )
                    if rows
                    else None
                ),
                "mean_union_count": (
                    round(
                        statistics.fmean(
                            [
                                row["union_count"]
                                for row in rows
                            ]
                        ),
                        3,
                    )
                    if rows
                    else None
                ),
                "mean_jaccard": round_optional(
                    mean_defined(
                        [
                            row["jaccard"]
                            for row in rows
                        ]
                    )
                ),
            }

        for marginal_name in (
            MARGINAL_CONFIGURATIONS
        ):
            rows = [
                result["marginals"][
                    cutoff_key
                ][marginal_name]
                for result in case_results
            ]

            relevant_source_ids = sorted(
                {
                    source_id
                    for row in rows
                    for source_id in row[
                        "relevant_source_ids"
                    ]
                }
            )
            grade3_source_ids = sorted(
                {
                    source_id
                    for row in rows
                    for source_id in row[
                        "grade3_source_ids"
                    ]
                }
            )

            marginal_summary[
                cutoff_key
            ][marginal_name] = {
                "mean_candidate_count": (
                    round(
                        statistics.fmean(
                            [
                                row[
                                    "candidate_count"
                                ]
                                for row in rows
                            ]
                        ),
                        3,
                    )
                    if rows
                    else None
                ),
                "new_relevant_occurrences": sum(
                    int(
                        row[
                            "relevant_hit_count"
                        ]
                    )
                    for row in rows
                ),
                "unique_new_relevant_count": len(
                    relevant_source_ids
                ),
                "unique_new_relevant_source_ids": (
                    relevant_source_ids
                ),
                "new_grade3_occurrences": sum(
                    int(
                        row[
                            "grade3_hit_count"
                        ]
                    )
                    for row in rows
                ),
                "unique_new_grade3_count": len(
                    grade3_source_ids
                ),
                "unique_new_grade3_source_ids": (
                    grade3_source_ids
                ),
            }

    latency_names = sorted(
        {
            latency_name
            for result in case_results
            for latency_name in result[
                "latency_ms"
            ]
        }
    )

    latency = {
        latency_name: latency_summary(
            [
                float(
                    result["latency_ms"][
                        latency_name
                    ]
                )
                for result in case_results
                if latency_name
                in result["latency_ms"]
            ]
        )
        for latency_name in latency_names
    }

    return {
        "case_count": len(case_results),
        "routes": summarize_coverage_group(
            case_results=case_results,
            group_name="routes",
            member_names=ROUTES,
            cutoffs=cutoffs,
        ),
        "combinations": (
            summarize_coverage_group(
                case_results=case_results,
                group_name="combinations",
                member_names=tuple(
                    COMBINATIONS
                ),
                cutoffs=cutoffs,
            )
        ),
        "overlaps": overlap_summary,
        "marginals": marginal_summary,
        "latency_ms": latency,
    }


async def retrieve_freshness_candidates(
    repository: PostRepository,
    *,
    case: EvaluationCase,
    limit: int,
) -> list[dict[str, Any]]:
    """Run the production Freshness candidate route."""

    bounding_box = bounding_box_for_case(
        case
    )

    rows = await repository.search_candidates(
        category=category_value(case),
        visible_statuses=case.visible_statuses,
        city=case.city,
        district=case.district,
        min_latitude=bounding_box[
            "min_latitude"
        ],
        max_latitude=bounding_box[
            "max_latitude"
        ],
        min_longitude=bounding_box[
            "min_longitude"
        ],
        max_longitude=bounding_box[
            "max_longitude"
        ],
        limit=limit,
    )

    if (
        case.latitude is None
        or case.longitude is None
        or case.radius_km is None
    ):
        return list(rows)

    filtered: list[dict[str, Any]] = []

    for row in rows:
        latitude = row.get("latitude")
        longitude = row.get("longitude")

        if latitude is None or longitude is None:
            continue

        distance_km = haversine_km(
            case.latitude,
            case.longitude,
            float(latitude),
            float(longitude),
        )

        if distance_km > case.radius_km:
            continue

        normalized = dict(row)
        normalized["distance_km"] = (
            distance_km
        )
        filtered.append(normalized)

    return filtered


async def retrieve_lexical_candidates(
    connection: Any,
    *,
    case: EvaluationCase,
    limit: int,
    overfetch_factor: float,
) -> list[dict[str, Any]]:
    """Run business-filtered PostgreSQL Lexical Recall."""

    bounding_box = bounding_box_for_case(
        case
    )

    return list(
        await lexical_search_filtered(
            connection,
            query=case.query,
            category=category_value(case),
            visible_statuses=(
                case.visible_statuses
            ),
            city=case.city,
            district=case.district,
            min_latitude=bounding_box[
                "min_latitude"
            ],
            max_latitude=bounding_box[
                "max_latitude"
            ],
            min_longitude=bounding_box[
                "min_longitude"
            ],
            max_longitude=bounding_box[
                "max_longitude"
            ],
            latitude=case.latitude,
            longitude=case.longitude,
            radius_km=case.radius_km,
            overfetch_factor=overfetch_factor,
            limit=limit,
        )
    )


async def retrieve_semantic_candidates(
    connection: Any,
    *,
    case: EvaluationCase,
    query_embedding: Any,
    limit: int,
    ef_search: int,
    iterative_scan: str,
    radius_overfetch_factor: float,
) -> list[dict[str, Any]]:
    """Run business-filtered PostgreSQL Semantic Recall."""

    bounding_box = bounding_box_for_case(
        case
    )

    return list(
        await semantic_search_filtered(
            connection,
            query_embedding=query_embedding,
            category=category_value(case),
            visible_statuses=(
                case.visible_statuses
            ),
            city=case.city,
            district=case.district,
            min_latitude=bounding_box[
                "min_latitude"
            ],
            max_latitude=bounding_box[
                "max_latitude"
            ],
            min_longitude=bounding_box[
                "min_longitude"
            ],
            max_longitude=bounding_box[
                "max_longitude"
            ],
            latitude=case.latitude,
            longitude=case.longitude,
            radius_km=case.radius_km,
            radius_overfetch_factor=(
                radius_overfetch_factor
            ),
            limit=limit,
            ef_search=ef_search,
            iterative_scan=iterative_scan,
        )
    )


async def evaluate_cases(
    *,
    cases: Sequence[EvaluationCase],
    model: Any,
    cutoffs: Sequence[int],
    limit: int,
    ef_search: int,
    iterative_scan: str,
    lexical_overfetch_factor: float,
    radius_overfetch_factor: float,
) -> list[dict[str, Any]]:
    """Evaluate all three recall routes for every case."""

    case_results: list[dict[str, Any]] = []

    async with await connect_postgres() as connection:
        for index, case in enumerate(
            cases,
            start=1,
        ):
            freshness_started = (
                time.perf_counter()
            )
            freshness_candidates = (
                await retrieve_freshness_candidates(
                    post_repository,
                    case=case,
                    limit=limit,
                )
            )
            freshness_latency_ms = (
                time.perf_counter()
                - freshness_started
            ) * 1000.0

            lexical_started = time.perf_counter()
            lexical_candidates = (
                await retrieve_lexical_candidates(
                    connection,
                    case=case,
                    limit=limit,
                    overfetch_factor=(
                        lexical_overfetch_factor
                    ),
                )
            )
            lexical_latency_ms = (
                time.perf_counter()
                - lexical_started
            ) * 1000.0

            semantic_started = (
                time.perf_counter()
            )

            encoding_started = (
                time.perf_counter()
            )
            query_embedding = (
                await asyncio.to_thread(
                    encode_query,
                    model,
                    case.query,
                )
            )
            encoding_latency_ms = (
                time.perf_counter()
                - encoding_started
            ) * 1000.0

            semantic_database_started = (
                time.perf_counter()
            )
            semantic_candidates = (
                await retrieve_semantic_candidates(
                    connection,
                    case=case,
                    query_embedding=(
                        query_embedding
                    ),
                    limit=limit,
                    ef_search=ef_search,
                    iterative_scan=iterative_scan,
                    radius_overfetch_factor=(
                        radius_overfetch_factor
                    ),
                )
            )
            semantic_database_latency_ms = (
                time.perf_counter()
                - semantic_database_started
            ) * 1000.0

            semantic_end_to_end_latency_ms = (
                time.perf_counter()
                - semantic_started
            ) * 1000.0

            result = analyze_case_routes(
                case=case,
                route_candidates={
                    "freshness": (
                        freshness_candidates
                    ),
                    "lexical": lexical_candidates,
                    "semantic": (
                        semantic_candidates
                    ),
                },
                cutoffs=cutoffs,
                latency_ms={
                    "freshness": (
                        freshness_latency_ms
                    ),
                    "lexical": lexical_latency_ms,
                    "semantic_encoding": (
                        encoding_latency_ms
                    ),
                    "semantic_database": (
                        semantic_database_latency_ms
                    ),
                    "semantic_end_to_end": (
                        semantic_end_to_end_latency_ms
                    ),
                },
            )
            case_results.append(result)

            maximum_cutoff = str(
                max(cutoffs)
            )
            union_recall = (
                result["coverage"]["combinations"]
                ["freshness_lexical_semantic"]
                [maximum_cutoff]["recall"]
            )

            print(
                f"[{index}/{len(cases)}] "
                f"{case.case_id} "
                f"| freshness="
                f"{len(freshness_candidates)} "
                f"| lexical="
                f"{len(lexical_candidates)} "
                f"| semantic="
                f"{len(semantic_candidates)} "
                f"| union_recall@"
                f"{maximum_cutoff}="
                f"{union_recall}"
            )

    return case_results


def positive_int(value: str) -> int:
    """Parse a positive command-line integer."""

    parsed = int(value)

    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return parsed


def positive_float(value: str) -> float:
    """Parse a positive command-line float."""

    parsed = float(value)

    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return parsed


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate Freshness, Lexical, and "
            "Semantic candidate coverage."
        )
    )

    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL_PATH,
    )
    parser.add_argument(
        "--device",
        choices=(
            "auto",
            "cpu",
            "cuda",
        ),
        default="auto",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_LIMIT,
    )
    parser.add_argument(
        "--cutoffs",
        type=positive_int,
        nargs="+",
        default=list(DEFAULT_CUTOFFS),
    )
    parser.add_argument(
        "--ef-search",
        type=positive_int,
        default=DEFAULT_EF_SEARCH,
    )
    parser.add_argument(
        "--iterative-scan",
        choices=(
            "off",
            "strict_order",
            "relaxed_order",
        ),
        default=DEFAULT_ITERATIVE_SCAN,
    )
    parser.add_argument(
        "--lexical-overfetch-factor",
        type=positive_float,
        default=(
            DEFAULT_LEXICAL_OVERFETCH_FACTOR
        ),
    )
    parser.add_argument(
        "--radius-overfetch-factor",
        type=positive_float,
        default=(
            DEFAULT_RADIUS_OVERFETCH_FACTOR
        ),
    )

    return parser.parse_args()


async def async_main(
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run the complete route-coverage evaluation."""

    if args.limit > MAX_RECALL_LIMIT:
        raise ValueError(
            f"limit must not exceed "
            f"{MAX_RECALL_LIMIT}"
        )

    if args.ef_search > MAX_EF_SEARCH:
        raise ValueError(
            f"ef_search must not exceed "
            f"{MAX_EF_SEARCH}"
        )

    cutoffs = normalize_positive_values(
        args.cutoffs,
        name="cutoffs",
        maximum=args.limit,
    )

    cases = load_cases(args.cases)

    device = resolve_device(args.device)
    model = await asyncio.to_thread(
        load_model,
        args.model_path,
        device=device,
    )

    case_results = await evaluate_cases(
        cases=cases,
        model=model,
        cutoffs=cutoffs,
        limit=args.limit,
        ef_search=args.ef_search,
        iterative_scan=args.iterative_scan,
        lexical_overfetch_factor=(
            args.lexical_overfetch_factor
        ),
        radius_overfetch_factor=(
            args.radius_overfetch_factor
        ),
    )

    summary = summarize_case_results(
        case_results,
        cutoffs,
    )

    report = {
        "generated_at": datetime.now(
            UTC
        ).isoformat(),
        "configuration": {
            "cases": str(args.cases),
            "model_path": str(args.model_path),
            "device": device,
            "limit": args.limit,
            "cutoffs": cutoffs,
            "ef_search": args.ef_search,
            "iterative_scan": (
                args.iterative_scan
            ),
            "lexical_overfetch_factor": (
                args.lexical_overfetch_factor
            ),
            "radius_overfetch_factor": (
                args.radius_overfetch_factor
            ),
            "combination_semantics": (
                "For cutoff K, combined coverage "
                "is the set union of every selected "
                "route's top K candidates."
            ),
        },
        "summary": summary,
        "cases": case_results,
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\n========== route coverage =========="
    )

    for cutoff in cutoffs:
        cutoff_key = str(cutoff)

        print(f"\ncutoff={cutoff}")

        for route_name in ROUTES:
            metrics = summary["routes"][
                route_name
            ][cutoff_key]

            print(
                f"{route_name}: "
                f"recall="
                f"{metrics['macro_recall']} "
                f"| grade3_hit="
                f"{metrics['grade3_hit_rate']} "
                f"| candidates="
                f"{metrics['mean_candidate_count']}"
            )

        union_metrics = summary[
            "combinations"
        ]["freshness_lexical_semantic"][
            cutoff_key
        ]

        print(
            "freshness+lexical+semantic: "
            f"recall="
            f"{union_metrics['macro_recall']} "
            f"| grade3_hit="
            f"{union_metrics['grade3_hit_rate']} "
            f"| candidates="
            f"{union_metrics['mean_candidate_count']}"
        )

        marginal = summary["marginals"][
            cutoff_key
        ]

        lexical_marginal = (
            marginal["lexical_over_freshness"]
        )

        print(
            "lexical over freshness: "
            f"new_relevant="
            f"{lexical_marginal['new_relevant_occurrences']} "
            f"| unique="
            f"{lexical_marginal['unique_new_relevant_count']}"
        )

        semantic_marginal = (
            marginal[
                "semantic_over_freshness_lexical"
            ]
        )

        print(
            "semantic over freshness+lexical: "
            f"new_relevant="
            f"{semantic_marginal['new_relevant_occurrences']} "
            f"| unique="
            f"{semantic_marginal['unique_new_relevant_count']}"
        )

    print(
        f"\nreport: {args.output}"
    )

    return report


def main() -> None:
    """CLI entry point."""

    asyncio.run(
        async_main(
            parse_args()
        )
    )


if __name__ == "__main__":
    main()
