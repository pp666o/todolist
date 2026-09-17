"""Pure lexical-search query rules."""

from __future__ import annotations

import re
import unicodedata

from collections.abc import Sequence
from dataclasses import dataclass


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
    r"[\s?？!！,，。.;；:：、/\\|()"
    r"\[\]{}<>《》“”\"'`~…—_-]+"
)


@dataclass(frozen=True)
class LexicalQueryTerms:
    """Normalized lexical terms used for recall."""

    normalized_query: str
    text_terms: tuple[str, ...]
    tag_terms: tuple[str, ...]


def _ordered_unique(
    values: Sequence[str],
    *,
    limit: int,
) -> tuple[str, ...]:
    """Deduplicate strings while retaining their order."""

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = value.strip()

        if (
            not normalized
            or normalized in seen
        ):
            continue

        seen.add(normalized)
        result.append(normalized)

        if len(result) >= limit:
            break

    return tuple(result)


def _contains_cjk(
    value: str,
) -> bool:
    """Return whether a token contains a CJK character."""

    return any(
        "\u3400" <= character <= "\u9fff"
        for character in value
    )


def extract_lexical_query_terms(
    query: str,
) -> LexicalQueryTerms:
    """Extract bounded Chinese-friendly lexical query terms."""

    if not isinstance(query, str):
        raise TypeError(
            "query must be a string"
        )

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

    segmented_query = (
        _PUNCTUATION_PATTERN.sub(
            " ",
            normalized_query,
        )
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
                tag_candidates.append(
                    token
                )

            for index in range(
                0,
                token_length - 1,
                2,
            ):
                tag_candidates.append(
                    token[
                        index : index + 2
                    ]
                )

        if token_length >= 3:
            text_candidates.append(
                token
            )

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
        fallback = "".join(
            tokens
        ).strip()

        text_terms = (
            fallback
            or normalized_query,
        )

    if not tag_terms:
        fallback = "".join(
            tokens
        ).strip()

        tag_terms = (
            fallback
            or normalized_query,
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

    if (
        (minimum is None)
        != (maximum is None)
    ):
        raise ValueError(
            f"{name} minimum and maximum "
            "must be provided together"
        )

    if (
        minimum is None
        or maximum is None
    ):
        return

    if not (
        lower_bound
        <= minimum
        <= upper_bound
    ):
        raise ValueError(
            f"{name} minimum must be between "
            f"{lower_bound} and {upper_bound}"
        )

    if not (
        lower_bound
        <= maximum
        <= upper_bound
    ):
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

    if not (
        1
        <= limit
        <= MAX_LEXICAL_LIMIT
    ):
        raise ValueError(
            "limit must be between "
            f"1 and {MAX_LEXICAL_LIMIT}"
        )

    if (
        category is not None
        and category
        not in SUPPORTED_CATEGORIES
    ):
        raise ValueError(
            f"Unsupported post category: "
            f"{category!r}"
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

    has_latitude = (
        latitude is not None
    )

    has_longitude = (
        longitude is not None
    )

    if has_latitude != has_longitude:
        raise ValueError(
            "latitude and longitude must "
            "be provided together"
        )

    if (
        latitude is not None
        and not -90.0
        <= latitude
        <= 90.0
    ):
        raise ValueError(
            "latitude must be between "
            "-90 and 90"
        )

    if (
        longitude is not None
        and not -180.0
        <= longitude
        <= 180.0
    ):
        raise ValueError(
            "longitude must be between "
            "-180 and 180"
        )

    if radius_km is not None:
        if not has_latitude:
            raise ValueError(
                "radius_km requires latitude "
                "and longitude"
            )

        if not (
            0.0
            < radius_km
            <= MAX_RADIUS_KM
        ):
            raise ValueError(
                "radius_km must be greater "
                "than zero and no more than "
                f"{MAX_RADIUS_KM}"
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