from __future__ import annotations

import math
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app import models, schemas, utils
from app.services.engine_service import global_engine


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    earth_radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )

    return earth_radius_km * 2 * math.atan2(
        math.sqrt(value),
        math.sqrt(max(0.0, 1.0 - value)),
    )


def _safe_number(value: int | float | None) -> float:
    return float(value or 0)


def _raw_popularity(todo: models.Todo) -> float:
    # 第一版仅用于工程链路验证。
    # 当前热度字段可能为模拟数据，不能解释为真实业务收益。
    engagement = (
        3.0 * _safe_number(todo.like_count)
        + 4.0 * _safe_number(todo.mark_count)
        + 0.05 * _safe_number(todo.view_count)
        + 1.0 * max(_safe_number(todo.rate_score), 0.0)
        - 2.0 * _safe_number(todo.dislike_count)
    )

    return math.log1p(max(engagement, 0.0))


def _distance_score(
    distance_km: float | None,
    radius_km: float | None,
) -> float | None:
    if distance_km is None:
        return None

    if radius_km is not None:
        return max(0.0, 1.0 - distance_km / radius_km)

    # 未提供半径时，10 km 约衰减到 0.5。
    return 1.0 / (1.0 + distance_km / 10.0)


def _build_reason(
    todo: models.Todo,
    distance_km: float | None,
    category: str | None,
) -> str:
    reasons = ["Dense 语义召回"]

    if category and todo.category == category:
        reasons.append(f"类别匹配：{category}")

    if distance_km is not None:
        reasons.append(f"距离约 {distance_km:.1f} km")

    if todo.city:
        reasons.append(todo.city)

    return "；".join(reasons)


def search_posts(
    db: Session,
    request: schemas.PostSearchRequest,
) -> dict[str, Any]:
    query_vector = utils.get_embedding(request.query)

    end_ts = int(time.time()) + 365 * 24 * 60 * 60

    dense_results = global_engine.search(
        start_ts=0,
        end_ts=end_ts,
        query_vector=query_vector,
        top_k=request.recall_k,
    )

    dense_candidate_count = len(dense_results)

    if not dense_results:
        return {
            "request_id": str(uuid.uuid4()),
            "query": request.query,
            "dense_candidate_count": 0,
            "filtered_candidate_count": 0,
            "results": [],
        }

    candidate_ids = [int(result[0]) for result in dense_results]
    semantic_scores = {
        int(result[0]): float(result[1])
        for result in dense_results
    }

    todos = (
        db.query(models.Todo)
        .filter(models.Todo.id.in_(candidate_ids))
        .all()
    )
    todo_by_id = {todo.id: todo for todo in todos}

    filtered: list[dict[str, Any]] = []

    for todo_id in candidate_ids:
        todo = todo_by_id.get(todo_id)

        if todo is None:
            continue

        if (
            request.visible_statuses is not None
            and todo.visible_status not in request.visible_statuses
        ):
            continue

        if request.category and todo.category != request.category:
            continue

        if request.city and todo.city != request.city:
            continue

        if request.district and todo.district != request.district:
            continue

        distance_km: float | None = None

        if (
            request.latitude is not None
            and request.longitude is not None
            and todo.latitude is not None
            and todo.longitude is not None
        ):
            distance_km = haversine_km(
                request.latitude,
                request.longitude,
                float(todo.latitude),
                float(todo.longitude),
            )

        if request.radius_km is not None:
            if distance_km is None:
                continue

            if distance_km > request.radius_km:
                continue

        filtered.append(
            {
                "todo": todo,
                "semantic_score": semantic_scores[todo_id],
                "distance_km": distance_km,
                "raw_popularity": _raw_popularity(todo),
            }
        )

    max_popularity = max(
        (item["raw_popularity"] for item in filtered),
        default=0.0,
    )

    results: list[dict[str, Any]] = []

    for item in filtered:
        todo = item["todo"]
        semantic_score = item["semantic_score"]
        distance_km = item["distance_km"]

        # 余弦相似度 [-1, 1] 映射到 [0, 1]。
        semantic_normalized = max(
            0.0,
            min(1.0, (semantic_score + 1.0) / 2.0),
        )

        popularity_score = (
            item["raw_popularity"] / max_popularity
            if max_popularity > 0
            else 0.0
        )

        distance_score = _distance_score(
            distance_km,
            request.radius_km,
        )

        weighted_sum = 0.70 * semantic_normalized
        total_weight = 0.70

        if distance_score is not None:
            weighted_sum += 0.20 * distance_score
            total_weight += 0.20

        if max_popularity > 0:
            weighted_sum += 0.10 * popularity_score
            total_weight += 0.10

        final_score = weighted_sum / total_weight

        results.append(
            {
                "id": todo.id,
                "source_id": todo.source_id,
                "title": todo.title,
                "content": todo.content,
                "category": todo.category,
                "tags": todo.tags,
                "city": todo.city,
                "district": todo.district,
                "latitude": todo.latitude,
                "longitude": todo.longitude,
                "visible_status": todo.visible_status,
                "semantic_score": round(semantic_score, 6),
                "distance_km": (
                    round(distance_km, 3)
                    if distance_km is not None
                    else None
                ),
                "popularity_score": round(popularity_score, 6),
                "final_score": round(final_score, 6),
                "recall_sources": ["dense"],
                "reason": _build_reason(
                    todo,
                    distance_km,
                    request.category,
                ),
                "created_at": todo.created_at,
            }
        )

    results.sort(
        key=lambda result: result["final_score"],
        reverse=True,
    )

    return {
        "request_id": str(uuid.uuid4()),
        "query": request.query,
        "dense_candidate_count": dense_candidate_count,
        "filtered_candidate_count": len(results),
        "results": results[: request.top_k],
    }
