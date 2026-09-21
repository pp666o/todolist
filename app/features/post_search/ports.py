"""Dependency interfaces for the post-search use case."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any, Protocol, TypeAlias


PostRow: TypeAlias = dict[str, Any]

RealtimeFeatures: TypeAlias = dict[str, int]

RealtimeFeatureMap: TypeAlias = dict[
    str,
    RealtimeFeatures,
]

RealtimeFeatureLoader: TypeAlias = Callable[
    [Iterable[int | str]],
    Awaitable[RealtimeFeatureMap],
]


class PostSearchRepository(Protocol):
    """Data-access contract required by post search."""

    async def search_candidates(
        self,
        *,
        category: str | None = None,
        visible_statuses: Sequence[str] | None = None,
        city: str | None = None,
        district: str | None = None,
        min_latitude: float | None = None,
        max_latitude: float | None = None,
        min_longitude: float | None = None,
        max_longitude: float | None = None,
        limit: int = 200,
    ) -> list[PostRow]:
        ...

    async def fetch_by_source_keys(
        self,
        source_keys: Sequence[tuple[str, str]],
    ) -> list[PostRow]:
        ...