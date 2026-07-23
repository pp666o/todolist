"""PostgreSQL pg_trgm lexical-recall primitives."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from psycopg import AsyncConnection

from app.search.geo import haversine_km


MAX_LEXICAL_LIMIT = 2000
MAX_QUERY_LENGTH = 500
MAX_TEXT_TERMS = 24
MAX_TAG_TERMS = 32
MAX_OVERFETCH_FACTOR = 10.0
MAX_RADIUS_KM = 500.0

SUPPORTED_CATEGORIES = {
    "求助",
    "问答",
    "吐槽",
}

_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9]+|[\u3400-\u4DBF\u4E00-\u9FFF]+"
)

_LOW_INFORMATION_PHRASES = (
    "为什么",
    "应该",
    "怎么",
    "如何",
    "什么",
    "哪些",
    "需要",
    "可以",
    "是否",
    "能否",
    "附近",
    "有人",
    "问题",
    "处理",
    "方面",
    "时候",
    "一下",
    "还是",
    "请问",
    "求助",
    "吐槽",
    "里的",
    "这个",
    "那个",
    "一种",
    "一些",
    "一个",
    "和",
    "与",
    "及",
    "的",
    "了",
    "在",
    "对",
    "为",
    "吗",
    "呢",
)

_LOW_INFORMATION_SPLIT_PATTERN = re.compile(
    "|".join(
        re.escape(phrase)
        for phrase in sorted(
            _LOW_INFORMATION_PHRASES,
            key=len,
            reverse=True,
        )
    )
)

_PUNCTUATION_PATTERN = re.compile(
    r"[\\s?？!！,，。.;；:：、/\\\\|()"
    r"\\[\\]{}<>《》“”\\\"'`~…—_-]+"
)


@dataclass(frozen=True)
class LexicalQueryTerms:
    """Normalized lexical terms used for PostgreSQL recall."""

    normalized_query: str
    text_terms: tuple[str, ...]
    tag_terms: tuple[str, ...]


class LexicalCandidate(TypedDict):
    """One lightweight PostgreSQL lexical candidate."""

    source: str
    source_id: str

    lexical_score: float
    title_score: float
    content_score: float
    tag_score: float

    latitude: float | None
    longitude: float | None
    distance_km: float | None


def _ordered_unique(
    values: Sequence[str],
    *,
    limit: int,
) -> tuple[str, ...]:
    """Deduplicate strings while retaining their first order."""

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = value.strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

        if len(result) >= limit:
            break

    return tuple(result)


def _contains_cjk(value: str) -> bool:
    """Return whether a token contains a CJK character."""

    return any(
        "\u3400" <= character <= "\u9fff"
        for character in value
    )


def extract_lexical_query_terms(
    query: str,
) -> LexicalQueryTerms:
    """Extract bounded, Chinese-friendly lexical query terms.

    Low-information phrases are treated as segmentation boundaries.
    Text recall uses terms with at least three characters so pg_trgm
    can use its indexes effectively. Tag recall uses complete segments
    and non-overlapping two-character chunks.
    """

    if not isinstance(query, str):
        raise TypeError("query must be a string")

    normalized_query = unicodedata.normalize(
        "NFKC",
        query,
    )
    normalized_query = " ".join(
        normalized_query.lower().split()
    )

    if not normalized_query:
        raise ValueError(
            "query must not be blank"
        )

    if len(normalized_query) > MAX_QUERY_LENGTH:
        raise ValueError(
            "query must be no longer than "
            f"{MAX_QUERY_LENGTH} characters"
        )

    segmented_query = _PUNCTUATION_PATTERN.sub(
        " ",
        normalized_query,
    )
    segmented_query = (
        _LOW_INFORMATION_SPLIT_PATTERN.sub(
            " ",
            segmented_query,
        )
    )

    tokens = _TOKEN_PATTERN.findall(
        segmented_query
    )

    text_candidates: list[str] = []
    tag_candidates: list[str] = []

    for token in tokens:
        if not _contains_cjk(token):
            text_candidates.append(token)
            tag_candidates.append(token)
            continue

        token_length = len(token)

        if token_length >= 2:
            if token_length <= 8:
                tag_candidates.append(token)

            # Chinese business tags are commonly two-character words.
            # Non-overlapping chunks avoid noisy cross-word bigrams
            # such as "序开" from "程序开发".
            for index in range(
                0,
                token_length - 1,
                2,
            ):
                tag_candidates.append(
                    token[index : index + 2]
                )

        if token_length >= 3:
            # Prefer the complete meaningful segment.
            text_candidates.append(token)

            # Add bounded local substrings for trigram-indexed recall.
            for size in (4, 3):
                if token_length < size:
                    continue

                for index in range(
                    token_length - size + 1
                ):
                    text_candidates.append(
                        token[
                            index : index + size
                        ]
                    )

    text_terms = _ordered_unique(
        text_candidates,
        limit=MAX_TEXT_TERMS,
    )
    tag_terms = _ordered_unique(
        tag_candidates,
        limit=MAX_TAG_TERMS,
    )

    if not text_terms:
        fallback = "".join(tokens).strip()

        text_terms = (
            fallback or normalized_query,
        )

    if not tag_terms:
        fallback = "".join(tokens).strip()

        tag_terms = (
            fallback or normalized_query,
        )

    return LexicalQueryTerms(
        normalized_query=normalized_query,
        text_terms=text_terms,
        tag_terms=tag_terms,
    )


def _validate_optional_range(
    *,
    name: str,
    minimum: float | None,
    maximum: float | None,
    lower_bound: float,
    upper_bound: float,
) -> None:
    """Validate one optional inclusive numeric range."""

    if (minimum is None) != (maximum is None):
        raise ValueError(
            f"{name} minimum and maximum "
            "must be provided together"
        )

    if minimum is None or maximum is None:
        return

    if not lower_bound <= minimum <= upper_bound:
        raise ValueError(
            f"{name} minimum must be between "
            f"{lower_bound} and {upper_bound}"
        )

    if not lower_bound <= maximum <= upper_bound:
        raise ValueError(
            f"{name} maximum must be between "
            f"{lower_bound} and {upper_bound}"
        )

    if minimum > maximum:
        raise ValueError(
            f"{name} minimum cannot exceed maximum"
        )


def validate_lexical_search_parameters(
    *,
    category: str | None,
    min_latitude: float | None,
    max_latitude: float | None,
    min_longitude: float | None,
    max_longitude: float | None,
    latitude: float | None,
    longitude: float | None,
    radius_km: float | None,
    overfetch_factor: float,
    limit: int,
) -> None:
    """Validate lexical-recall business parameters."""

    if not 1 <= limit <= MAX_LEXICAL_LIMIT:
        raise ValueError(
            "limit must be between "
            f"1 and {MAX_LEXICAL_LIMIT}"
        )

    if (
        category is not None
        and category not in SUPPORTED_CATEGORIES
    ):
        raise ValueError(
            f"Unsupported post category: {category!r}"
        )

    _validate_optional_range(
        name="latitude",
        minimum=min_latitude,
        maximum=max_latitude,
        lower_bound=-90.0,
        upper_bound=90.0,
    )
    _validate_optional_range(
        name="longitude",
        minimum=min_longitude,
        maximum=max_longitude,
        lower_bound=-180.0,
        upper_bound=180.0,
    )

    has_latitude = latitude is not None
    has_longitude = longitude is not None

    if has_latitude != has_longitude:
        raise ValueError(
            "latitude and longitude must be "
            "provided together"
        )

    if (
        latitude is not None
        and not -90.0 <= latitude <= 90.0
    ):
        raise ValueError(
            "latitude must be between -90 and 90"
        )

    if (
        longitude is not None
        and not -180.0 <= longitude <= 180.0
    ):
        raise ValueError(
            "longitude must be between -180 and 180"
        )

    if radius_km is not None:
        if not has_latitude:
            raise ValueError(
                "radius_km requires latitude "
                "and longitude"
            )

        if not 0.0 < radius_km <= MAX_RADIUS_KM:
            raise ValueError(
                "radius_km must be greater than zero "
                f"and no more than {MAX_RADIUS_KM}"
            )

    if not (
        1.0
        <= overfetch_factor
        <= MAX_OVERFETCH_FACTOR
    ):
        raise ValueError(
            "overfetch_factor must be between "
            f"1 and {MAX_OVERFETCH_FACTOR}"
        )


def _build_match_count_expression(
    field_sql: str,
    *,
    parameter_names: Sequence[str],
) -> str:
    """Build a numeric substring-match count expression."""

    if not parameter_names:
        return "0.0"

    expressions = [
        (
            "CASE WHEN "
            f"{field_sql} ILIKE "
            f"%({parameter_name})s "
            "THEN 1.0 ELSE 0.0 END"
        )
        for parameter_name in parameter_names
    ]

    return (
        "("
        + " + ".join(expressions)
        + ")"
    )


async def lexical_search_filtered(
    connection: AsyncConnection[dict[str, Any]],
    *,
    query: str,
    category: str | None = None,
    visible_statuses: Sequence[str] | None = None,
    city: str | None = None,
    district: str | None = None,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    overfetch_factor: float = 4.0,
    limit: int,
) -> list[LexicalCandidate]:
    """Recall posts through bounded trigram and tag routes.

    Title, content, and tag routes first produce independently bounded
    candidate ID sets. Expensive coverage scoring is then calculated
    only for their small union rather than every broad tag match.
    """

    terms = extract_lexical_query_terms(
        query
    )

    validate_lexical_search_parameters(
        category=category,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        overfetch_factor=overfetch_factor,
        limit=limit,
    )

    normalized_statuses = list(
        dict.fromkeys(
            status.strip()
            for status in (
                visible_statuses or ()
            )
            if status and status.strip()
        )
    )

    normalized_city = (
        city.strip()
        if city and city.strip()
        else None
    )
    normalized_district = (
        district.strip()
        if district and district.strip()
        else None
    )

    scan_limit = min(
        MAX_LEXICAL_LIMIT,
        max(
            limit,
            math.ceil(
                limit * overfetch_factor
            ),
        ),
    )
    final_scan_limit = min(
        MAX_LEXICAL_LIMIT,
        scan_limit * 3,
    )

    parameters: dict[str, Any] = {
        "tag_terms": list(
            terms.tag_terms
        ),
        "text_term_count": float(
            len(terms.text_terms)
        ),
        "tag_score_denominator": float(
            max(
                1,
                min(
                    2,
                    len(terms.tag_terms),
                ),
            )
        ),
        "scan_limit": scan_limit,
        "final_scan_limit": final_scan_limit,
    }

    pattern_parameter_names: list[str] = []

    for index, text_term in enumerate(
        terms.text_terms
    ):
        parameter_name = (
            f"pattern_{index}"
        )
        pattern_parameter_names.append(
            parameter_name
        )
        parameters[
            parameter_name
        ] = f"%{text_term}%"

    title_matches = [
        (
            "p.title ILIKE "
            f"%({parameter_name})s"
        )
        for parameter_name
        in pattern_parameter_names
    ]
    content_matches = [
        (
            "p.content ILIKE "
            f"%({parameter_name})s"
        )
        for parameter_name
        in pattern_parameter_names
    ]

    title_match_sql = (
        "("
        + " OR ".join(title_matches)
        + ")"
    )
    content_match_sql = (
        "("
        + " OR ".join(content_matches)
        + ")"
    )

    title_match_count_sql = (
        _build_match_count_expression(
            "p.title",
            parameter_names=(
                pattern_parameter_names
            ),
        )
    )
    content_match_count_sql = (
        _build_match_count_expression(
            "p.content",
            parameter_names=(
                pattern_parameter_names
            ),
        )
    )

    business_conditions: list[str] = []

    if category is not None:
        business_conditions.append(
            "p.category = %(category)s"
        )
        parameters["category"] = category

    if normalized_statuses:
        business_conditions.append(
            "p.visible_status = "
            "ANY(%(visible_statuses)s)"
        )
        parameters[
            "visible_statuses"
        ] = normalized_statuses

    if normalized_city:
        business_conditions.append(
            "p.city = %(city)s"
        )
        parameters["city"] = normalized_city

    if normalized_district:
        business_conditions.append(
            "p.district = %(district)s"
        )
        parameters[
            "district"
        ] = normalized_district

    if (
        min_latitude is not None
        and max_latitude is not None
    ):
        business_conditions.append(
            "p.latitude BETWEEN "
            "%(min_latitude)s "
            "AND %(max_latitude)s"
        )
        parameters[
            "min_latitude"
        ] = min_latitude
        parameters[
            "max_latitude"
        ] = max_latitude

    if (
        min_longitude is not None
        and max_longitude is not None
    ):
        business_conditions.append(
            "p.longitude BETWEEN "
            "%(min_longitude)s "
            "AND %(max_longitude)s"
        )
        parameters[
            "min_longitude"
        ] = min_longitude
        parameters[
            "max_longitude"
        ] = max_longitude

    business_where_sql = (
        "\n                    AND ".join(
            business_conditions
        )
        if business_conditions
        else "TRUE"
    )

    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            WITH title_recall AS (
                SELECT
                    p.id
                FROM posts AS p
                WHERE
                    {business_where_sql}
                    AND {title_match_sql}
                ORDER BY
                    {title_match_count_sql} DESC,
                    p.updated_at DESC NULLS LAST,
                    p.id DESC
                LIMIT %(scan_limit)s
            ),
            content_recall AS (
                SELECT
                    p.id
                FROM posts AS p
                WHERE
                    {business_where_sql}
                    AND {content_match_sql}
                ORDER BY
                    {content_match_count_sql} DESC,
                    p.updated_at DESC NULLS LAST,
                    p.id DESC
                LIMIT %(scan_limit)s
            ),
            tag_recall AS (
                SELECT
                    p.id
                FROM posts AS p

                LEFT JOIN LATERAL (
                    SELECT
                        count(*)::double precision
                            AS match_count
                    FROM unnest(p.tags)
                        AS tag(value)
                    WHERE
                        tag.value = ANY(
                            %(tag_terms)s::text[]
                        )
                ) AS tag_matches
                    ON TRUE

                WHERE
                    {business_where_sql}
                    AND p.tags &&
                        %(tag_terms)s::text[]

                ORDER BY
                    tag_matches.match_count DESC,
                    p.updated_at DESC NULLS LAST,
                    p.id DESC

                LIMIT %(scan_limit)s
            ),
            candidate_ids AS (
                SELECT id FROM title_recall
                UNION
                SELECT id FROM content_recall
                UNION
                SELECT id FROM tag_recall
            ),
            matched AS (
                SELECT
                    p.id,
                    p.source,
                    p.source_id,
                    p.latitude,
                    p.longitude,
                    p.updated_at,

                    LEAST(
                        1.0,
                        {title_match_count_sql}
                        / %(text_term_count)s
                    )::double precision
                        AS title_score,

                    LEAST(
                        1.0,
                        0.8
                        * {content_match_count_sql}
                        / %(text_term_count)s
                    )::double precision
                        AS content_score,

                    LEAST(
                        1.0,
                        COALESCE(
                            tag_matches.match_count,
                            0
                        )
                        / %(tag_score_denominator)s
                    )::double precision
                        AS tag_score

                FROM posts AS p

                JOIN candidate_ids AS candidates
                  ON candidates.id = p.id

                LEFT JOIN LATERAL (
                    SELECT
                        count(*)::double precision
                            AS match_count
                    FROM unnest(p.tags)
                        AS tag(value)
                    WHERE
                        tag.value = ANY(
                            %(tag_terms)s::text[]
                        )
                ) AS tag_matches
                    ON TRUE
            ),
            scored AS (
                SELECT
                    *,
                    (
                        0.55 * title_score
                        + 0.30 * tag_score
                        + 0.15 * content_score
                    )::double precision
                        AS lexical_score
                FROM matched
            )
            SELECT
                source,
                source_id,
                latitude,
                longitude,
                lexical_score,
                title_score,
                content_score,
                tag_score
            FROM scored
            ORDER BY
                lexical_score DESC,
                title_score DESC,
                tag_score DESC,
                content_score DESC,
                updated_at DESC NULLS LAST,
                id DESC
            LIMIT %(final_scan_limit)s
            """,
            parameters,
        )

        rows = await cursor.fetchall()

    candidates: list[
        LexicalCandidate
    ] = []

    for row in rows:
        row_latitude = (
            float(row["latitude"])
            if row["latitude"] is not None
            else None
        )
        row_longitude = (
            float(row["longitude"])
            if row["longitude"] is not None
            else None
        )

        distance_km: float | None = None

        if radius_km is not None:
            if (
                latitude is None
                or longitude is None
                or row_latitude is None
                or row_longitude is None
            ):
                continue

            distance_km = haversine_km(
                latitude,
                longitude,
                row_latitude,
                row_longitude,
            )

            if distance_km > radius_km:
                continue

        candidates.append(
            LexicalCandidate(
                source=str(row["source"]),
                source_id=str(
                    row["source_id"]
                ),
                lexical_score=float(
                    row["lexical_score"]
                ),
                title_score=float(
                    row["title_score"]
                ),
                content_score=float(
                    row["content_score"]
                ),
                tag_score=float(
                    row["tag_score"]
                ),
                latitude=row_latitude,
                longitude=row_longitude,
                distance_km=distance_km,
            )
        )

        if len(candidates) >= limit:
            break

    return candidates
