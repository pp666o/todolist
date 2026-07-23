"""PostgreSQL repository for community posts."""

from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection

from app.domain.post import PostUpsert
from app.infrastructure.postgres import connect_postgres


POST_SELECT_COLUMNS = """
    id,
    source,
    source_id,
    title,
    content,
    category,
    tags,
    latitude,
    longitude,
    country,
    province,
    city,
    district,
    address,
    likes,
    views,
    marks,
    dislikes,
    ratescore,
    visible_status,
    owner_id,
    created_at,
    updated_at,
    embedding_updated_at,
    synced_at
"""


POST_UPSERT_SQL = """
    INSERT INTO posts (
        source,
        source_id,
        title,
        content,
        category,
        tags,
        latitude,
        longitude,
        country,
        province,
        city,
        district,
        address,
        likes,
        views,
        marks,
        dislikes,
        ratescore,
        visible_status,
        owner_id,
        created_at,
        updated_at
    )
    VALUES (
        %(source)s,
        %(source_id)s,
        %(title)s,
        %(content)s,
        %(category)s,
        %(tags)s,
        %(latitude)s,
        %(longitude)s,
        %(country)s,
        %(province)s,
        %(city)s,
        %(district)s,
        %(address)s,
        %(likes)s,
        %(views)s,
        %(marks)s,
        %(dislikes)s,
        %(ratescore)s,
        %(visible_status)s,
        %(owner_id)s,
        %(created_at)s,
        %(updated_at)s
    )
    ON CONFLICT (source, source_id)
    DO UPDATE SET
        title = EXCLUDED.title,
        content = EXCLUDED.content,
        category = EXCLUDED.category,
        tags = EXCLUDED.tags,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        country = EXCLUDED.country,
        province = EXCLUDED.province,
        city = EXCLUDED.city,
        district = EXCLUDED.district,
        address = EXCLUDED.address,
        likes = EXCLUDED.likes,
        views = EXCLUDED.views,
        marks = EXCLUDED.marks,
        dislikes = EXCLUDED.dislikes,
        ratescore = EXCLUDED.ratescore,
        visible_status = EXCLUDED.visible_status,
        owner_id = EXCLUDED.owner_id,
        created_at = EXCLUDED.created_at,
        updated_at = EXCLUDED.updated_at,

        embedding = CASE
            WHEN posts.title IS DISTINCT FROM EXCLUDED.title
              OR posts.content IS DISTINCT FROM EXCLUDED.content
              OR posts.category IS DISTINCT FROM EXCLUDED.category
              OR posts.tags IS DISTINCT FROM EXCLUDED.tags
            THEN NULL
            ELSE posts.embedding
        END,

        embedding_updated_at = CASE
            WHEN posts.title IS DISTINCT FROM EXCLUDED.title
              OR posts.content IS DISTINCT FROM EXCLUDED.content
              OR posts.category IS DISTINCT FROM EXCLUDED.category
              OR posts.tags IS DISTINCT FROM EXCLUDED.tags
            THEN NULL
            ELSE posts.embedding_updated_at
        END,

        synced_at = now()
"""


