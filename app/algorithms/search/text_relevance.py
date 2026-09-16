from collections.abc import Mapping
from typing import Any
import unicodedata
def _normalize_text(value: str | None) -> str:
    """Normalize text for lightweight lexical matching."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.lower().split())


def _character_bigrams(value: str) -> set[str]:
    """Return character bigrams for Chinese-friendly rough matching."""
    compact = value.replace(" ", "")

    if not compact:
        return set()

    if len(compact) == 1:
        return {compact}

    return {
        compact[index : index + 2]
        for index in range(len(compact) - 1)
    }


def _field_match_score(query: str, field: str) -> float:
    """Calculate one normalized lexical field score."""
    if not query or not field:
        return 0.0

    if query == field:
        return 1.0

    if query in field:
        return 0.9

    query_tokens = {
        token
        for token in query.split()
        if token
    }

    token_coverage = 0.0

    if query_tokens:
        matched_tokens = sum(
            1
            for token in query_tokens
            if token in field
        )
        token_coverage = matched_tokens / len(query_tokens)

    query_bigrams = _character_bigrams(query)
    field_bigrams = _character_bigrams(field)

    bigram_coverage = 0.0

    if query_bigrams:
        bigram_coverage = (
            len(query_bigrams & field_bigrams)
            / len(query_bigrams)
        )

    return min(
        1.0,
        max(
            0.8 * token_coverage,
            0.7 * bigram_coverage,
        ),
    )


def calculate_text_score(
    query: str,
    row: Mapping[str, Any],
) -> tuple[float, list[str], list[str]]:
    """Calculate title/tag/content lexical relevance."""
    normalized_query = _normalize_text(query)
    normalized_title = _normalize_text(row.get("title"))
    normalized_content = _normalize_text(row.get("content"))

    tags = row.get("tags") or []
    normalized_tags = _normalize_text(" ".join(tags))

    title_score = _field_match_score(
        normalized_query,
        normalized_title,
    )
    tag_score = _field_match_score(
        normalized_query,
        normalized_tags,
    )
    content_score = _field_match_score(
        normalized_query,
        normalized_content,
    )

    text_score = (
        0.55 * title_score
        + 0.30 * tag_score
        + 0.15 * content_score
    )

    recall_sources: list[str] = []
    reasons: list[str] = []

    if title_score > 0:
        recall_sources.append("keyword_title")
        reasons.append("标题与搜索词相关")

    if tag_score > 0:
        recall_sources.append("keyword_tags")
        reasons.append("标签与搜索词相关")

    if content_score > 0:
        recall_sources.append("keyword_content")
        reasons.append("正文与搜索词相关")

    return (
        min(1.0, max(0.0, text_score)),
        recall_sources,
        reasons,
    )

