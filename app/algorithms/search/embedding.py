"""Pure embedding text and vector contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


MODEL_DIMENSION = 512

QUERY_INSTRUCTION = (
    "为这个句子生成表示以用于检索相关文章："
)


def build_post_text(
    row: Mapping[str, Any],
) -> str:
    """Build canonical document text for post embeddings."""

    title = str(
        row.get("title") or ""
    ).strip()

    category = str(
        row.get("category") or ""
    ).strip()

    content = str(
        row.get("content") or ""
    ).strip()

    raw_tags = row.get("tags") or []

    tags = [
        str(tag).strip()
        for tag in raw_tags
        if str(tag).strip()
    ]

    parts: list[str] = []

    if title:
        parts.append(
            f"标题：{title}"
        )

    if category:
        parts.append(
            f"类别：{category}"
        )

    if tags:
        parts.append(
            f"标签：{' '.join(tags)}"
        )

    if content:
        parts.append(
            f"正文：{content}"
        )

    if not parts:
        raise ValueError(
            f"Post {row.get('id')} "
            "has no encodable text."
        )

    return "\n".join(parts)


def build_query_text(
    query: str,
) -> str:
    """Build canonical BGE query text."""

    if not isinstance(query, str):
        raise TypeError(
            "query must be a string"
        )

    normalized_query = (
        query.strip()
    )

    if not normalized_query:
        raise ValueError(
            "query must not be blank"
        )

    return (
        QUERY_INSTRUCTION
        + normalized_query
    )


def validate_embedding_batch(
    embeddings: np.ndarray,
    *,
    expected_rows: int,
) -> np.ndarray:
    """Validate shape, finite values and L2 normalization."""

    vectors = np.asarray(
        embeddings,
        dtype=np.float32,
    )

    expected_shape = (
        expected_rows,
        MODEL_DIMENSION,
    )

    if vectors.shape != expected_shape:
        raise ValueError(
            "Expected embedding shape "
            f"{expected_shape}, "
            f"got {vectors.shape}."
        )

    if not np.isfinite(
        vectors
    ).all():
        raise ValueError(
            "Embedding batch contains "
            "NaN or infinite values."
        )

    norms = np.linalg.norm(
        vectors,
        axis=1,
    )

    if not np.allclose(
        norms,
        1.0,
        atol=1e-4,
    ):
        raise ValueError(
            "Embedding batch is not "
            "L2-normalized. "
            "Observed norm range: "
            f"{float(norms.min()):.6f}–"
            f"{float(norms.max()):.6f}"
        )

    return norms