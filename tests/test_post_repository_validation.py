"""Validation tests for PostgreSQL candidate recall."""

import asyncio

import pytest

from app.repositories.post_repository import PostRepository


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize("limit", [0, -1, 2001])
def test_invalid_limit_is_rejected(limit: int) -> None:
    repository = PostRepository()

    with pytest.raises(
        ValueError,
        match="limit must be between",
    ):
        run(repository.search_candidates(limit=limit))


def test_invalid_category_is_rejected() -> None:
    repository = PostRepository()

    with pytest.raises(
        ValueError,
        match="Unsupported post category",
    ):
        run(
            repository.search_candidates(
                category="其他",
            )
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "min_latitude": 30.0,
        },
        {
            "max_latitude": 30.0,
        },
        {
            "min_longitude": 100.0,
        },
        {
            "max_longitude": 100.0,
        },
        {
            "min_latitude": 40.0,
            "max_latitude": 30.0,
        },
        {
            "min_longitude": 120.0,
            "max_longitude": 110.0,
        },
    ],
)
def test_invalid_bounds_are_rejected(kwargs: dict) -> None:
    repository = PostRepository()

    with pytest.raises(ValueError):
        run(repository.search_candidates(**kwargs))
