"""HTTP contract tests for post search."""

import asyncio

import httpx
from fastapi import FastAPI

from todolist.app.serving.routers import post_search
from todolist.app.features.post_search.post_search import PostSearchResponse


def create_test_app(monkeypatch) -> FastAPI:
    async def fake_search(request):
        return PostSearchResponse(
            request_id="test-request",
            query=request.query,
            total_candidates=0,
            result_count=0,
            items=[],
            degraded=False,
            degraded_reason=None,
        )

    monkeypatch.setattr(
        post_search.post_search_service,
        "search",
        fake_search,
    )

    app = FastAPI()
    app.include_router(post_search.router)
    return app


def post_json(
    app: FastAPI,
    path: str,
    payload: dict,
) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                path,
                json=payload,
            )

    return asyncio.run(request())


def test_search_posts_returns_200(monkeypatch) -> None:
    app = create_test_app(monkeypatch)

    response = post_json(
        app,
        "/search/posts",
        {
            "query": "附近修电脑",
            "top_k": 10,
            "recall_k": 200,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["query"] == "附近修电脑"
    assert payload["result_count"] == 0
    assert payload["degraded"] is False


def test_invalid_search_request_returns_422(
    monkeypatch,
) -> None:
    app = create_test_app(monkeypatch)

    response = post_json(
        app,
        "/search/posts",
        {
            "query": "测试",
            "latitude": 30.0,
        },
    )

    assert response.status_code == 422


def test_top_k_cannot_exceed_recall_k(
    monkeypatch,
) -> None:
    app = create_test_app(monkeypatch)

    response = post_json(
        app,
        "/search/posts",
        {
            "query": "测试",
            "top_k": 20,
            "recall_k": 10,
        },
    )

    assert response.status_code == 422
