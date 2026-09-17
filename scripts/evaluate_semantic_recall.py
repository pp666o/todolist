#!/usr/bin/env python3
"""Evaluate global or business-filtered semantic recall through PostgreSQL HNSW."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.infrastructure.postgres import connect_postgres
from app.infrastructure.search.embedding_runtime import (
    DEFAULT_MODEL_PATH,
    encode_query,
    load_model,
    resolve_device,
)
from app.search.semantic_retrieval import (
    MAX_EF_SEARCH,
    MAX_RECALL_LIMIT,
    semantic_search_filtered,
    semantic_search_global,
)
from scripts.evaluate_post_search import (
    EvaluationCase,
    load_cases,
    percentile,
    recall_at_k,
    reciprocal_rank_at_k,
    round_optional,
)


DEFAULT_CASES_PATH = Path(
    "data/evaluation/post_search_rewrite_cases.jsonl"
)
DEFAULT_OUTPUT_PATH = Path(
    "data/evaluation/results/semantic_global.json"
)
DEFAULT_FILTERED_OUTPUT_PATH = Path(
    "data/evaluation/results/semantic_filtered.json"
)
DEFAULT_CUTOFFS = (20, 50, 100, 200, 500)
DEFAULT_EF_SEARCH_VALUES = (40, 100, 200)
# Filtered HNSW evaluation must return a complete candidate set.
# iterative_scan=off may return fewer rows after SQL filtering.
DEFAULT_ITERATIVE_SCAN = "strict_order"
DEFAULT_RADIUS_OVERFETCH_FACTOR = 2.0


def normalize_positive_values(
    values: Sequence[int],
    *,
    name: str,
    maximum: int,
) -> list[int]:
    """Validate, deduplicate, and sort positive integer settings."""

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
    """Build a compact latency distribution summary."""

    normalized = [
        float(value)
        for value in values
    ]

    return {
        "count": len(normalized),
        "mean": (
            round(statistics.fmean(normalized), 3)
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


def grade3_hit_at_k(
    returned_source_ids: Sequence[str],
    relevance: dict[str, int],
    k: int,
) -> float | None:
    """Return whether any grade-3 anchor appears in the top K."""

    anchors = {
        source_id
        for source_id, grade in relevance.items()
        if grade == 3
    }

    if not anchors:
        return None

    return float(
        bool(
            anchors.intersection(
                returned_source_ids[:k]
            )
        )
    )


def build_judged_ranks(
    returned_source_ids: Sequence[str],
    relevance: dict[str, int],
    *,
    minimum_grade: int,
    exact_grade: int | None = None,
) -> list[dict[str, Any]]:
    """Return ranks for judged posts, including missing items."""

    rank_by_source_id = {
        source_id: rank
        for rank, source_id in enumerate(
            returned_source_ids,
            start=1,
        )
    }

    rows: list[dict[str, Any]] = []

    for source_id, grade in relevance.items():
        if exact_grade is not None:
            if grade != exact_grade:
                continue
        elif grade < minimum_grade:
            continue

        rows.append(
            {
                "source_id": source_id,
                "grade": grade,
                "rank": rank_by_source_id.get(
                    source_id
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["rank"] is None,
            (
                int(row["rank"])
                if row["rank"] is not None
                else 10**9
            ),
            -int(row["grade"]),
            str(row["source_id"]),
        ),
    )


def build_cutoff_metrics(
    returned_source_ids: Sequence[str],
    case: EvaluationCase,
    cutoffs: Sequence[int],
) -> dict[str, dict[str, Any]]:
    """Calculate metrics only for fully returned cutoffs.

    pgvector HNSW may return fewer rows than the SQL LIMIT when
    hnsw.ef_search is smaller than the requested recall limit.
    Metrics for an incomplete cutoff must not be reported as if the
    full top-K ranking had been evaluated.
    """

    returned_count = len(
        returned_source_ids
    )
    metrics: dict[
        str,
        dict[str, Any],
    ] = {}

    for cutoff in cutoffs:
        complete = returned_count >= cutoff

        metrics[str(cutoff)] = {
            "complete": complete,
            "returned_count": returned_count,
            "recall": (
                round_optional(
                    recall_at_k(
                        returned_source_ids,
                        case.relevance,
                        cutoff,
                        case.binary_relevance_threshold,
                    )
                )
                if complete
                else None
            ),
            "mrr": (
                round_optional(
                    reciprocal_rank_at_k(
                        returned_source_ids,
                        case.relevance,
                        cutoff,
                        case.binary_relevance_threshold,
                    )
                )
                if complete
                else None
            ),
            "grade3_hit": (
                round_optional(
                    grade3_hit_at_k(
                        returned_source_ids,
                        case.relevance,
                        cutoff,
                    )
                )
                if complete
                else None
            ),
        }

    return metrics

def build_experiment_summary(
    case_results: Sequence[dict[str, Any]],
    cutoffs: Sequence[int],
) -> dict[str, Any]:
    """Build macro metrics and latency summaries for one ef_search."""

    cutoff_summary: dict[str, dict[str, Any]] = {}

    for cutoff in cutoffs:
        cutoff_key = str(cutoff)

        cutoff_metrics = [
            result["metrics"][cutoff_key]
            for result in case_results
        ]

        complete_metrics = [
            metric
            for metric in cutoff_metrics
            if metric["complete"]
        ]

        cutoff_summary[cutoff_key] = {
            "complete_case_count": len(
                complete_metrics
            ),
            "incomplete_case_count": (
                len(cutoff_metrics)
                - len(complete_metrics)
            ),
            "macro_recall": round_optional(
                mean_defined(
                    [
                        metric["recall"]
                        for metric in complete_metrics
                    ]
                )
            ),
            "mrr": round_optional(
                mean_defined(
                    [
                        metric["mrr"]
                        for metric in complete_metrics
                    ]
                )
            ),
            "grade3_hit_rate": round_optional(
                mean_defined(
                    [
                        metric["grade3_hit"]
                        for metric in complete_metrics
                    ]
                )
            ),
        }

    returned_counts: list[int] = []

    for result in case_results:
        returned_count = result.get(
            "returned_count"
        )

        if returned_count is None:
            cutoff_metrics = result.get(
                "metrics",
                {},
            )

            returned_count = next(
                (
                    metric.get(
                        "returned_count"
                    )
                    for metric in (
                        cutoff_metrics.values()
                    )
                    if metric.get(
                        "returned_count"
                    ) is not None
                ),
                None,
            )

        if returned_count is None:
            raise ValueError(
                "case result must include "
                "returned_count"
            )

        returned_counts.append(
            int(returned_count)
        )

    return {
        "case_count": len(case_results),
        "returned_count": {
            "count": len(returned_counts),
            "min": (
                min(returned_counts)
                if returned_counts
                else None
            ),
            "mean": (
                round(
                    statistics.fmean(
                        returned_counts
                    ),
                    3,
                )
                if returned_counts
                else None
            ),
            "p50": round_optional(
                percentile(
                    returned_counts,
                    50,
                ),
                3,
            ),
            "max": (
                max(returned_counts)
                if returned_counts
                else None
            ),
        },
        "cutoffs": cutoff_summary,
        "database_latency_ms": latency_summary(
            [
                float(result["database_latency_ms"])
                for result in case_results
            ]
        ),
        "end_to_end_latency_ms": latency_summary(
            [
                float(result["end_to_end_latency_ms"])
                for result in case_results
            ]
        ),
    }


def case_category_value(
    case: EvaluationCase,
) -> str | None:
    """Return the plain category value used by PostgreSQL."""

    if case.category is None:
        return None

    value = getattr(
        case.category,
        "value",
        case.category,
    )

    return str(value)


def case_filter_configuration(
    case: EvaluationCase,
) -> dict[str, Any]:
    """Serialize the filters applied to one evaluation case."""

    return {
        "category": case_category_value(case),
        "visible_statuses": list(
            case.visible_statuses
        ),
        "city": case.city,
        "district": case.district,
        "latitude": case.latitude,
        "longitude": case.longitude,
        "radius_km": case.radius_km,
    }


async def retrieve_semantic_candidates(
    connection: Any,
    *,
    mode: str,
    case: EvaluationCase,
    query_embedding: Any,
    limit: int,
    ef_search: int,
    iterative_scan: str = DEFAULT_ITERATIVE_SCAN,
    radius_overfetch_factor: float = (
        DEFAULT_RADIUS_OVERFETCH_FACTOR
    ),
) -> list[dict[str, Any]]:
    """Dispatch one case to global or filtered semantic recall."""

    if mode == "global":
        return await semantic_search_global(
            connection,
            query_embedding=query_embedding,
            limit=limit,
            ef_search=ef_search,
        )

    if mode == "filtered":
        return await semantic_search_filtered(
            connection,
            query_embedding=query_embedding,
            category=case_category_value(case),
            visible_statuses=case.visible_statuses,
            city=case.city,
            district=case.district,
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

    raise ValueError(
        f"unsupported semantic evaluation mode: {mode}"
    )


async def evaluate_mode(
    *,
    mode: str,
    cases: Sequence[EvaluationCase],
    model: Any,
    cutoffs: Sequence[int],
    ef_search_values: Sequence[int],
    iterative_scan: str = DEFAULT_ITERATIVE_SCAN,
    radius_overfetch_factor: float = (
        DEFAULT_RADIUS_OVERFETCH_FACTOR
    ),
) -> tuple[
    list[dict[str, Any]],
    list[float],
]:
    """Evaluate all cases under one semantic recall mode."""

    if mode not in {
        "global",
        "filtered",
    }:
        raise ValueError(
            f"unsupported semantic evaluation mode: {mode}"
        )

    max_cutoff = max(cutoffs)

    encoded_cases: list[
        tuple[EvaluationCase, Any, float]
    ] = []
    encoder_latencies: list[float] = []

    for case in cases:
        started_at = time.perf_counter()

        embedding = encode_query(
            model,
            case.query,
        )

        encoder_ms = (
            time.perf_counter() - started_at
        ) * 1000.0

        encoder_latencies.append(encoder_ms)
        encoded_cases.append(
            (
                case,
                embedding,
                encoder_ms,
            )
        )

    experiments: list[dict[str, Any]] = []

    async with await connect_postgres() as connection:
        for ef_search in ef_search_values:
            case_results: list[dict[str, Any]] = []

            for case, embedding, encoder_ms in encoded_cases:
                database_started_at = (
                    time.perf_counter()
                )

                candidates = (
                    await retrieve_semantic_candidates(
                        connection,
                        mode=mode,
                        case=case,
                        query_embedding=embedding,
                        limit=max_cutoff,
                        ef_search=ef_search,
                        iterative_scan=iterative_scan,
                        radius_overfetch_factor=(
                            radius_overfetch_factor
                        ),
                    )
                )

                database_ms = (
                    time.perf_counter()
                    - database_started_at
                ) * 1000.0

                returned_source_ids = [
                    str(candidate["source_id"])
                    for candidate in candidates
                ]

                case_results.append(
                    {
                        "case_id": case.case_id,
                        "query": case.query,
                        "mode": mode,
                        "filters": (
                            case_filter_configuration(
                                case
                            )
                        ),
                        "requested_limit": max_cutoff,
                        "binary_relevance_threshold": (
                            case.binary_relevance_threshold
                        ),
                        "returned_count": len(candidates),
                        "encoder_latency_ms": round(
                            encoder_ms,
                            3,
                        ),
                        "database_latency_ms": round(
                            database_ms,
                            3,
                        ),
                        "end_to_end_latency_ms": round(
                            encoder_ms + database_ms,
                            3,
                        ),
                        "metrics": build_cutoff_metrics(
                            returned_source_ids,
                            case,
                            cutoffs,
                        ),
                        "positive_ranks": (
                            build_judged_ranks(
                                returned_source_ids,
                                case.relevance,
                                minimum_grade=(
                                    case.binary_relevance_threshold
                                ),
                            )
                        ),
                        "anchor_ranks": (
                            build_judged_ranks(
                                returned_source_ids,
                                case.relevance,
                                minimum_grade=3,
                                exact_grade=3,
                            )
                        ),
                        "top_candidates": [
                            {
                                "rank": rank,
                                **candidate,
                            }
                            for rank, candidate in enumerate(
                                candidates[:20],
                                start=1,
                            )
                        ],
                    }
                )

            experiments.append(
                {
                    "mode": mode,
                    "ef_search": ef_search,
                    "iterative_scan": (
                        iterative_scan
                        if mode == "filtered"
                        else None
                    ),
                    "radius_overfetch_factor": (
                        radius_overfetch_factor
                        if mode == "filtered"
                        else None
                    ),
                    "summary": (
                        build_experiment_summary(
                            case_results,
                            cutoffs,
                        )
                    ),
                    "cases": case_results,
                }
            )

    return experiments, encoder_latencies


async def evaluate_global(
    *,
    cases: Sequence[EvaluationCase],
    model: Any,
    cutoffs: Sequence[int],
    ef_search_values: Sequence[int],
) -> tuple[
    list[dict[str, Any]],
    list[float],
]:
    """Backward-compatible global evaluation wrapper."""

    return await evaluate_mode(
        mode="global",
        cases=cases,
        model=model,
        cutoffs=cutoffs,
        ef_search_values=ef_search_values,
    )


def positive_int(value: str) -> int:
    """Parse one positive integer CLI argument."""

    parsed = int(value)

    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return parsed


def overfetch_factor(value: str) -> float:
    """Parse a radius over-fetch factor of at least one."""

    parsed = float(value)

    if parsed < 1.0:
        raise argparse.ArgumentTypeError(
            "value must be greater than or equal to 1.0"
        )

    return parsed


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate global or business-filtered "
            "BGE + pgvector HNSW recall."
        )
    )

    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL_PATH,
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
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
        nargs="+",
        default=list(DEFAULT_EF_SEARCH_VALUES),
    )
    parser.add_argument(
        "--mode",
        choices=("global", "filtered"),
        default="global",
    )
    parser.add_argument(
        "--iterative-scan",
        choices=("off", "strict_order"),
        default=DEFAULT_ITERATIVE_SCAN,
    )
    parser.add_argument(
        "--radius-overfetch-factor",
        type=overfetch_factor,
        default=DEFAULT_RADIUS_OVERFETCH_FACTOR,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )

    return parser.parse_args()


async def async_main(
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run semantic recall evaluation and save the JSON report."""

    cutoffs = normalize_positive_values(
        args.cutoffs,
        name="cutoffs",
        maximum=MAX_RECALL_LIMIT,
    )
    ef_search_values = normalize_positive_values(
        args.ef_search,
        name="ef_search",
        maximum=MAX_EF_SEARCH,
    )

    output_path = args.output

    if output_path is None:
        output_path = (
            DEFAULT_FILTERED_OUTPUT_PATH
            if args.mode == "filtered"
            else DEFAULT_OUTPUT_PATH
        )

    model_path = args.model_path.resolve()

    if not model_path.is_dir():
        raise FileNotFoundError(
            f"Local model directory not found: {model_path}"
        )

    cases = load_cases(
        args.cases.resolve()
    )
    device = resolve_device(
        args.device
    )

    print("========== semantic recall evaluation ==========")
    print("mode:", args.mode)
    print("cases:", len(cases))
    print("model_path:", model_path)
    print("device:", device)
    print("cutoffs:", cutoffs)
    print("ef_search:", ef_search_values)
    print(
        "iterative_scan:",
        (
            args.iterative_scan
            if args.mode == "filtered"
            else None
        ),
    )
    print(
        "radius_overfetch_factor:",
        (
            args.radius_overfetch_factor
            if args.mode == "filtered"
            else None
        ),
    )

    model_started_at = time.perf_counter()

    model = load_model(
        model_path,
        device=device,
    )

    model_load_ms = (
        time.perf_counter() - model_started_at
    ) * 1000.0

    warmup_started_at = time.perf_counter()
    encode_query(
        model,
        "语义检索模型预热",
    )
    warmup_ms = (
        time.perf_counter() - warmup_started_at
    ) * 1000.0

    experiments, encoder_latencies = (
        await evaluate_mode(
            mode=args.mode,
            cases=cases,
            model=model,
            cutoffs=cutoffs,
            ef_search_values=ef_search_values,
            iterative_scan=args.iterative_scan,
            radius_overfetch_factor=(
                args.radius_overfetch_factor
            ),
        )
    )

    report = {
        "generated_at_utc": datetime.now(
            UTC
        ).isoformat(),
        "mode": args.mode,
        "configuration": {
            "mode": args.mode,
            "cases": str(args.cases),
            "model_path": str(model_path),
            "device": device,
            "cutoffs": cutoffs,
            "ef_search_values": ef_search_values,
            "maximum_recall_limit": max(cutoffs),
            "iterative_scan": (
                args.iterative_scan
                if args.mode == "filtered"
                else None
            ),
            "radius_overfetch_factor": (
                args.radius_overfetch_factor
                if args.mode == "filtered"
                else None
            ),
        },
        "model": {
            "dimension": (
                model.get_embedding_dimension()
            ),
            "load_latency_ms": round(
                model_load_ms,
                3,
            ),
            "warmup_latency_ms": round(
                warmup_ms,
                3,
            ),
        },
        "encoder_latency_ms": latency_summary(
            encoder_latencies
        ),
        "experiments": experiments,
    }

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\n========== summary ==========")
    print(
        "encoder_latency_ms:",
        report["encoder_latency_ms"],
    )

    for experiment in experiments:
        print(
            "\nef_search:",
            experiment["ef_search"],
        )
        print(
            "iterative_scan:",
            experiment["iterative_scan"],
        )
        print(
            "radius_overfetch_factor:",
            experiment[
                "radius_overfetch_factor"
            ],
        )
        print(
            "returned_count:",
            experiment["summary"][
                "returned_count"
            ],
        )
        print(
            "database_latency_ms:",
            experiment["summary"][
                "database_latency_ms"
            ],
        )
        print(
            "end_to_end_latency_ms:",
            experiment["summary"][
                "end_to_end_latency_ms"
            ],
        )

        for cutoff in cutoffs:
            metrics = experiment["summary"][
                "cutoffs"
            ][str(cutoff)]

            print(
                f"@{cutoff}",
                "| complete=",
                (
                    f"{metrics['complete_case_count']}"
                    f"/{experiment['summary']['case_count']}"
                ),
                "| recall=",
                metrics["macro_recall"],
                "| mrr=",
                metrics["mrr"],
                "| grade3_hit=",
                metrics["grade3_hit_rate"],
            )

    print("\noutput:", output_path)

    return report


def main() -> None:
    """CLI entry point."""

    args = parse_args()
    asyncio.run(
        async_main(args)
    )


if __name__ == "__main__":
    main()
