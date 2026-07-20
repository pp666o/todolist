"""Tests for the post synchronization audit tool."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import scripts.audit_post_data as audit_module


def make_snapshot(
    *,
    row_count: int = 3,
    source_ids: set[str] | None = None,
) -> dict[str, Any]:
    resolved_ids = source_ids or {"1", "2", "3"}

    return {
        "database": "source_db",
        "table": "source_posts",
        "source": audit_module.MYSQL_POST_SOURCE,
        "row_count": row_count,
        "distinct_source_ids": row_count,
        "min_source_id": 1,
        "max_source_id": 3,
        "min_created_at": "2024-01-01T00:00:00",
        "max_created_at": "2024-01-03T00:00:00",
        "min_updated_at": "2024-01-01T00:00:00",
        "max_updated_at": "2024-01-03T00:00:00",
        "embedded_count": 0,
        "non_numeric_source_id_count": 0,
        "quality": {
            key: 0
            for key in audit_module.QUALITY_COUNTERS
        },
        "coverage": {
            "coordinate_count": row_count,
            "distinct_country_count": 1,
            "distinct_province_count": 1,
            "distinct_city_count": 1,
            "distinct_district_count": 1,
            "distinct_city_district_count": 1,
            "empty_address_count": 0,
            "missing_created_at_count": 0,
            "missing_updated_at_count": 0,
            "updated_before_created_count": 0,
        },
        "categories": {
            "求助": 1,
            "问答": 1,
            "吐槽": 1,
        },
        "visible_statuses": {
            "1": 1,
            "2": 1,
            "3": 1,
        },
        "source_ids": resolved_ids,
        "issue_samples": [],
    }


def test_evaluate_audit_accepts_matching_snapshots() -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    errors, warnings = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert errors == []
    assert warnings == [
        "No synchronized posts currently have embeddings."
    ]


def test_evaluate_audit_reports_id_and_count_mismatches() -> None:
    mysql_snapshot = make_snapshot(
        source_ids={"1", "2", "3"},
    )
    postgres_snapshot = make_snapshot(
        row_count=3,
        source_ids={"1", "2", "4"},
    )

    errors, _ = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert any(
        "missing MySQL source IDs" in error
        and "'3'" in error
        for error in errors
    )
    assert any(
        "extra MySQL-derived source IDs" in error
        and "'4'" in error
        for error in errors
    )


def test_evaluate_audit_reports_quality_failures() -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    mysql_snapshot["quality"]["empty_title_count"] = 2
    postgres_snapshot["quality"]["invalid_latitude_count"] = 1

    errors, _ = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert "MySQL empty_title_count=2." in errors
    assert "PostgreSQL invalid_latitude_count=1." in errors


def test_evaluate_audit_reports_distribution_mismatch() -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    postgres_snapshot["categories"] = {
        "求助": 2,
        "问答": 1,
        "吐槽": 0,
    }

    errors, _ = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert any(
        "category distributions differ" in error
        for error in errors
    )


def test_run_audit_returns_zero_for_valid_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    monkeypatch.setattr(
        audit_module,
        "read_mysql_snapshot",
        lambda *, sample_size: mysql_snapshot,
    )

    async def fake_postgres_snapshot(
        *,
        sample_size: int,
    ) -> dict[str, Any]:
        return postgres_snapshot

    monkeypatch.setattr(
        audit_module,
        "read_postgres_snapshot",
        fake_postgres_snapshot,
    )

    exit_code = asyncio.run(
        audit_module.run_audit(sample_size=20)
    )

    assert exit_code == 0


def test_run_audit_returns_nonzero_for_invalid_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot(
        source_ids={"1", "2", "4"},
    )

    monkeypatch.setattr(
        audit_module,
        "read_mysql_snapshot",
        lambda *, sample_size: mysql_snapshot,
    )

    async def fake_postgres_snapshot(
        *,
        sample_size: int,
    ) -> dict[str, Any]:
        return postgres_snapshot

    monkeypatch.setattr(
        audit_module,
        "read_postgres_snapshot",
        fake_postgres_snapshot,
    )

    exit_code = asyncio.run(
        audit_module.run_audit(sample_size=20)
    )

    assert exit_code == 1


@pytest.mark.parametrize("sample_size", [0, 1001])
def test_parse_args_rejects_invalid_sample_size(
    monkeypatch: pytest.MonkeyPatch,
    sample_size: int,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit_post_data.py",
            "--sample-size",
            str(sample_size),
        ],
    )

    with pytest.raises(SystemExit):
        audit_module.parse_args()


def test_evaluate_audit_reports_coverage_mismatch() -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    postgres_snapshot["coverage"]["distinct_city_count"] = 2

    errors, _ = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert any(
        "coverage differs for distinct_city_count" in error
        for error in errors
    )


def test_evaluate_audit_warns_about_source_time_normalization() -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    mysql_snapshot["coverage"][
        "updated_before_created_count"
    ] = 5

    errors, warnings = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert errors == []
    assert any(
        "mapper normalizes these rows" in warning
        for warning in warnings
    )


def test_evaluate_audit_rejects_target_time_inversion() -> None:
    mysql_snapshot = make_snapshot()
    postgres_snapshot = make_snapshot()

    postgres_snapshot["coverage"][
        "updated_before_created_count"
    ] = 1

    errors, _ = audit_module.evaluate_audit(
        mysql_snapshot,
        postgres_snapshot,
        sample_size=20,
    )

    assert any(
        "updated_at values earlier than created_at" in error
        for error in errors
    )
