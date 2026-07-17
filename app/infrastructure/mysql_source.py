"""Remote MySQL source configuration and connection helpers."""

import re
from functools import lru_cache
from typing import Any

import pymysql
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymysql.connections import Connection
from pymysql.cursors import DictCursor


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_$.-]+$")


class MySQLSourceSettings(BaseSettings):
    """Remote MySQL source settings loaded from .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(
        min_length=1,
        validation_alias="MYSQL_SOURCE_HOST",
    )
    port: int = Field(
        default=3306,
        ge=1,
        le=65535,
        validation_alias="MYSQL_SOURCE_PORT",
    )
    user: str = Field(
        min_length=1,
        validation_alias="MYSQL_SOURCE_USER",
    )
    password: SecretStr = Field(
        validation_alias="MYSQL_SOURCE_PASSWORD",
    )
    database: str = Field(
        min_length=1,
        validation_alias="MYSQL_SOURCE_DATABASE",
    )
    table: str = Field(
        default="tiezi_geo_new",
        min_length=1,
        validation_alias="MYSQL_SOURCE_TABLE",
    )
    charset: str = Field(
        default="utf8mb4",
        validation_alias="MYSQL_SOURCE_CHARSET",
    )


@lru_cache
def get_mysql_source_settings() -> MySQLSourceSettings:
    """Return process-wide remote MySQL settings."""
    settings = MySQLSourceSettings()

    for identifier_name, identifier_value in (
        ("database", settings.database),
        ("table", settings.table),
    ):
        if not _IDENTIFIER_PATTERN.fullmatch(identifier_value):
            raise ValueError(
                f"Unsafe MySQL {identifier_name} identifier: "
                f"{identifier_value!r}"
            )

    return settings


def quote_mysql_identifier(identifier: str) -> str:
    """Safely quote a previously validated MySQL identifier."""
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"Unsafe MySQL identifier: {identifier!r}")

    return f"`{identifier.replace('`', '``')}`"


def connect_mysql_source() -> Connection:
    """Open a synchronous connection to the remote MySQL source."""
    settings = get_mysql_source_settings()

    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password.get_secret_value(),
        database=settings.database,
        charset=settings.charset,
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )


def check_mysql_source_connection() -> dict[str, Any]:
    """Verify connectivity and inspect the configured source table."""
    settings = get_mysql_source_settings()
    table = quote_mysql_identifier(settings.table)

    with connect_mysql_source() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    DATABASE() AS database_name,
                    VERSION() AS mysql_version
                """
            )
            server = cursor.fetchone()

            cursor.execute(
                f"""
                SELECT count(*) AS row_count
                FROM {table}
                """
            )
            table_result = cursor.fetchone()

    if server is None or table_result is None:
        raise RuntimeError("MySQL source check returned no result.")

    return {
        **server,
        "table_name": settings.table,
        "row_count": int(table_result["row_count"]),
    }
