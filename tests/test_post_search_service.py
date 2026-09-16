"""Tests for the post-search application service."""

import asyncio
from typing import Any

import pytest

from app.features.post_search.post_search import PostSearchRequest
from app.features.post_search import post_search_service as service_module
from app.features.post_search.post_search_service import PostSearchService


class FakePostRepository:
    """In-memory repository used by service tests."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        freshness_rows: list[
            dict[str, Any]
        ] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.freshness_rows = (
            list(freshness_rows)
            if freshness_rows is not None
            else list(rows)
        )
        self.last_parameters: (
            dict[str, Any] | None
        ) = None
        self.last_source_keys: list[
            tuple[str, str]
        ] | None = None

    async def search_candidates(
        self,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.last_parameters = kwargs
        return list(self.freshness_rows)

    async def fetch_by_source_keys(
        self,
        source_keys: list[
            tuple[str, str]
        ],
    ) -> list[dict[str, Any]]:
        self.last_source_keys = list(
            source_keys
        )

        row_by_key = {
            (
                str(row["source"]),
                str(row["source_id"]),
            ): row
            for row in self.rows
        }

        return [
            row_by_key[key]
            for key in source_keys
            if key in row_by_key
        ]


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


def test_search_merges_freshness_and_semantic_candidates(
    monkeypatch,
) -> None:
    fresh = make_post(
        post_id=1,
        source_id="fresh",
        title="电脑维修帮助",
        latitude=37.689434,
        longitude=112.761673,
    )
    shared = make_post(
        post_id=2,
        source_id="shared",
        title="电脑维修服务",
        latitude=37.689434,
        longitude=112.761673,
    )
    semantic_only = make_post(
        post_id=3,
        source_id="semantic-only",
        title="完全不同的标题",
        latitude=37.689434,
        longitude=112.761673,
    )
    semantic_only["content"] = "另一段不包含查询词的正文"
    semantic_only["tags"] = []

    repository = FakePostRepository(
        [
            fresh,
            shared,
            semantic_only,
        ],
        freshness_rows=[
            fresh,
            shared,
        ],
    )

    async def fake_semantic_recaller(_):
        return [
            {
                "source": shared["source"],
                "source_id": shared["source_id"],
                "semantic_score": 0.91,
                "semantic_distance": 0.09,
            },
            {
                "source": semantic_only["source"],
                "source_id": semantic_only["source_id"],
                "semantic_score": 0.83,
                "semantic_distance": 0.17,
            },
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
        repository=repository,
        semantic_recaller=(
            fake_semantic_recaller
        ),
        semantic_weight=0.10,
        semantic_zero_text_min_score=0.50,
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                top_k=10,
                recall_k=200,
            )
        )
    )

    assert response.total_candidates == 3
    assert response.result_count == 3
    assert repository.last_source_keys == [
        (
            "mysql_tiezi_geo_new",
            "fresh",
        ),
        (
            "mysql_tiezi_geo_new",
            "shared",
        ),
        (
            "mysql_tiezi_geo_new",
            "semantic-only",
        ),
    ]

    items = {
        item.source_id: item
        for item in response.items
    }

    assert items["shared"].semantic_score == 0.91
    assert items["shared"].recall_sources[:2] == [
        "freshness",
        "semantic",
    ]

    assert (
        items["semantic-only"].semantic_score
        == 0.83
    )
    assert items[
        "semantic-only"
    ].text_score == 0.0
    assert items[
        "semantic-only"
    ].recall_sources == [
        "semantic"
    ]


def test_semantic_failure_falls_back_to_freshness(
    monkeypatch,
) -> None:
    row = make_post(
        post_id=1,
        source_id="fresh",
        title="电脑维修帮助",
        latitude=37.689434,
        longitude=112.761673,
    )

    async def failed_semantic(_):
        raise RuntimeError(
            "simulated semantic failure"
        )

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
        repository=FakePostRepository([row]),
        semantic_recaller=failed_semantic,
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                top_k=10,
                recall_k=200,
            )
        )
    )

    assert response.result_count == 1
    assert response.items[0].source_id == "fresh"
    assert response.items[
        0
    ].semantic_score is None
    assert response.degraded is True
    assert response.degraded_reason is not None
    assert (
        "Semantic recall unavailable"
        in response.degraded_reason
    )


def test_semantic_and_redis_failures_are_combined(
    monkeypatch,
) -> None:
    row = make_post(
        post_id=1,
        source_id="fresh",
        title="电脑维修帮助",
        latitude=37.689434,
        longitude=112.761673,
    )

    async def failed_semantic(_):
        raise RuntimeError(
            "simulated semantic failure"
        )

    async def failed_redis(_):
        raise ConnectionError(
            "simulated Redis failure"
        )

    monkeypatch.setattr(
        service_module,
        "get_post_realtime_features",
        failed_redis,
    )

    service = PostSearchService(
        repository=FakePostRepository([row]),
        semantic_recaller=failed_semantic,
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                top_k=10,
                recall_k=200,
            )
        )
    )

    assert response.result_count == 1
    assert response.degraded is True
    assert response.degraded_reason is not None
    assert "Semantic" in response.degraded_reason
    assert "Redis" in response.degraded_reason


@pytest.mark.parametrize(
    (
        "semantic_weight",
        "semantic_zero_text_min_score",
    ),
    [
        (-0.1, 0.5),
        (1.1, 0.5),
        (0.2, -0.1),
        (0.2, 1.1),
    ],
)
def test_invalid_semantic_ranking_parameters_are_rejected(
    semantic_weight,
    semantic_zero_text_min_score,
) -> None:
    with pytest.raises(ValueError):
        PostSearchService(
            repository=FakePostRepository([]),
            semantic_weight=semantic_weight,
            semantic_zero_text_min_score=(
                semantic_zero_text_min_score
            ),
        )


def test_zero_text_semantic_candidate_below_threshold_is_removed(
    monkeypatch,
) -> None:
    semantic_only = make_post(
        post_id=1,
        source_id="semantic-low",
        title="完全无关标题",
        latitude=37.689434,
        longitude=112.761673,
    )
    semantic_only["content"] = "另一段无关正文"
    semantic_only["tags"] = []

    repository = FakePostRepository(
        [semantic_only],
        freshness_rows=[],
    )

    async def fake_semantic(_):
        return [
            {
                "source": semantic_only["source"],
                "source_id": semantic_only["source_id"],
                "semantic_score": 0.49,
                "semantic_distance": 0.51,
            }
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
        repository=repository,
        semantic_recaller=fake_semantic,
        semantic_weight=0.2,
        semantic_zero_text_min_score=0.5,
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                top_k=10,
                recall_k=200,
            )
        )
    )

    assert response.total_candidates == 1
    assert response.result_count == 0


def test_semantic_weight_orders_zero_text_candidates(
    monkeypatch,
) -> None:
    high = make_post(
        post_id=1,
        source_id="semantic-high",
        title="完全无关标题甲",
        latitude=37.689434,
        longitude=112.761673,
    )
    low = make_post(
        post_id=2,
        source_id="semantic-low",
        title="完全无关标题乙",
        latitude=37.689434,
        longitude=112.761673,
    )

    for row in (high, low):
        row["content"] = "另一段无关正文"
        row["tags"] = []
        row["views"] = 0
        row["likes"] = 0
        row["marks"] = 0
        row["dislikes"] = 0

    repository = FakePostRepository(
        [high, low],
        freshness_rows=[],
    )

    async def fake_semantic(_):
        return [
            {
                "source": low["source"],
                "source_id": low["source_id"],
                "semantic_score": 0.60,
                "semantic_distance": 0.40,
            },
            {
                "source": high["source"],
                "source_id": high["source_id"],
                "semantic_score": 0.90,
                "semantic_distance": 0.10,
            },
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
        repository=repository,
        semantic_recaller=fake_semantic,
        semantic_weight=0.3,
        semantic_zero_text_min_score=0.5,
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                top_k=10,
                recall_k=200,
            )
        )
    )

    assert response.result_count == 2
    assert [
        item.source_id
        for item in response.items
    ] == [
        "semantic-high",
        "semantic-low",
    ]
    assert (
        response.items[0].score
        > response.items[1].score
    )


def test_unweighted_semantic_only_candidate_is_not_admitted(
    monkeypatch,
) -> None:
    semantic_only = make_post(
        post_id=1,
        source_id="semantic-only",
        title="完全无关的标题",
        latitude=37.689434,
        longitude=112.761673,
    )
    semantic_only["content"] = "另一段完全无关的正文"
    semantic_only["tags"] = []

    repository = FakePostRepository(
        [semantic_only],
        freshness_rows=[],
    )

    async def fake_semantic(_):
        return [
            {
                "source": semantic_only["source"],
                "source_id": semantic_only["source_id"],
                "semantic_score": 0.95,
                "semantic_distance": 0.05,
            }
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
        repository=repository,
        semantic_recaller=fake_semantic,
        semantic_weight=0.0,
        semantic_zero_text_min_score=0.0,
    )

    response = run(
        service.search(
            PostSearchRequest(
                query="电脑维修",
                top_k=10,
                recall_k=200,
            )
        )
    )

    assert response.total_candidates == 1
    assert response.result_count == 0


def test_production_semantic_recall_remains_opt_in() -> None:
    assert (
        service_module
        .post_search_service
        ._semantic_recaller
        is None
    )
