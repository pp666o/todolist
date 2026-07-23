#!/usr/bin/env python3
"""Evaluate fixed-budget allocations across recall routes."""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROUTES = (
    "freshness",
    "lexical",
    "semantic",
)

DEFAULT_INPUT_PATH = Path(
    "data/evaluation/results/recall_route_coverage.json"
)
DEFAULT_OUTPUT_PATH = Path(
    "data/evaluation/results/recall_budget_allocations.json"
)
DEFAULT_TOTAL_BUDGET = 200
DEFAULT_ALLOCATIONS = (
    "100,50,50",
    "80,80,40",
    "60,80,60",
    "40,80,80",
    "0,100,100",
)

CandidateKey = tuple[str, str]


def parse_allocation(
    value: str,
    *,
    total_budget: int,
) -> dict[str, int]:
    """Parse Freshness, Lexical, Semantic route quotas."""

    parts = [
        part.strip()
        for part in value.split(",")
    ]

    if len(parts) != len(ROUTES):
        raise ValueError(
            "allocation must contain exactly "
            "three comma-separated integers"
        )

    try:
        quotas = [
            int(part)
            for part in parts
        ]
    except ValueError as exc:
        raise ValueError(
            "allocation values must be integers"
        ) from exc

    if any(quota < 0 for quota in quotas):
        raise ValueError(
            "allocation values must not be negative"
        )

    if sum(quotas) != total_budget:
        raise ValueError(
            "allocation values must sum to "
            f"{total_budget}"
        )

    if not any(quotas):
        raise ValueError(
            "at least one route quota must be positive"
        )

    return dict(
        zip(
            ROUTES,
            quotas,
            strict=True,
        )
    )


def allocation_name(
    allocation: Mapping[str, int],
) -> str:
    """Return a compact stable allocation name."""

    return (
        f"f{allocation['freshness']}"
        f"_l{allocation['lexical']}"
        f"_s{allocation['semantic']}"
    )


def normalize_route_keys(
    case_result: Mapping[str, Any],
) -> dict[str, list[CandidateKey]]:
    """Read ordered business keys from one coverage case."""

    raw_routes = case_result.get(
        "route_business_keys"
    )

    if not isinstance(raw_routes, Mapping):
        raise ValueError(
            "coverage report does not contain "
            "route_business_keys; rerun the "
            "route coverage evaluator"
        )

    normalized: dict[
        str,
        list[CandidateKey],
    ] = {}

    for route in ROUTES:
        raw_candidates = raw_routes.get(route)

        if not isinstance(
            raw_candidates,
            Sequence,
        ) or isinstance(
            raw_candidates,
            (str, bytes),
        ):
            raise ValueError(
                f"route {route!r} candidates "
                "must be a sequence"
            )

        keys: list[CandidateKey] = []
        seen: set[CandidateKey] = set()

        for raw_candidate in raw_candidates:
            if not isinstance(
                raw_candidate,
                Mapping,
            ):
                raise ValueError(
                    "route candidate must be "
                    "an object"
                )

            source = str(
                raw_candidate.get("source")
                or ""
            ).strip()
            source_id = str(
                raw_candidate.get("source_id")
                or ""
            ).strip()

            if not source or not source_id:
                raise ValueError(
                    "route candidate must contain "
                    "source and source_id"
                )

            key = source, source_id

            if key in seen:
                continue

            seen.add(key)
            keys.append(key)

        normalized[route] = keys

    return normalized


