"""Static tests for the user-profile PostgreSQL migration."""

from pathlib import Path


MIGRATION_PATH = Path(
    "db/migrations/005_create_user_profiles.sql"
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


def test_user_profile_migration_exists() -> None:
    assert MIGRATION_PATH.is_file()


def test_migration_is_transactional_and_idempotent() -> None:
    sql = normalized_sql()

    assert sql.startswith("begin;")
    assert sql.endswith("commit;")

    assert (
        "create table if not exists "
        "public.user_profiles"
        in sql
    )

    assert sql.count(
        "create index if not exists"
    ) == 3


def test_business_key_and_profile_constraints_exist() -> None:
    sql = normalized_sql()

    assert (
        "unique (source, source_user_id)"
        in sql
    )

    assert (
        "check (authored_post_count >= 0)"
        in sql
    )

    assert (
        "check (profile_version > 0)"
        in sql
    )

    assert (
        "jsonb_typeof(category_weights) = 'object'"
        in sql
    )

    assert (
        "jsonb_typeof(tag_weights) = 'object'"
        in sql
    )


def test_profile_fields_support_creator_aggregation() -> None:
    sql = normalized_sql()

    required_fields = (
        "age_bucket",
        "hobby_tags",
        "authored_post_count",
        "category_weights",
        "tag_weights",
        "avg_likes",
        "avg_views",
        "avg_marks",
        "avg_dislikes",
        "avg_rate_score",
        "last_authored_at",
        "synced_at",
    )

    for field in required_fields:
        assert field in sql


def test_migration_excludes_sensitive_and_future_fields() -> None:
    sql = normalized_sql()

    excluded_fields = (
        "realname",
        "nickname",
        "revenue",
        "married_status",
        "from_lat",
        "from_lng",
        "address",
        "gender",
    )

    for field in excluded_fields:
        assert field not in sql

    assert "vector(" not in sql
    assert "creator_embedding" not in sql
