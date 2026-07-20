"""Regression test for API route registration."""

from fastapi import FastAPI

from app.api import matching_api, post_search


def test_search_and_matching_routes_are_registered() -> None:
    app = FastAPI()

    app.include_router(matching_api.router)
    app.include_router(post_search.router)

    schema = app.openapi()
    paths = set(schema["paths"])

    assert "/search/posts" in paths
    assert "/matching/users" in paths
    assert "/matching/items" in paths
    assert "/matching/potential-matches/{user_id}" in paths