def weighted_rank_merge(
    *,
    route_keys: Mapping[
        str,
        Sequence[CandidateKey],
    ],
    allocation: Mapping[str, int],
    total_budget: int,
) -> dict[str, Any]:
    """Merge route rankings under one fixed total budget.

    A candidate at rank r from a route with quota q receives
    normalized priority r / q. Routes with quota zero are disabled.
    Duplicate business keys are skipped, and deeper candidates from
    active routes backfill the resulting empty slots.
    """

    if total_budget < 1:
        raise ValueError(
            "total_budget must be positive"
        )

    unknown_routes = (
        set(allocation) - set(ROUTES)
    )

    if unknown_routes:
        raise ValueError(
            "unsupported allocation routes: "
            f"{sorted(unknown_routes)}"
        )

    if sum(
        int(allocation.get(route, 0))
        for route in ROUTES
    ) != total_budget:
        raise ValueError(
            "allocation must sum to total_budget"
        )

    ranked_entries: list[
        tuple[
            float,
            int,
            int,
            str,
            str,
            str,
        ]
    ] = []

    for route_index, route in enumerate(
        ROUTES
    ):
        quota = int(
            allocation.get(route, 0)
        )

        if quota < 0:
            raise ValueError(
                "route quota must not be negative"
            )

        if quota == 0:
            continue

        for rank, key in enumerate(
            route_keys.get(route, ()),
            start=1,
        ):
            source, source_id = key

            ranked_entries.append(
                (
                    rank / quota,
                    route_index,
                    rank,
                    str(source),
                    str(source_id),
                    route,
                )
            )

    ranked_entries.sort()

    selected: list[dict[str, Any]] = []
    seen: set[CandidateKey] = set()

    contribution_count = {
        route: 0
        for route in ROUTES
    }

    for (
        normalized_rank,
        _,
        route_rank,
        source,
        source_id,
        route,
    ) in ranked_entries:
        key = source, source_id

        if key in seen:
            continue

        seen.add(key)
        contribution_count[route] += 1

        selected.append(
            {
                "source": source,
                "source_id": source_id,
                "selected_from": route,
                "route_rank": route_rank,
                "normalized_rank": round(
                    normalized_rank,
                    8,
                ),
            }
        )

        if len(selected) >= total_budget:
            break

    return {
        "candidate_count": len(selected),
        "fill_rate": (
            len(selected) / total_budget
        ),
        "contribution_count": (
            contribution_count
        ),
        "candidates": selected,
    }


