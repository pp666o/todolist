"""PostgreSQL connection configuration and helpers."""

from functools import lru_cache
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    """PostgreSQL settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database: str = Field(validation_alias="POSTGRES_DB")
    user: str = Field(validation_alias="POSTGRES_USER")
    password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    host: str = Field(default="127.0.0.1", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias="POSTGRES_PORT")


@lru_cache
def get_postgres_settings() -> PostgresSettings:
    """Return the process-wide PostgreSQL settings instance."""
    return PostgresSettings()


async def connect_postgres() -> AsyncConnection[dict[str, Any]]:
    """Open an asynchronous PostgreSQL connection."""
    settings = get_postgres_settings()

    return await AsyncConnection.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.database,
        user=settings.user,
        password=settings.password.get_secret_value(),
        row_factory=dict_row,
    )


async def check_postgres_connection() -> dict[str, Any]:
    """Verify PostgreSQL connectivity and the pgvector extension."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    current_database() AS database,
                    current_user AS database_user,
                    current_setting('server_version') AS postgres_version,
                    (
                        SELECT extversion
                        FROM pg_extension
                        WHERE extname = 'vector'
                    ) AS vector_version,
                    (
                        SELECT count(*)
                        FROM posts
                    ) AS post_count
                """
            )

            row = await cursor.fetchone()

    if row is None:
        raise RuntimeError("PostgreSQL connectivity check returned no result.")

    return row
