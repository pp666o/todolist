"""Static tests for PostgreSQL lexical-search indexes."""

from pathlib import Path


MIGRATION_PATH = Path(
    "db/migrations/004_add_post_lexical_indexes.sql"
)


def normalized_sql() -> str:
    """Return lowercase SQL with normalized whitespace."""

    return " ".join(
        MIGRATION_PATH.read_text(
            encoding="utf-8"
        )
        .lower()
        .split()
    )


def test_lexical_index_migration_exists() -> None:
    assert MIGRATION_PATH.is_file()


def test_migration_is_transactional_and_idempotent() -> None:
    sql = normalized_sql()

    assert sql.startswith("begin;")
    assert sql.endswith("commit;")
    assert (
        "create extension if not exists pg_trgm;"
        in sql
    )
    assert sql.count(
        "create index if not exists"
    ) == 3


def test_title_and_content_use_trigram_gin() -> None:
    sql = normalized_sql()

    assert (
        "create index if not exists "
        "idx_posts_title_trgm on posts "
        "using gin (title gin_trgm_ops);"
        in sql
    )
    assert (
        "create index if not exists "
        "idx_posts_content_trgm on posts "
        "using gin (content gin_trgm_ops);"
        in sql
    )


def test_tags_use_native_array_gin() -> None:
    sql = normalized_sql()

    assert (
        "create index if not exists "
        "idx_posts_tags_gin on posts "
        "using gin (tags);"
        in sql
    )


def test_migration_does_not_claim_bm25() -> None:
    sql = normalized_sql()

    assert "bm25" not in sql
