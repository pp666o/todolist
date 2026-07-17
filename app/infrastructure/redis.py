"""Redis connection and realtime-feature helpers."""

from functools import lru_cache
from typing import Any, Iterable

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis


POST_REALTIME_HASH_PREFIX = "post:rt"

POST_REALTIME_FIELDS = (
    "views_1h",
    "views_24h",
    "likes_24h",
    "marks_24h",
    "unlocks_24h",
)


class RedisSettings(BaseSettings):
    """Redis settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(
        default="127.0.0.1",
        min_length=1,
        validation_alias="REDIS_HOST",
    )
    port: int = Field(
        default=16379,
        ge=1,
        le=65535,
        validation_alias="REDIS_PORT",
    )
    db: int = Field(
        default=0,
        ge=0,
        validation_alias="REDIS_DB",
    )
    password: SecretStr | None = Field(
        default=None,
        validation_alias="REDIS_PASSWORD",
    )
    socket_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=30,
        validation_alias="REDIS_SOCKET_TIMEOUT_SECONDS",
    )


@lru_cache
def get_redis_settings() -> RedisSettings:
    """Return process-wide Redis settings."""
    return RedisSettings()


def create_redis_client() -> Redis:
    """Create an asynchronous Redis client."""
    settings = get_redis_settings()

    password = None
    if settings.password is not None:
        configured_password = settings.password.get_secret_value().strip()
        password = configured_password or None

    return Redis(
        host=settings.host,
        port=settings.port,
        db=settings.db,
        password=password,
        socket_connect_timeout=settings.socket_timeout_seconds,
        socket_timeout=settings.socket_timeout_seconds,
        decode_responses=True,
        health_check_interval=30,
    )


def build_post_realtime_key(post_id: int | str) -> str:
    """Return the Redis hash key for one canonical post."""
    return f"{POST_REALTIME_HASH_PREFIX}:{post_id}"


def _parse_nonnegative_int(value: Any) -> int:
    """Convert a Redis counter into a non-negative integer."""
    if value is None:
        return 0

    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


async def check_redis_connection() -> dict[str, Any]:
    """Verify Redis through the configured connection."""
    client = create_redis_client()

    try:
        async with client.pipeline(transaction=False) as pipeline:
            pipeline.ping()
            pipeline.dbsize()
            results = await pipeline.execute()

        server_info = await client.info(section="server")

        return {
            "ping": bool(results[0]),
            "dbsize": int(results[1]),
            "redis_version": server_info.get("redis_version"),
            "redis_mode": server_info.get("redis_mode"),
        }
    finally:
        await client.aclose()


async def get_post_realtime_features(
    post_ids: Iterable[int | str],
) -> dict[str, dict[str, int]]:
    """Read realtime features for multiple candidate posts using a pipeline."""
    normalized_ids = [str(post_id) for post_id in post_ids]

    if not normalized_ids:
        return {}

    client = create_redis_client()

    try:
        async with client.pipeline(transaction=False) as pipeline:
            for post_id in normalized_ids:
                pipeline.hmget(
                    build_post_realtime_key(post_id),
                    POST_REALTIME_FIELDS,
                )

            rows = await pipeline.execute()

        features: dict[str, dict[str, int]] = {}

        for post_id, values in zip(normalized_ids, rows):
            features[post_id] = {
                field: _parse_nonnegative_int(value)
                for field, value in zip(POST_REALTIME_FIELDS, values)
            }

        return features
    finally:
        await client.aclose()
