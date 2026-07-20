"""Optional integration tests against local PostgreSQL."""

import asyncio
import os

import pytest

from app.repositories.post_repository import post_repository


RUN_INTEGRATION = (
    os.getenv("RUN_POSTGRES_INTEGRATION") == "1"
)


@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason=(
        "Set RUN_POSTGRES_INTEGRATION=1 "
        "to run PostgreSQL integration tests."
    ),
)
def test_real_candidate_filters() -> None:
    async def run_test() -> None:
        category_rows = (
            await post_repository.search_candidates(
                category="求助",
                limit=20,
            )
        )

        assert category_rows
        assert all(
            row["category"] == "求助"
            for row in category_rows
        )

        bbox_rows = (
            await post_repository.search_candidates(
                min_latitude=37.68,
                max_latitude=37.70,
                min_longitude=112.75,
                max_longitude=112.77,
                limit=20,
            )
        )

        assert any(
            row["source_id"] == "5891"
            for row in bbox_rows
        )

    asyncio.run(run_test())
