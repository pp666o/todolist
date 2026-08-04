"""Map raw MySQL post rows into canonical post domain models."""

import re
from datetime import datetime
from typing import Any, Mapping

from app.domain.post import PostUpsert
from app.infrastructure.mysql_source import get_mysql_source_settings


MYSQL_POST_SOURCE = "mysql_tiezi_geo_new"
_POST_SOURCE_PREFIX = "mysql_"
_TAG_SEPARATOR = re.compile(r"[,，;；]+")


def get_mysql_post_source() -> str:
    """Derive the canonical remote source name from the configured MySQL table."""
    settings = get_mysql_source_settings()
    table_name = settings.table.strip()
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", table_name)

    if not normalized:
        normalized = MYSQL_POST_SOURCE

    if normalized.startswith(_POST_SOURCE_PREFIX):
        source = normalized
    else:
        source = f"{_POST_SOURCE_PREFIX}{normalized}"

    return source[:64]


def _first_available(
    row: Mapping[str, Any],
    keys: tuple[str, ...],
    default: Any = None,
) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


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


def _normalize_category(value: Any) -> str:
    text = _clean_optional_text(value)

    if not text:
        return "求助"

    normalized = text.strip()

    if normalized in {"求助", "问答", "吐槽"}:
        return normalized

    if "问" in normalized:
        return "问答"

    if "吐" in normalized or "抱怨" in normalized:
        return "吐槽"

    return "求助"


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


def map_mysql_post_row(
    row: Mapping[str, Any],
    source: str | None = None,
) -> PostUpsert:
    """Convert one remote MySQL row into a canonical PostUpsert."""
    source = source or get_mysql_post_source()
    created_at, updated_at = normalize_post_times(
        _first_available(row, ("createtime", "created_at", "create_time", "ctime")),
        _first_available(row, ("updatetime", "updated_at", "update_time")),
    )

    title = _clean_optional_text(
        _first_available(
            row,
            (
                "title",
                "subject",
                "topic",
                "weibo_title",
                "note_title",
            ),
        )
    )
    content = _clean_optional_text(
        _first_available(
            row,
            (
                "detail",
                "content",
                "body",
                "text",
                "weibo_content",
            ),
        )
    )

    if not title and content:
        title = content[:64]

    if not content and title:
        content = title

    if not title:
        title = "帖子"

    if not content:
        content = title

    visible_status = _clean_optional_text(
        _first_available(
            row,
            ("visiblestatus", "visible_status", "status"),
        )
    )

    return PostUpsert(
        source=source,
        source_id=_clean_required_text(
            _first_available(
                row,
                (
                    "id",
                    "source_id",
                    "post_id",
                    "weibo_id",
                ),
            ),
            "source_id",
        ),
        title=title,
        content=content,
        category=_normalize_category(
            _first_available(
                row,
                (
                    "typecategory",
                    "category",
                    "post_category",
                    "topic",
                    "category_name",
                ),
            )
        ),
        tags=normalize_tags(
            _first_available(
                row,
                ("tags", "tag", "keywords", "topics"),
            )
        ),
        latitude=_clean_optional_float(
            _first_available(
                row,
                ("from_lat", "latitude", "lat"),
            )
        ),
        longitude=_clean_optional_float(
            _first_available(
                row,
                ("from_lng", "longitude", "lng"),
            )
        ),
        country=_clean_optional_text(
            _first_available(
                row,
                ("country",),
            )
        ),
        province=_clean_optional_text(
            _first_available(
                row,
                ("province",),
            )
        ),
        city=_clean_optional_text(
            _first_available(
                row,
                ("city",),
            )
        ),
        district=_clean_optional_text(
            _first_available(
                row,
                ("district",),
            )
        ),
        address=_clean_optional_text(
            _first_available(
                row,
                ("address",),
            )
        ),
        likes=_clean_nonnegative_int(
            _first_available(
                row,
                ("likes", "like_count", "likes_count"),
            )
        ),
        views=_clean_nonnegative_int(
            _first_available(
                row,
                ("views", "view_count", "views_count"),
            )
        ),
        marks=_clean_nonnegative_int(
            _first_available(
                row,
                ("marks", "mark_count", "marks_count"),
            )
        ),
        dislikes=_clean_nonnegative_int(
            _first_available(
                row,
                ("dislikes", "dislike_count", "dislikes_count"),
            )
        ),
        ratescore=_clean_optional_float(
            _first_available(
                row,
                ("ratescore", "rate_score", "rating"),
            )
        ),
        visible_status=visible_status,
        owner_id=_clean_optional_text(
            _first_available(
                row,
                (
                    "owenerid",
                    "ownerid",
                    "user_id",
                    "author_id",
                    "creator_id",
                ),
            )
        ),
        created_at=created_at,
        updated_at=updated_at,
    )
