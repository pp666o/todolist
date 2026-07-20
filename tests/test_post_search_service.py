"""Tests for the post-search application service."""

import asyncio
from typing import Any

from app.schemas.post_search import PostSearchRequest
from app.services import post_search_service as service_module
from app.services.post_search_service import PostSearchService


class FakePostRepository:
    """In-memory repository used by service tests."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.rows = rows
        self.last_parameters: dict[str, Any] | None = None

    async def search_candidates(
        self,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.last_parameters = kwargs
        return list(self.rows)


def make_post(
    *,
    post_id: int,
    source_id: str,
    title: str,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    return {
        "id": post_id,
        "source": "mysql_tiezi_geo_new",
        "source_id": source_id,
        "title": title,
        "content": "软件欢迎发展，提供电脑维修帮助。",
        "category": "求助",
        "tags": ["软件", "电脑"],
        "latitude": latitude,
        "longitude": longitude,
        "country": "中国",
        "province": "山西省",
        "city": "晋中市",
        "district": "榆次区",
        "address": "测试地址",
        "likes": 10,
        "views": 100,
        "marks": 5,
        "dislikes": 1,
        "ratescore": 4.5,
        "visible_status": "1",
        "owner_id": "owner-1",
        "created_at": None,
        "updated_at": None,
        "embedding_updated_at": None,
        "synced_at": None,
    }


def run(coroutine):
    return asyncio.run(coroutine)


def test_search_uses_business_source_id_for_redis(
    monkeypatch,
) -> None:
    rows = [
        make_post(
            post_id=1,
            source_id="5891",
            title="进行欢迎有关这样",
            latitude=37.689434,
            longitude=112.761673,
        )
    ]

    repository = FakePostRepository(rows)
    captured_ids: list[str] = []

    async def fake_realtime_features(post_ids):
        captured_ids.extend(post_ids)

        return {
            "5891": {
                "views_1h": 0,
                "views_24h": 0,
                "likes_24h": 0,
                "marks_24h": 0,
                "unlocks_24h": 0,
            }
        }

    monkeypatch.setattr(
        service_module,
        "get_post_realtime_features",
        fake_realtime_features,
    )

    service = PostSearchService(repository=repository)

    response = run(
        service.search(
            PostSearchRequest(
                query="进行欢迎有关这样",
                latitude=37.689434,
                longitude=112.761673,
                radius_km=10,
                city="晋中市",
                district="榆次区",
                top_k=10,
                recall_k=100,
            )
        )
    )

    assert captured_ids == ["5891"]
    assert response.result_count == 1
    assert response.items[0].source_id == "5891"
    assert response.items[0].distance_km == 0.0
    assert response.items[0].unlock_score == 0.0
    assert response.degraded is False


def test_exact_radius_filter_removes_outside_post(
    monkeypatch,
) -> None:
    rows = [
        make_post(
            post_id=1,
            source_id="inside",
            title="电脑维修帮助",
            latitude=37.689434,
            longitude=112.761673,
        ),
        make_post(
            post_id=2,
            source_id="outside",
            title="电脑维修帮助",
            latitude=39.9042,
            longitude=116.4074,
        ),
    ]

    async def zero_features(post_ids):
        return {
            str(post_id): {
                "views_1h": 0,
                "views_24h": 0,
                "likes_24h": 0,
                "marks_24h": 0,
                "unlocks_24h": 0,
            }
            for post_id in post_ids
        }

    monkeypatch.setattr(
        service_module,
        "get_post_realtime_features",
        zero_features,
    )

    service = PostSearchService(
        repository=FakePostRepository(rows)
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                latitude=37.689434,
                longitude=112.761673,
                radius_km=10,
                top_k=10,
                recall_k=100,
            )
        )
    )

    assert response.result_count == 1
    assert response.items[0].source_id == "inside"


def test_redis_failure_degrades_without_losing_results(
    monkeypatch,
) -> None:
    rows = [
        make_post(
            post_id=1,
            source_id="5891",
            title="进行欢迎有关这样",
            latitude=37.689434,
            longitude=112.761673,
        )
    ]

    async def failed_realtime_features(_):
        raise ConnectionError("simulated Redis failure")

    monkeypatch.setattr(
        service_module,
        "get_post_realtime_features",
        failed_realtime_features,
    )

    service = PostSearchService(
        repository=FakePostRepository(rows)
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="进行欢迎有关这样",
                top_k=10,
                recall_k=100,
            )
        )
    )

    assert response.result_count == 1
    assert response.degraded is True
    assert response.degraded_reason is not None
    assert "Redis" in response.degraded_reason
