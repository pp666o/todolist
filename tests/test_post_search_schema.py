"""Tests for post-search request validation."""

import pytest
from pydantic import ValidationError

from app.schemas.post_search import PostSearchRequest


def test_query_is_trimmed() -> None:
    request = PostSearchRequest(
        query="  附近修电脑  ",
        top_k=10,
        recall_k=200,
    )

    assert request.query == "附近修电脑"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "query": "   ",
        },
        {
            "query": "测试",
            "top_k": 20,
            "recall_k": 10,
        },
        {
            "query": "测试",
            "latitude": 30.0,
        },
        {
            "query": "测试",
            "longitude": 120.0,
        },
        {
            "query": "测试",
            "radius_km": 10.0,
        },
        {
            "query": "测试",
            "unexpected_field": "forbidden",
        },
    ],
)
def test_invalid_requests_return_validation_error(
    payload: dict,
) -> None:
    with pytest.raises(ValidationError):
        PostSearchRequest(**payload)


def test_valid_geo_request() -> None:
    request = PostSearchRequest(
        query="附近修电脑",
        latitude=30.0,
        longitude=120.0,
        radius_km=10.0,
        top_k=5,
        recall_k=100,
    )

    assert request.radius_km == 10.0
