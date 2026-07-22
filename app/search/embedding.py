"""Shared embedding utilities for offline and online retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


MODEL_DIMENSION = 512
DEFAULT_BATCH_SIZE = 32
DEFAULT_MODEL_PATH = Path(
    "/workspace/models/bge-small-zh-v1.5"
)

QUERY_INSTRUCTION = (
    "为这个句子生成表示以用于检索相关文章："
)


def build_post_text(row: Mapping[str, Any]) -> str:
    """Build the canonical document text used for post embeddings."""

    title = str(row.get("title") or "").strip()
    category = str(row.get("category") or "").strip()
    content = str(row.get("content") or "").strip()

    raw_tags = row.get("tags") or []
    tags = [
        str(tag).strip()
        for tag in raw_tags
        if str(tag).strip()
    ]

    parts: list[str] = []

    if title:
        parts.append(f"标题：{title}")

    if category:
        parts.append(f"类别：{category}")

    if tags:
        parts.append(f"标签：{' '.join(tags)}")

    if content:
        parts.append(f"正文：{content}")

    if not parts:
        raise ValueError(
            f"Post {row.get('id')} has no encodable text."
        )

    return "\n".join(parts)


def build_query_text(query: str) -> str:
    """Build the canonical BGE query text with retrieval instruction."""

    if not isinstance(query, str):
        raise TypeError("query must be a string")

    normalized_query = query.strip()

    if not normalized_query:
        raise ValueError("query must not be blank")

    return QUERY_INSTRUCTION + normalized_query


def embedding_to_pgvector(
    embedding: Sequence[float] | np.ndarray,
) -> str:
    """Serialize one embedding into pgvector text format."""

    vector = np.asarray(
        embedding,
        dtype=np.float32,
    )

    if vector.shape != (MODEL_DIMENSION,):
        raise ValueError(
            "Expected one embedding with shape "
            f"({MODEL_DIMENSION},), got {vector.shape}."
        )

    if not np.isfinite(vector).all():
        raise ValueError(
            "Embedding contains NaN or infinite values."
        )

    return (
        "["
        + ",".join(
            format(float(value), ".9g")
            for value in vector
        )
        + "]"
    )


def validate_embedding_batch(
    embeddings: np.ndarray,
    *,
    expected_rows: int,
) -> np.ndarray:
    """Validate embedding shape, finite values, and L2 normalization."""

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
            f"Expected embedding shape {expected_shape}, "
            f"got {vectors.shape}."
        )

    if not np.isfinite(vectors).all():
        raise ValueError(
            "Embedding batch contains NaN or infinite values."
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
            "Embedding batch is not L2-normalized. "
            f"Observed norm range: "
            f"{float(norms.min()):.6f}–"
            f"{float(norms.max()):.6f}"
        )

    return norms


def resolve_device(requested_device: str) -> str:
    """Resolve auto/cpu/cuda into an available Torch device."""

    import torch

    if requested_device not in {
        "auto",
        "cpu",
        "cuda",
    }:
        raise ValueError(
            "device must be one of: auto, cpu, cuda"
        )

    if requested_device == "auto":
        return (
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

    if (
        requested_device == "cuda"
        and not torch.cuda.is_available()
    ):
        raise RuntimeError(
            "CUDA was requested, but Torch reports "
            "that CUDA is unavailable."
        )

    return requested_device


def load_model(
    model_path: Path,
    *,
    device: str,
) -> Any:
    """Load and validate the local Sentence Transformer model."""

    from sentence_transformers import (
        SentenceTransformer,
    )

    model = SentenceTransformer(
        str(model_path),
        device=device,
    )

    dimension = model.get_embedding_dimension()

    if dimension != MODEL_DIMENSION:
        raise RuntimeError(
            f"Model dimension is {dimension}; "
            f"database schema expects {MODEL_DIMENSION}."
        )

    return model


def encode_documents(
    model: Any,
    texts: Sequence[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> np.ndarray:
    """Encode document texts without adding the query instruction."""

    normalized_texts = [
        str(text).strip()
        for text in texts
    ]

    if not normalized_texts:
        raise ValueError(
            "at least one document text is required"
        )

    if any(not text for text in normalized_texts):
        raise ValueError(
            "document texts must not contain blank values"
        )

    document_encoder = getattr(
        model,
        "encode_document",
        None,
    )

    if callable(document_encoder):
        embeddings = document_encoder(
            normalized_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    else:
        embeddings = model.encode(
            normalized_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    vectors = np.asarray(
        embeddings,
        dtype=np.float32,
    )

    validate_embedding_batch(
        vectors,
        expected_rows=len(normalized_texts),
    )

    return vectors


def encode_queries(
    model: Any,
    queries: Sequence[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> np.ndarray:
    """Encode queries using the explicit canonical BGE instruction."""

    if isinstance(queries, str):
        raise TypeError(
            "queries must be a sequence of strings, "
            "not one string"
        )

    query_texts = [
        build_query_text(query)
        for query in queries
    ]

    if not query_texts:
        raise ValueError(
            "at least one query is required"
        )

    embeddings = model.encode(
        query_texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    vectors = np.asarray(
        embeddings,
        dtype=np.float32,
    )

    validate_embedding_batch(
        vectors,
        expected_rows=len(query_texts),
    )

    return vectors


def encode_query(
    model: Any,
    query: str,
) -> np.ndarray:
    """Encode one query and return one normalized 512-D vector."""

    return encode_queries(
        model,
        [query],
        batch_size=1,
    )[0]