def evaluate_case_allocation(
    *,
    case_result: Mapping[str, Any],
    allocation: Mapping[str, int],
    total_budget: int,
) -> dict[str, Any]:
    """Evaluate one allocation for one judged query."""

    route_keys = normalize_route_keys(
        case_result
    )

    merged = weighted_rank_merge(
        route_keys=route_keys,
        allocation=allocation,
        total_budget=total_budget,
    )

    relevant = {
        str(source_id)
        for source_id in case_result.get(
            "relevant_source_ids",
            (),
        )
    }
    grade3 = {
        str(source_id)
        for source_id in case_result.get(
            "grade3_source_ids",
            (),
        )
    }

    selected_source_ids = {
        str(candidate["source_id"])
        for candidate in merged["candidates"]
    }

    relevant_hits = sorted(
        selected_source_ids & relevant
    )
    grade3_hits = sorted(
        selected_source_ids & grade3
    )

    return {
        "case_id": str(
            case_result["case_id"]
        ),
        "query": str(
            case_result["query"]
        ),
        "candidate_count": merged[
            "candidate_count"
        ],
        "fill_rate": round(
            float(merged["fill_rate"]),
            6,
        ),
        "contribution_count": merged[
            "contribution_count"
        ],
        "relevant_hit_count": len(
            relevant_hits
        ),
        "relevant_source_ids": (
            relevant_hits
        ),
        "recall": (
            round(
                len(relevant_hits)
                / len(relevant),
                6,
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


def mean_defined(
    values: Sequence[float | None],
) -> float | None:
    """Return the mean of defined values."""

    defined = [
        float(value)
        for value in values
        if value is not None
    ]

    if not defined:
        return None

    return statistics.fmean(defined)


def summarize_allocation(
    case_results: Sequence[
        Mapping[str, Any]
    ],
) -> dict[str, Any]:
    """Build aggregate metrics for one allocation."""

    relevant_source_ids = sorted(
        {
            source_id
            for result in case_results
            for source_id in result[
                "relevant_source_ids"
            ]
        }
    )
    grade3_source_ids = sorted(
        {
            source_id
            for result in case_results
            for source_id in result[
                "grade3_source_ids"
            ]
        }
    )

    contribution_mean = {
        route: (
            round(
                statistics.fmean(
                    [
                        int(
                            result[
                                "contribution_count"
                            ][route]
                        )
                        for result in case_results
                    ]
                ),
                3,
            )
            if case_results
            else None
        )
        for route in ROUTES
    }

    return {
        "case_count": len(case_results),
        "macro_recall": (
            round(
                mean_defined(
                    [
                        result["recall"]
                        for result in (
                            case_results
                        )
                    ]
                ),
                6,
            )
            if case_results
            else None
        ),
        "grade3_hit_rate": (
            round(
                mean_defined(
                    [
                        result["grade3_hit"]
                        for result in (
                            case_results
                        )
                    ]
                ),
                6,
            )
            if case_results
            else None
        ),
        "mean_candidate_count": (
            round(
                statistics.fmean(
                    [
                        int(
                            result[
                                "candidate_count"
                            ]
                        )
                        for result in case_results
                    ]
                ),
                3,
            )
            if case_results
            else None
        ),
        "mean_fill_rate": (
            round(
                statistics.fmean(
                    [
                        float(
                            result["fill_rate"]
                        )
                        for result in case_results
                    ]
                ),
                6,
            )
            if case_results
            else None
        ),
        "underfilled_case_count": sum(
            1
            for result in case_results
            if float(result["fill_rate"]) < 1.0
        ),
        "relevant_hit_occurrences": sum(
            int(result["relevant_hit_count"])
            for result in case_results
        ),
        "unique_relevant_hit_count": len(
            relevant_source_ids
        ),
        "unique_relevant_source_ids": (
            relevant_source_ids
        ),
        "grade3_hit_occurrences": sum(
            len(result["grade3_source_ids"])
            for result in case_results
        ),
        "unique_grade3_hit_count": len(
            grade3_source_ids
        ),
        "unique_grade3_source_ids": (
            grade3_source_ids
        ),
        "mean_contribution_count": (
            contribution_mean
        ),
    }


def positive_int(value: str) -> int:
    parsed = int(value)

    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "value must be positive"
        )

    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate fixed-budget recall "
            "route allocations."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
    )
    parser.add_argument(
        "--total-budget",
        type=positive_int,
        default=DEFAULT_TOTAL_BUDGET,
    )
    parser.add_argument(
        "--allocations",
        nargs="+",
        default=list(
            DEFAULT_ALLOCATIONS
        ),
        metavar="FRESHNESS,LEXICAL,SEMANTIC",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise FileNotFoundError(
            f"coverage report not found: "
            f"{args.input}"
        )

    coverage_report = json.loads(
        args.input.read_text(
            encoding="utf-8"
        )
    )

    raw_cases = coverage_report.get(
        "cases"
    )

    if not isinstance(raw_cases, list):
        raise ValueError(
            "coverage report cases must be a list"
        )

    allocation_reports: dict[
        str,
        Any,
    ] = {}

    for raw_allocation in args.allocations:
        allocation = parse_allocation(
            raw_allocation,
            total_budget=args.total_budget,
        )
        name = allocation_name(
            allocation
        )

        case_results = [
            evaluate_case_allocation(
                case_result=case_result,
                allocation=allocation,
                total_budget=args.total_budget,
            )
            for case_result in raw_cases
        ]

        allocation_reports[name] = {
            "allocation": allocation,
            "summary": summarize_allocation(
                case_results
            ),
            "cases": case_results,
        }

    report = {
        "generated_at": datetime.now(
            UTC
        ).isoformat(),
        "configuration": {
            "input": str(args.input),
            "total_budget": (
                args.total_budget
            ),
            "merge_strategy": (
                "weighted normalized route rank; "
                "priority=route_rank/route_quota; "
                "duplicate business keys are skipped; "
                "active route tails backfill empty slots"
            ),
        },
        "allocations": allocation_reports,
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
        "========== fixed budget allocations =========="
    )

    for name, allocation_report in (
        allocation_reports.items()
    ):
        summary = allocation_report[
            "summary"
        ]

        print(
            name,
            "| recall=",
            summary["macro_recall"],
            "| grade3_hit=",
            summary["grade3_hit_rate"],
            "| candidates=",
            summary["mean_candidate_count"],
            "| fill_rate=",
            summary["mean_fill_rate"],
            "| contribution=",
            summary[
                "mean_contribution_count"
            ],
        )

    print(f"\nreport: {args.output}")


if __name__ == "__main__":
    main()
