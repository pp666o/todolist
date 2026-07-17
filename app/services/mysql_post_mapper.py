"""Map raw MySQL post rows into canonical post domain models."""

import re
from datetime import datetime
from typing import Any, Mapping

from app.domain.post import PostUpsert


MYSQL_POST_SOURCE = "mysql_tiezi_geo_new"

_TAG_SEPARATOR = re.compile(r"[,，;；]+")


def _clean_required_text(value: Any, field_name: str) -> str:
    """Normalize a required text value."""
    text = "" if value is None else str(value).strip()

    if not text:
        raise ValueError(f"MySQL post field {field_name!r} is empty.")

    return text


def _clean_optional_text(value: Any) -> str | None:
    """Normalize an optional text value."""
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_nonnegative_int(value: Any) -> int:
    """Normalize a non-negative counter."""
    if value is None:
        return 0

    return max(0, int(value))


def _clean_optional_float(value: Any) -> float | None:
    """Normalize an optional numeric value."""
    if value is None:
        return None

    return float(value)


def normalize_tags(raw_tags: Any) -> list[str]:
    """Split, strip, and deduplicate raw MySQL tags."""
    if raw_tags is None:
        return []

    if isinstance(raw_tags, (list, tuple, set)):
        candidates = [str(value) for value in raw_tags]
    else:
        candidates = _TAG_SEPARATOR.split(str(raw_tags))

    result: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        tag = candidate.strip()

        if not tag or tag in seen:
            continue

        result.append(tag)
        seen.add(tag)

    return result


def normalize_post_times(
    created_at: Any,
    updated_at: Any,
) -> tuple[datetime | None, datetime | None]:
    """Prevent invalid source update times from preceding creation time."""
    normalized_created = (
        created_at if isinstance(created_at, datetime) else None
    )
    normalized_updated = (
        updated_at if isinstance(updated_at, datetime) else None
    )

    if normalized_created is None:
        return None, normalized_updated

    if (
        normalized_updated is None
        or normalized_updated < normalized_created
    ):
        normalized_updated = normalized_created

    return normalized_created, normalized_updated


def map_mysql_post_row(row: Mapping[str, Any]) -> PostUpsert:
    """Convert one tiezi_geo_new row into a canonical PostUpsert."""
    created_at, updated_at = normalize_post_times(
        row.get("createtime"),
        row.get("updatetime"),
    )

    visible_status = _clean_optional_text(row.get("visiblestatus"))

    return PostUpsert(
        source=MYSQL_POST_SOURCE,
        source_id=_clean_required_text(row.get("id"), "id"),
        title=_clean_required_text(row.get("title"), "title"),
        content=_clean_required_text(row.get("detail"), "detail"),
        category=_clean_required_text(
            row.get("typecategory"),
            "typecategory",
        ),
        tags=normalize_tags(row.get("tags")),
        latitude=_clean_optional_float(row.get("from_lat")),
        longitude=_clean_optional_float(row.get("from_lng")),
        country=_clean_optional_text(row.get("country")),
        province=_clean_optional_text(row.get("province")),
        city=_clean_optional_text(row.get("city")),
        district=_clean_optional_text(row.get("district")),
        address=_clean_optional_text(row.get("address")),
        likes=_clean_nonnegative_int(row.get("likes")),
        views=_clean_nonnegative_int(row.get("views")),
        marks=_clean_nonnegative_int(row.get("marks")),
        dislikes=_clean_nonnegative_int(row.get("dislikes")),
        ratescore=_clean_optional_float(row.get("ratescore")),
        visible_status=visible_status,
        owner_id=_clean_optional_text(row.get("owenerid")),
        created_at=created_at,
        updated_at=updated_at,
    )
