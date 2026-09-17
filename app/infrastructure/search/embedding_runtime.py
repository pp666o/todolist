"""Embedding model runtime."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
import numpy as np

from app.algorithms.search.embedding import (
    MODEL_DIMENSION,
    build_query_text,
    validate_embedding_batch,
)


DEFAULT_BATCH_SIZE = 32

DEFAULT_MODEL_PATH = Path(
    "/workspace/models/bge-small-zh-v1.5"
)


def resolve_device(
    requested_device: str,
) -> str:
    """Resolve auto/cpu/cuda into an available Torch device."""

    if requested_device not in {
        "auto",
        "cpu",
        "cuda",
    }:
        raise ValueError(
            "device must be one of: "
            "auto, cpu, cuda"
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
            "CUDA was requested, "
            "but Torch reports that "
            "CUDA is unavailable."
        )

    return requested_device


def load_model(
    model_path: Path,
    *,
    device: str,
) -> Any:
    """Load the local Sentence Transformer model."""

    from sentence_transformers import (
        SentenceTransformer,
    )

    model = SentenceTransformer(
        str(model_path),
        device=device,
    )

    dimension = (
        model.get_embedding_dimension()
    )

    if dimension != MODEL_DIMENSION:
        raise RuntimeError(
            f"Model dimension is {dimension}; "
            "database schema expects "
            f"{MODEL_DIMENSION}."
        )

    return model


def encode_documents(
    model: Any,
    texts: Sequence[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> np.ndarray:
    """Encode document texts."""

    normalized_texts = [
        str(text).strip()
        for text in texts
    ]

    if not normalized_texts:
        raise ValueError(
            "at least one document "
            "text is required"
        )

    if any(
        not text
        for text in normalized_texts
    ):
        raise ValueError(
            "document texts must not "
            "contain blank values"
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
        expected_rows=len(
            normalized_texts
        ),
    )

    return vectors


def encode_queries(
    model: Any,
    queries: Sequence[str],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> np.ndarray:
    """Encode retrieval queries."""

    if isinstance(queries, str):
        raise TypeError(
            "queries must be a sequence "
            "of strings, not one string"
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
        expected_rows=len(
            query_texts
        ),
    )

    return vectors


def encode_query(
    model: Any,
    query: str,
) -> np.ndarray:
    """Encode one retrieval query."""

    return encode_queries(
        model,
        [query],
        batch_size=1,
    )[0]