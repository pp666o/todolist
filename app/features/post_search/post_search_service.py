"""Application service for geo-aware post search."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict
from uuid import uuid4

from app.infrastructure.redis import get_post_realtime_features
from app.algorithms.search.text_relevance import calculate_text_score
from app.algorithms.search.semantic_scoring import (
    calibrate_semantic_score,
)
from app.repositories.post_repository import (
    PostRepository,
    post_repository,
)
from app.features.post_search.post_search import (
    PostSearchHit,
    PostSearchRequest,
    PostSearchResponse,
)
from app.algorithms.search.candidate_merge import (
    hydrate_recall_candidates,
    merge_recall_candidates,
)
from app.algorithms.search.geo import (
    calculate_bounding_box as _calculate_bounding_box,
    haversine_km as _haversine_km,
)


SemanticRecaller = Callable[
    [PostSearchRequest],
    Awaitable[list[dict[str, Any]]],
]

PostRow = dict[str, Any]
SemanticCandidate = dict[str, Any]
RealtimeFeatures = dict[str, int]
RealtimeFeatureMap = dict[str, RealtimeFeatures]


class BoundingBox(TypedDict):
    min_latitude: float | None
    max_latitude: float | None
    min_longitude: float | None
    max_longitude: float | None


class ScoredSearchCandidate(TypedDict, total=False):
    row: PostRow
    text_score: float
    semantic_score: float | None
    semantic_ranking_score: float
    geo_score: float
    distance_km: float | None
    hot_raw: float
    realtime_hot_raw: float
    unlock_raw: float
    hot_score: float
    unlock_score: float
    final_score: float
    recall_sources: list[str]
    reasons: list[str]


def _validate_semantic_ranking_parameters(
    *,
    semantic_weight: float,
    semantic_zero_text_min_score: float,
) -> None:
    """Validate configurable semantic-ranking parameters."""

    if not 0.0 <= semantic_weight <= 1.0:
        raise ValueError(
            "semantic_weight must be between 0 and 1"
        )

    if not (
        0.0
        <= semantic_zero_text_min_score
        <= 1.0
    ):
        raise ValueError(
            "semantic_zero_text_min_score "
            "must be between 0 and 1"
        )
    


def _static_hot_raw(row: PostRow) -> float:
    """Calculate a long-tail-safe static popularity value."""
    views = max(0, int(row.get("views") or 0))
    likes = max(0, int(row.get("likes") or 0))
    marks = max(0, int(row.get("marks") or 0))
    dislikes = max(0, int(row.get("dislikes") or 0))

    return max(
        0.0,
        0.20 * math.log1p(views)
        + 0.40 * math.log1p(likes)
        + 0.30 * math.log1p(marks)
        - 0.10 * math.log1p(dislikes),
    )


def _realtime_hot_raw(
    features: RealtimeFeatures,
) -> float:
    """Calculate Redis-backed realtime popularity."""
    views_1h = max(0, int(features.get("views_1h", 0)))
    views_24h = max(0, int(features.get("views_24h", 0)))
    likes_24h = max(0, int(features.get("likes_24h", 0)))
    marks_24h = max(0, int(features.get("marks_24h", 0)))

    return (
        0.20 * math.log1p(views_1h)
        + 0.25 * math.log1p(views_24h)
        + 0.35 * math.log1p(likes_24h)
        + 0.20 * math.log1p(marks_24h)
    )


def _unlock_raw(
    features: RealtimeFeatures,
) -> float:
    """Calculate the Redis unlock signal."""
    unlocks_24h = max(
        0,
        int(features.get("unlocks_24h", 0)),
    )
    return math.log1p(unlocks_24h)


def _min_max_normalize(values: list[float]) -> list[float]:
    """Normalize values to the inclusive [0, 1] interval."""
    if not values:
        return []

    minimum = min(values)
    maximum = max(values)

    if math.isclose(minimum, maximum):
        return [0.0 for _ in values]

    scale = maximum - minimum

    return [
        (value - minimum) / scale
        for value in values
    ]


def _build_bounding_box(request: PostSearchRequest,
) -> BoundingBox:
    bounding_box: BoundingBox = {
        "min_latitude": None,
        "max_latitude": None,
        "min_longitude": None,
        "max_longitude": None,
    }

    if (
        request.latitude is not None
        and request.longitude is not None
        and request.radius_km is not None
    ):
        bounding_box = _calculate_bounding_box(
            request.latitude,
            request.longitude,
            request.radius_km,
        )

    return bounding_box


async def _load_realtime_features(
    scored_candidates: list[ScoredSearchCandidate],
    degradation_reasons: list[str],
) -> RealtimeFeatureMap:
    realtime_features: RealtimeFeatureMap = {}

    if not scored_candidates:
        return realtime_features

    source_ids = [
        str(candidate["row"]["source_id"])
        for candidate in scored_candidates
    ]

    try:
        realtime_features = await get_post_realtime_features(source_ids)
    except Exception as exc:
        degradation_reasons.append(
            "Redis realtime features unavailable: "
            f"{type(exc).__name__}"
        )

    return realtime_features



def _attach_realtime_signals(
    scored_candidates: list[ScoredSearchCandidate],
    realtime_features: RealtimeFeatureMap,
) -> None:
    for candidate in scored_candidates:
        source_id = str(candidate["row"]["source_id"])
        features = realtime_features.get(source_id, {})

        candidate["realtime_hot_raw"] = _realtime_hot_raw(features)
        candidate["unlock_raw"] = _unlock_raw(features)

        if candidate["realtime_hot_raw"] > 0:
            candidate["recall_sources"].append("redis_realtime")
            candidate["reasons"].append("近期互动较活跃")

        if candidate["unlock_raw"] > 0:
            candidate["recall_sources"].append("redis_unlock")
            candidate["reasons"].append("近期解锁较多")

        candidate["recall_sources"] = list(dict.fromkeys(candidate["recall_sources"]))
        candidate["reasons"] = list(dict.fromkeys(candidate["reasons"]))


def _compute_final_scores(
    scored_candidates: list[ScoredSearchCandidate],
    *,
    request_has_geo: bool,
    semantic_weight: float,
) -> None:
    static_hot_scores = _min_max_normalize(
        [
            candidate["hot_raw"]
            for candidate in scored_candidates
        ]
    )

    realtime_hot_scores = _min_max_normalize(
        [
            candidate["realtime_hot_raw"]
            for candidate in scored_candidates
        ]
    )

    unlock_scores = _min_max_normalize(
        [
            candidate["unlock_raw"]
            for candidate in scored_candidates
        ]
    )

    has_unlock_signal = any(
        candidate["unlock_raw"] > 0
        for candidate in scored_candidates
    )

    for (
        candidate,
        static_hot_score,
        realtime_hot_score,
        unlock_score,
    ) in zip(
        scored_candidates,
        static_hot_scores,
        realtime_hot_scores,
        unlock_scores,
    ):
        hot_score = (
            0.65 * static_hot_score
            + 0.35 * realtime_hot_score
        )

        weights = {
            "text": 0.50,
            "hot": 0.15,
        }

        if semantic_weight > 0:
            weights["semantic"] = (
                semantic_weight
            )

        if request_has_geo:
            weights["geo"] = 0.25

        if has_unlock_signal:
            weights["unlock"] = 0.10

        weighted_sum = (
            weights["text"] * candidate["text_score"]
            + weights["hot"] * hot_score
        )

        if "semantic" in weights:
            weighted_sum += (
                weights["semantic"]
                * candidate[
                    "semantic_ranking_score"
                ]
            )

        if "geo" in weights:
            weighted_sum += (
                weights["geo"] * candidate["geo_score"]
            )

        if "unlock" in weights:
            weighted_sum += (
                weights["unlock"] * unlock_score
            )

        candidate["hot_score"] = hot_score
        candidate["unlock_score"] = unlock_score
        candidate["final_score"] = (
            weighted_sum / sum(weights.values())
        )


def _sort_candidates(
    scored_candidates: list[ScoredSearchCandidate],
) -> None:
    scored_candidates.sort(
        key=lambda candidate: (
            -candidate["final_score"],
            -candidate["text_score"],
            -candidate["semantic_ranking_score"],
            (
                candidate["distance_km"]
                if candidate["distance_km"] is not None
                else math.inf
            ),
            -int(candidate["row"]["id"]),
        )
    )


def _build_hits(
    selected: list[ScoredSearchCandidate],
) -> list[PostSearchHit]:
    items = [
            PostSearchHit(
                post_id=int(candidate["row"]["id"]),
                source=str(candidate["row"]["source"]),
                source_id=str(candidate["row"]["source_id"]),
                title=str(candidate["row"]["title"]),
                content=str(candidate["row"]["content"]),
                category=candidate["row"]["category"],
                tags=list(candidate["row"].get("tags") or []),
                city=candidate["row"].get("city"),
                district=candidate["row"].get("district"),
                address=candidate["row"].get("address"),
                latitude=candidate["row"].get("latitude"),
                longitude=candidate["row"].get("longitude"),
                distance_km=(
                    round(candidate["distance_km"], 4)
                    if candidate["distance_km"] is not None
                    else None
                ),
                score=round(candidate["final_score"], 6),
                text_score=round(
                    candidate["text_score"],
                    6,
                ),
                semantic_score=(
                    round(
                        candidate["semantic_score"],
                        6,
                    )
                    if candidate[
                        "semantic_score"
                    ] is not None
                    else None
                ),
                bm25_score=None,
                geo_score=round(
                    candidate["geo_score"],
                    6,
                ),
                hot_score=round(
                    candidate["hot_score"],
                    6,
                ),
                unlock_score=round(
                    candidate["unlock_score"],
                    6,
                ),
                recall_sources=candidate["recall_sources"],
                reason="；".join(candidate["reasons"]) or None,
            )
            for candidate in selected
            ]
    return items


def _build_response(
    *,
    request: PostSearchRequest,
    total_candidates: int,
    items: list[PostSearchHit],
    degradation_reasons: list[str],
) -> PostSearchResponse:
    degraded = bool(degradation_reasons)
    degraded_reason = (
        "; ".join(degradation_reasons)
        if degradation_reasons
        else None
    )

    return PostSearchResponse(
        request_id=uuid4().hex,
        query=request.query,
        total_candidates=total_candidates,
        result_count=len(items),
        items=items,
        degraded=degraded,
        degraded_reason=degraded_reason,
    )    

class PostSearchService:
    """Coordinate recall, filtering, ranking, and result assembly."""

    def __init__(
        self,
        repository: PostRepository = post_repository,
        semantic_recaller: SemanticRecaller | None = None,
        *,
        semantic_weight: float = 0.0,
        semantic_zero_text_min_score: float = 0.0,
    ) -> None:
        _validate_semantic_ranking_parameters(
            semantic_weight=semantic_weight,
            semantic_zero_text_min_score=(
                semantic_zero_text_min_score
            ),
        )

        self._repository = repository
        self._semantic_recaller = semantic_recaller
        self._semantic_weight = float(
            semantic_weight
        )
        self._semantic_zero_text_min_score = float(
            semantic_zero_text_min_score
        )

    async def search(
        self,
        request: PostSearchRequest,
    ) -> PostSearchResponse:
        """Search posts with lexical, geographic and static signals."""

        degradation_reasons: list[str] = []
        bounding_box = _build_bounding_box(request)
        freshness_candidates = (
            await self._repository.search_candidates(
                category=request.category,
                visible_statuses=request.visible_statuses,
                city=request.city,
                district=request.district,
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
                limit=request.recall_k,
            )
        )

        semantic_candidates: list[
            dict[str, Any]
        ] = []

        if self._semantic_recaller is not None:
            try:
                semantic_candidates = list(
                    await self._semantic_recaller(
                        request
                    )
                )
            except Exception as exc:
                degradation_reasons.append(
                    "Semantic recall unavailable: "
                    f"{type(exc).__name__}"
                )

        merged_candidates = merge_recall_candidates(
            freshness_candidates=(
                freshness_candidates
            ),
            semantic_candidates=semantic_candidates,
        )

        source_keys = [
            (
                candidate["source"],
                candidate["source_id"],
            )
            for candidate in merged_candidates
        ]

        try:
            hydrated_rows = (
                await self._repository.fetch_by_source_keys(
                    source_keys
                )
            )
            hydrated_candidates = (
                hydrate_recall_candidates(
                    merged_candidates,
                    hydrated_rows,
                )
            )
        except Exception as exc:
            degradation_reasons.append(
                "Candidate hydration unavailable: "
                f"{type(exc).__name__}"
            )

            freshness_only = merge_recall_candidates(
                freshness_candidates=(
                    freshness_candidates
                ),
                semantic_candidates=[],
            )
            hydrated_candidates = (
                hydrate_recall_candidates(
                    freshness_only,
                    freshness_candidates,
                )
            )

        scored_candidates: list[ScoredSearchCandidate] = []

        for recalled_candidate in hydrated_candidates:
            row = recalled_candidate["row"]
            semantic_score = recalled_candidate[
                "semantic_score"
            ]

            (
                text_score,
                lexical_recall_sources,
                reasons,
            ) = calculate_text_score(
                request.query,
                row,
            )

            recall_sources = list(
                dict.fromkeys(
                    [
                        *recalled_candidate[
                            "recall_sources"
                        ],
                        *lexical_recall_sources,
                    ]
                )
            )

            semantic_ranking_score = (
                calibrate_semantic_score(
                    semantic_score,
                    minimum_score=(
                        self
                        ._semantic_zero_text_min_score
                    ),
                )
            )

            semantic_ranking_enabled = (
                self._semantic_weight > 0
            )

            if text_score <= 0 and (
                not semantic_ranking_enabled
                or semantic_ranking_score <= 0
            ):
                continue

            if semantic_score is not None:
                reasons.append("语义相关")

            distance_km: float | None = None
            geo_score = 0.0

            row_latitude = row.get("latitude")
            row_longitude = row.get("longitude")

            if (
                request.latitude is not None
                and request.longitude is not None
                and row_latitude is not None
                and row_longitude is not None
            ):
                distance_km = _haversine_km(
                    request.latitude,
                    request.longitude,
                    float(row_latitude),
                    float(row_longitude),
                )

                if (
                    request.radius_km is not None
                    and distance_km > request.radius_km
                ):
                    continue

                if request.radius_km is not None:
                    distance_score = max(
                        0.0,
                        1.0 - distance_km / request.radius_km,
                    )
                    recall_sources.append("radius_filter")
                else:
                    distance_score = 1.0 / (
                        1.0 + distance_km / 10.0
                    )

                geo_score += 0.70 * distance_score

                reasons.append(
                    f"距离约 {distance_km:.1f} km"
                )

            if (
                request.city
                and row.get("city") == request.city
            ):
                geo_score += 0.20
                recall_sources.append("city_filter")
                reasons.append("位于指定城市")

            if (
                request.district
                and row.get("district") == request.district
            ):
                geo_score += 0.10
                recall_sources.append("district_filter")
                reasons.append("位于指定区域")

            scored_candidates.append(
                {
                    "row": row,
                    "text_score": text_score,
                    "semantic_score": semantic_score,
                    "semantic_ranking_score": (
                        semantic_ranking_score
                    ),
                    "geo_score": min(1.0, geo_score),
                    "distance_km": distance_km,
                    "hot_raw": _static_hot_raw(row),
                    "recall_sources": list(
                        dict.fromkeys(recall_sources)
                    ),
                    "reasons": list(dict.fromkeys(reasons)),
                }
            )

        realtime_features = await _load_realtime_features(
            scored_candidates,
            degradation_reasons,
        )
        _attach_realtime_signals(
            scored_candidates,
            realtime_features,
        )

        request_has_geo = any(
            value is not None
            for value in (
                request.city,
                request.district,
                request.latitude,
                request.longitude,
            )
        )

        _compute_final_scores(
            scored_candidates,
            request_has_geo=request_has_geo,
            semantic_weight=self._semantic_weight,
        )
        _sort_candidates(scored_candidates)

        selected = scored_candidates[: request.top_k]
        items = _build_hits(selected)

        return _build_response(
            request=request,
            total_candidates=len(hydrated_candidates),
            items=items,
            degradation_reasons=degradation_reasons,
        )
# Semantic recall remains opt-in until BM25 or a stronger
# reranking stage can safely control semantic-only candidates.
post_search_service = PostSearchService()
