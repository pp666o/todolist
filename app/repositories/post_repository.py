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