class PostRepository:
    """Read and persist posts in PostgreSQL."""

    async def count(self) -> int:
        """Return the total number of stored posts."""
        async with await connect_postgres() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT count(*) AS post_count
                    FROM posts
                    """
                )
                row = await cursor.fetchone()

        if row is None:
            raise RuntimeError("Post count query returned no result.")

        return int(row["post_count"])

    async def get_by_id(self, post_id: int) -> dict[str, Any] | None:
        """Return one post by its internal PostgreSQL ID."""
        async with await connect_postgres() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    SELECT
                        {POST_SELECT_COLUMNS}
                    FROM posts
                    WHERE id = %s
                    """,
                    (post_id,),
                )
                row = await cursor.fetchone()

        return row

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
    ) -> list[dict[str, Any]]:
        """Return filtered post candidates for downstream ranking.

        This method performs database-level hard filtering and stable
        candidate ordering. Text scoring, exact distance calculation,
        Redis feature retrieval, and final ranking belong to the service
        layer.
        """
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000.")

        if category is not None and category not in {
            "求助",
            "问答",
            "吐槽",
        }:
            raise ValueError(f"Unsupported post category: {category!r}")

        def validate_range(
            *,
            name: str,
            minimum: float | None,
            maximum: float | None,
            lower_bound: float,
            upper_bound: float,
        ) -> None:
            if (minimum is None) != (maximum is None):
                raise ValueError(
                    f"{name} minimum and maximum must be provided together."
                )

            if minimum is None or maximum is None:
                return

            if not lower_bound <= minimum <= upper_bound:
                raise ValueError(
                    f"{name} minimum must be between "
                    f"{lower_bound} and {upper_bound}."
                )

            if not lower_bound <= maximum <= upper_bound:
                raise ValueError(
                    f"{name} maximum must be between "
                    f"{lower_bound} and {upper_bound}."
                )

            if minimum > maximum:
                raise ValueError(
                    f"{name} minimum cannot exceed maximum."
                )

        validate_range(
            name="latitude",
            minimum=min_latitude,
            maximum=max_latitude,
            lower_bound=-90,
            upper_bound=90,
        )
        validate_range(
            name="longitude",
            minimum=min_longitude,
            maximum=max_longitude,
            lower_bound=-180,
            upper_bound=180,
        )

        normalized_statuses = list(
            dict.fromkeys(
                status.strip()
                for status in (visible_statuses or ())
                if status and status.strip()
            )
        )

        normalized_city = city.strip() if city else None
        normalized_district = district.strip() if district else None

        conditions: list[str] = []
        parameters: dict[str, Any] = {
            "limit": limit,
        }

        if category is not None:
            conditions.append("category = %(category)s")
            parameters["category"] = category

        if normalized_statuses:
            conditions.append(
                "visible_status = ANY(%(visible_statuses)s)"
            )
            parameters["visible_statuses"] = normalized_statuses

        if normalized_city:
            conditions.append("city = %(city)s")
            parameters["city"] = normalized_city

        if normalized_district:
            conditions.append("district = %(district)s")
            parameters["district"] = normalized_district

        if min_latitude is not None and max_latitude is not None:
            conditions.append(
                "latitude BETWEEN %(min_latitude)s AND %(max_latitude)s"
            )
            parameters["min_latitude"] = min_latitude
            parameters["max_latitude"] = max_latitude

        if min_longitude is not None and max_longitude is not None:
            conditions.append(
                "longitude BETWEEN %(min_longitude)s AND %(max_longitude)s"
            )
            parameters["min_longitude"] = min_longitude
            parameters["max_longitude"] = max_longitude

        where_sql = (
            " AND\n                ".join(conditions)
            if conditions
            else "TRUE"
        )

        query = f"""
            SELECT
                {POST_SELECT_COLUMNS}
            FROM posts
            WHERE
                {where_sql}
            ORDER BY
                updated_at DESC NULLS LAST,
                views DESC,
                id DESC
            LIMIT %(limit)s
        """

        async with await connect_postgres() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query, parameters)
                rows = await cursor.fetchall()

        return list(rows)

    async def fetch_by_source_keys(
        self,
        source_keys: Sequence[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        """Hydrate posts by business keys in requested order."""

        normalized_keys: list[
            tuple[str, str]
        ] = []
        seen: set[tuple[str, str]] = set()

        for raw_key in source_keys:
            if len(raw_key) != 2:
                raise ValueError(
                    "source key must contain "
                    "(source, source_id)"
                )

            source = str(raw_key[0]).strip()
            source_id = str(raw_key[1]).strip()

            if not source:
                raise ValueError(
                    "source must not be blank"
                )

            if not source_id:
                raise ValueError(
                    "source_id must not be blank"
                )

            key = source, source_id

            if key in seen:
                continue

            seen.add(key)
            normalized_keys.append(key)

        if not normalized_keys:
            return []

        parameters = {
            "sources": [
                source
                for source, _ in normalized_keys
            ],
            "source_ids": [
                source_id
                for _, source_id in normalized_keys
            ],
        }

        query = f"""
            WITH requested AS (
                SELECT
                    source,
                    source_id,
                    ordinal
                FROM unnest(
                    %(sources)s::text[],
                    %(source_ids)s::text[]
                ) WITH ORDINALITY AS input(
                    source,
                    source_id,
                    ordinal
                )
            ),
            hydrated AS (
                SELECT
                    {POST_SELECT_COLUMNS}
                FROM posts
            )
            SELECT
                hydrated.*
            FROM requested
            JOIN hydrated
              ON hydrated.source = requested.source
             AND hydrated.source_id = requested.source_id
            ORDER BY requested.ordinal
        """

        async with await connect_postgres() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    query,
                    parameters,
                )
                rows = await cursor.fetchall()

        return list(rows)

    async def upsert_many(
        self,
        posts: Sequence[PostUpsert],
        *,
        connection: AsyncConnection[dict[str, Any]] | None = None,
    ) -> int:
        """Insert or update posts using the business unique key."""
        if not posts:
            return 0

        parameters = [post.model_dump(mode="python") for post in posts]

        owns_connection = connection is None
        active_connection = connection or await connect_postgres()

        try:
            async with active_connection.cursor() as cursor:
                await cursor.executemany(
                    POST_UPSERT_SQL,
                    parameters,
                )

            if owns_connection:
                await active_connection.commit()

            return len(posts)

        except Exception:
            if owns_connection:
                await active_connection.rollback()
            raise

        finally:
            if owns_connection:
                await active_connection.close()


post_repository = PostRepository()
