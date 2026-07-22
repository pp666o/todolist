from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pytest

from app.search.embedding import MODEL_DIMENSION
from app.search.semantic_retrieval import (
    semantic_search_filtered,
    semantic_search_global,
    validate_filtered_semantic_search_parameters,
    validate_semantic_search_parameters,
)


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        traceback: Any,
    ) -> None:
        return None


class FakeCursor:
    def __init__(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.rows = rows
        self.executions: list[
            tuple[str, dict[str, Any] | None]
        ] = []

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        traceback: Any,
    ) -> None:
        return None

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.executions.append(
            (
                str(query),
                parameters,
            )
        )

    async def fetchall(
        self,
    ) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.cursor_instance = FakeCursor(rows)
        self.transaction_count = 0

    def transaction(self) -> FakeTransaction:
        self.transaction_count += 1
        return FakeTransaction()

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def normalized_vector() -> np.ndarray:
    vector = np.zeros(
        MODEL_DIMENSION,
        dtype=np.float32,
    )
    vector[0] = 1.0
    return vector


@pytest.mark.parametrize(
    ("limit", "ef_search", "message"),
    [
        (0, 100, "limit"),
        (2001, 100, "limit"),
        (20, 0, "ef_search"),
        (20, 1001, "ef_search"),
    ],
)
def test_validate_semantic_search_parameters_rejects_invalid(
    limit: int,
    ef_search: int,
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        validate_semantic_search_parameters(
            limit=limit,
            ef_search=ef_search,
        )


def test_validate_semantic_search_parameters_accepts_bounds() -> None:
    validate_semantic_search_parameters(
        limit=1,
        ef_search=1,
    )
    validate_semantic_search_parameters(
        limit=2000,
        ef_search=1000,
    )


def test_semantic_search_global_executes_hnsw_query() -> None:
    connection = FakeConnection(
        [
            {
                "source": "mysql",
                "source_id": 5276544,
                "semantic_score": 0.681118,
                "semantic_distance": 0.318882,
            },
            {
                "source": "mysql",
                "source_id": "84908361",
                "semantic_score": 0.673895,
                "semantic_distance": 0.326105,
            },
        ]
    )

    results = asyncio.run(
        semantic_search_global(
            connection,  # type: ignore[arg-type]
            query_embedding=normalized_vector(),
            limit=20,
            ef_search=100,
        )
    )

    assert connection.transaction_count == 1
    assert len(
        connection.cursor_instance.executions
    ) == 2

    set_sql, set_parameters = (
        connection.cursor_instance.executions[0]
    )
    query_sql, query_parameters = (
        connection.cursor_instance.executions[1]
    )

    assert (
        "SET LOCAL hnsw.ef_search = 100"
        in set_sql
    )
    assert set_parameters is None

    normalized_query_sql = " ".join(
        query_sql.split()
    )

    assert (
        "embedding <=> %(query_vector)s::vector"
        in normalized_query_sql
    )
    assert (
        "ORDER BY embedding "
        "<=> %(query_vector)s::vector"
        in normalized_query_sql
    )
    assert (
        "LIMIT %(limit)s"
        in normalized_query_sql
    )

    assert query_parameters is not None
    assert query_parameters["limit"] == 20
    assert str(
        query_parameters["query_vector"]
    ).startswith("[1,")

    assert results == [
        {
            "source": "mysql",
            "source_id": "5276544",
            "semantic_score": pytest.approx(
                0.681118
            ),
            "semantic_distance": pytest.approx(
                0.318882
            ),
        },
        {
            "source": "mysql",
            "source_id": "84908361",
            "semantic_score": pytest.approx(
                0.673895
            ),
            "semantic_distance": pytest.approx(
                0.326105
            ),
        },
    ]


def test_semantic_search_global_returns_empty_list() -> None:
    connection = FakeConnection([])

    results = asyncio.run(
        semantic_search_global(
            connection,  # type: ignore[arg-type]
            query_embedding=normalized_vector(),
            limit=5,
            ef_search=40,
        )
    )

    assert results == []


def test_semantic_search_global_validates_vector() -> None:
    connection = FakeConnection([])

    with pytest.raises(
        ValueError,
        match="Expected one embedding",
    ):
        asyncio.run(
            semantic_search_global(
                connection,  # type: ignore[arg-type]
                query_embedding=np.zeros(
                    384,
                    dtype=np.float32,
                ),
                limit=5,
                ef_search=40,
            )
        )

    assert connection.transaction_count == 0

@pytest.mark.parametrize(
    (
        "overrides",
        "message",
    ),
    [
        (
            {
                "category": "其他",
            },
            "Unsupported post category",
        ),
        (
            {
                "min_latitude": 10.0,
            },
            "latitude minimum and maximum",
        ),
        (
            {
                "latitude": 10.0,
            },
            "latitude and longitude",
        ),
        (
            {
                "radius_km": 10.0,
            },
            "radius_km requires",
        ),
        (
            {
                "radius_overfetch_factor": 0.5,
            },
            "radius_overfetch_factor",
        ),
        (
            {
                "iterative_scan": "relaxed_order",
            },
            "iterative_scan",
        ),
    ],
)
def test_validate_filtered_parameters_rejects_invalid(
    overrides: dict[str, Any],
    message: str,
) -> None:
    parameters: dict[str, Any] = {
        "category": None,
        "min_latitude": None,
        "max_latitude": None,
        "min_longitude": None,
        "max_longitude": None,
        "latitude": None,
        "longitude": None,
        "radius_km": None,
        "radius_overfetch_factor": 1.5,
        "limit": 20,
        "ef_search": 100,
        "iterative_scan": "off",
    }
    parameters.update(overrides)

    with pytest.raises(
        ValueError,
        match=message,
    ):
        validate_filtered_semantic_search_parameters(
            **parameters,
        )


def test_semantic_search_filtered_applies_filters_and_radius() -> None:
    connection = FakeConnection(
        [
            {
                "source": "mysql",
                "source_id": "inside",
                "latitude": 37.0,
                "longitude": 112.0,
                "semantic_score": 0.8,
                "semantic_distance": 0.2,
            },
            {
                "source": "mysql",
                "source_id": "outside",
                "latitude": 38.0,
                "longitude": 112.0,
                "semantic_score": 0.7,
                "semantic_distance": 0.3,
            },
        ]
    )

    results = asyncio.run(
        semantic_search_filtered(
            connection,  # type: ignore[arg-type]
            query_embedding=normalized_vector(),
            category="求助",
            visible_statuses=[
                "visible",
                "visible",
                " review ",
            ],
            city=" 晋中市 ",
            district=" 榆次区 ",
            min_latitude=36.5,
            max_latitude=37.5,
            min_longitude=111.5,
            max_longitude=112.5,
            latitude=37.0,
            longitude=112.0,
            radius_km=10.0,
            radius_overfetch_factor=2.0,
            limit=2,
            ef_search=100,
            iterative_scan="strict_order",
        )
    )

    assert connection.transaction_count == 1
    assert len(
        connection.cursor_instance.executions
    ) == 3

    ef_sql, ef_parameters = (
        connection.cursor_instance.executions[0]
    )
    iterative_sql, iterative_parameters = (
        connection.cursor_instance.executions[1]
    )
    query_sql, query_parameters = (
        connection.cursor_instance.executions[2]
    )

    assert (
        "SET LOCAL hnsw.ef_search = 100"
        in ef_sql
    )
    assert ef_parameters is None

    assert (
        "SET LOCAL hnsw.iterative_scan = "
        "strict_order"
        in iterative_sql
    )
    assert iterative_parameters is None

    normalized_sql = " ".join(
        query_sql.split()
    )

    assert (
        "category = %(category)s"
        in normalized_sql
    )
    assert (
        "visible_status = "
        "ANY(%(visible_statuses)s)"
        in normalized_sql
    )
    assert (
        "city = %(city)s"
        in normalized_sql
    )
    assert (
        "district = %(district)s"
        in normalized_sql
    )
    assert (
        "latitude BETWEEN "
        "%(min_latitude)s "
        "AND %(max_latitude)s"
        in normalized_sql
    )
    assert (
        "longitude BETWEEN "
        "%(min_longitude)s "
        "AND %(max_longitude)s"
        in normalized_sql
    )

    assert query_parameters is not None
    assert query_parameters["category"] == "求助"
    assert query_parameters[
        "visible_statuses"
    ] == [
        "visible",
        "review",
    ]
    assert query_parameters["city"] == "晋中市"
    assert query_parameters["district"] == "榆次区"
    assert query_parameters["scan_limit"] == 4

    assert len(results) == 1
    assert results[0]["source_id"] == "inside"
    assert results[0]["distance_km"] == pytest.approx(
        0.0
    )


def test_semantic_search_filtered_without_radius() -> None:
    connection = FakeConnection(
        [
            {
                "source": "mysql",
                "source_id": "candidate",
                "latitude": None,
                "longitude": None,
                "semantic_score": 0.6,
                "semantic_distance": 0.4,
            }
        ]
    )

    results = asyncio.run(
        semantic_search_filtered(
            connection,  # type: ignore[arg-type]
            query_embedding=normalized_vector(),
            limit=1,
            ef_search=40,
        )
    )

    assert results == [
        {
            "source": "mysql",
            "source_id": "candidate",
            "semantic_score": pytest.approx(
                0.6
            ),
            "semantic_distance": pytest.approx(
                0.4
            ),
            "latitude": None,
            "longitude": None,
            "distance_km": None,
        }
    ]

    _, _, query_execution = (
        connection.cursor_instance.executions
    )
    _, parameters = query_execution

    assert parameters is not None
    assert parameters["scan_limit"] == 1

