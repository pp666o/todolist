"""Tests for the online semantic-recall runtime."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from todolist.app.features.post_search.post_search import PostSearchRequest
from todolist.app.infrastructure import semantic_runtime
from todolist.app.algorithms.search.geo import calculate_bounding_box


class FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False


def test_semantic_model_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic_runtime.get_semantic_model.cache_clear()

    model = object()
    calls: list[tuple[object, str]] = []

    monkeypatch.setattr(
        semantic_runtime,
        "resolve_device",
        lambda _: "cpu",
    )

    def fake_load_model(
        model_path,
        *,
        device,
    ):
        calls.append(
            (
                model_path,
                device,
            )
        )
        return model

    monkeypatch.setattr(
        semantic_runtime,
        "load_model",
        fake_load_model,
    )

    try:
        first = semantic_runtime.get_semantic_model()
        second = semantic_runtime.get_semantic_model()

        assert first is model
        assert second is model
        assert len(calls) == 1
        assert calls[0][1] == "cpu"
    finally:
        semantic_runtime.get_semantic_model.cache_clear()


def test_filtered_runtime_maps_request_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    connection = FakeConnection()
    model = object()
    embedding = np.zeros(
        512,
        dtype=np.float32,
    )
    embedding[0] = 1.0

    monkeypatch.setattr(
        semantic_runtime,
        "get_semantic_model",
        lambda: model,
    )
    monkeypatch.setattr(
        semantic_runtime,
        "encode_query",
        lambda active_model, query: embedding,
    )

    async def fake_connect():
        return connection

    async def fake_search(
        active_connection,
        **kwargs,
    ):
        captured["connection"] = (
            active_connection
        )
        captured.update(kwargs)
        return [
            {
                "source": "mysql",
                "source_id": "1",
                "semantic_score": 0.8,
                "semantic_distance": 0.2,
                "latitude": 36.6,
                "longitude": 117.0,
                "distance_km": 1.0,
            }
        ]

    monkeypatch.setattr(
        semantic_runtime,
        "connect_postgres",
        fake_connect,
    )
    monkeypatch.setattr(
        semantic_runtime,
        "semantic_search_filtered",
        fake_search,
    )

    request = PostSearchRequest(
        query="附近电脑维修",
        category="求助",
        visible_statuses=[
            "1",
        ],
        city="济南市",
        district="市中区",
        latitude=36.613094,
        longitude=117.033028,
        radius_km=20.0,
        recall_k=500,
    )

    result = asyncio.run(
        semantic_runtime.recall_filtered_semantic(
            request
        )
    )

    bounding_box = calculate_bounding_box(
        request.latitude,
        request.longitude,
        request.radius_km,
    )

    assert result[0]["source_id"] == "1"
    assert captured["connection"] is connection
    assert captured["query_embedding"] is embedding
    assert captured["category"] == "求助"
    assert captured["visible_statuses"] == ["1"]
    assert captured["city"] == "济南市"
    assert captured["district"] == "市中区"
    assert captured["min_latitude"] == pytest.approx(
        bounding_box["min_latitude"]
    )
    assert captured["max_latitude"] == pytest.approx(
        bounding_box["max_latitude"]
    )
    assert captured["min_longitude"] == pytest.approx(
        bounding_box["min_longitude"]
    )
    assert captured["max_longitude"] == pytest.approx(
        bounding_box["max_longitude"]
    )
    assert captured["limit"] == 200
    assert captured["ef_search"] == 200
    assert (
        captured["iterative_scan"]
        == "strict_order"
    )
    assert (
        captured["radius_overfetch_factor"]
        == 2.0
    )
