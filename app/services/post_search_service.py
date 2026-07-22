"""Application service for geo-aware post search."""

from __future__ import annotations

import math
import unicodedata
from typing import Any
from uuid import uuid4

from app.infrastructure.redis import get_post_realtime_features
from app.repositories.post_repository import (
    PostRepository,
    post_repository,
)
from app.schemas.post_search import (
    PostSearchHit,
    PostSearchRequest,
    PostSearchResponse,
)
from app.search.geo import (
    calculate_bounding_box as _calculate_bounding_box,
    haversine_km as _haversine_km,
)


def _normalize_text(value: str | None) -> str:
    """Normalize text for lightweight lexical matching."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.lower().split())


def _character_bigrams(value: str) -> set[str]:
    """Return character bigrams for Chinese-friendly rough matching."""
    compact = value.replace(" ", "")

    if not compact:
        return set()

    if len(compact) == 1:
        return {compact}

    return {
        compact[index : index + 2]
        for index in range(len(compact) - 1)
    }


def _field_match_score(query: str, field: str) -> float:
    """Calculate one normalized lexical field score."""
    if not query or not field:
        return 0.0

    if query == field:
        return 1.0

    if query in field:
        return 0.9

    query_tokens = {
        token
        for token in query.split()
        if token
    }

    token_coverage = 0.0

    if query_tokens:
        matched_tokens = sum(
            1
            for token in query_tokens
            if token in field
        )
        token_coverage = matched_tokens / len(query_tokens)

    query_bigrams = _character_bigrams(query)
    field_bigrams = _character_bigrams(field)

    bigram_coverage = 0.0

    if query_bigrams:
        bigram_coverage = (
            len(query_bigrams & field_bigrams)
            / len(query_bigrams)
        )

    return min(
        1.0,
        max(
            0.8 * token_coverage,
            0.7 * bigram_coverage,
        ),
    )


def _calculate_text_score(
    query: str,
    row: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    """Calculate title/tag/content lexical relevance."""
    normalized_query = _normalize_text(query)
    normalized_title = _normalize_text(row.get("title"))
    normalized_content = _normalize_text(row.get("content"))

    tags = row.get("tags") or []
    normalized_tags = _normalize_text(" ".join(tags))

    title_score = _field_match_score(
        normalized_query,
        normalized_title,
    )
    tag_score = _field_match_score(
        normalized_query,
        normalized_tags,
    )
    content_score = _field_match_score(
        normalized_query,
        normalized_content,
    )

    text_score = (
        0.55 * title_score
        + 0.30 * tag_score
        + 0.15 * content_score
    )

    recall_sources: list[str] = []
    reasons: list[str] = []

    if title_score > 0:
        recall_sources.append("keyword_title")
        reasons.append("标题与搜索词相关")

    if tag_score > 0:
        recall_sources.append("keyword_tags")
        reasons.append("标签与搜索词相关")

    if content_score > 0:
        recall_sources.append("keyword_content")
        reasons.append("正文与搜索词相关")

    return (
        min(1.0, max(0.0, text_score)),
        recall_sources,
        reasons,
    )


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


def _static_hot_raw(row: dict[str, Any]) -> float:
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
    features: dict[str, int],
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
    features: dict[str, int],
) -> float:
    """Calculate the Redis unlock signal."""
    unlocks_24h = max(
        0,
        int(features.get("unlocks_24h", 0)),
    )
    return math.log1p(unlocks_24h)


class PostSearchService:
    """Coordinate recall, filtering, ranking, and result assembly."""

    def __init__(
        self,
        repository: PostRepository = post_repository,
    ) -> None:
        self._repository = repository

    async def search(
        self,
        request: PostSearchRequest,
    ) -> PostSearchResponse:
        """Search posts with lexical, geographic and static signals."""
        bounding_box: dict[str, float | None] = {
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

        candidates = await self._repository.search_candidates(
            category=request.category,
            visible_statuses=request.visible_statuses,
            city=request.city,
            district=request.district,
            min_latitude=bounding_box["min_latitude"],
            max_latitude=bounding_box["max_latitude"],
            min_longitude=bounding_box["min_longitude"],
            max_longitude=bounding_box["max_longitude"],
            limit=request.recall_k,
        )

        scored_candidates: list[dict[str, Any]] = []

        for row in candidates:
            (
                text_score,
                recall_sources,
                reasons,
            ) = _calculate_text_score(request.query, row)

            if text_score <= 0:
                continue

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
                    "geo_score": min(1.0, geo_score),
                    "distance_km": distance_km,
                    "hot_raw": _static_hot_raw(row),
                    "recall_sources": list(
                        dict.fromkeys(recall_sources)
                    ),
                    "reasons": list(dict.fromkeys(reasons)),
                }
            )

        degraded = False
        degraded_reason: str | None = None
        realtime_features: dict[str, dict[str, int]] = {}

        if scored_candidates:
            source_ids = [
                str(candidate["row"]["source_id"])
                for candidate in scored_candidates
            ]

            try:
                realtime_features = (
                    await get_post_realtime_features(source_ids)
                )
            except Exception as exc:
                degraded = True
                degraded_reason = (
                    "Redis realtime features unavailable: "
                    f"{type(exc).__name__}"
                )

        for candidate in scored_candidates:
            source_id = str(candidate["row"]["source_id"])
            features = realtime_features.get(source_id, {})

            candidate["realtime_hot_raw"] = (
                _realtime_hot_raw(features)
            )
            candidate["unlock_raw"] = _unlock_raw(features)

            if candidate["realtime_hot_raw"] > 0:
                candidate["recall_sources"].append(
                    "redis_realtime"
                )
                candidate["reasons"].append(
                    "近期互动较活跃"
                )

            if candidate["unlock_raw"] > 0:
                candidate["recall_sources"].append(
                    "redis_unlock"
                )
                candidate["reasons"].append(
                    "近期解锁较多"
                )

            candidate["recall_sources"] = list(
                dict.fromkeys(candidate["recall_sources"])
            )
            candidate["reasons"] = list(
                dict.fromkeys(candidate["reasons"])
            )

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

        request_has_geo = any(
            value is not None
            for value in (
                request.city,
                request.district,
                request.latitude,
                request.longitude,
            )
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

            if request_has_geo:
                weights["geo"] = 0.25

            if has_unlock_signal:
                weights["unlock"] = 0.10

            weighted_sum = (
                weights["text"] * candidate["text_score"]
                + weights["hot"] * hot_score
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

        scored_candidates.sort(
            key=lambda candidate: (
                -candidate["final_score"],
                -candidate["text_score"],
                (
                    candidate["distance_km"]
                    if candidate["distance_km"] is not None
                    else math.inf
                ),
                -int(candidate["row"]["id"]),
            )
        )

        selected = scored_candidates[: request.top_k]

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
                semantic_score=None,
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

        return PostSearchResponse(
            request_id=uuid4().hex,
            query=request.query,
            total_candidates=len(candidates),
            result_count=len(items),
            items=items,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )


post_search_service = PostSearchService()
