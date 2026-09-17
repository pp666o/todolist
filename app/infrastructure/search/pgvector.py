"""PostgreSQL pgvector serialization helpers."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.algorithms.search.embedding import (
    MODEL_DIMENSION,
)


def embedding_to_pgvector(
    embedding: Sequence[float] | np.ndarray,
) -> str:
    """Serialize one embedding into pgvector text format."""

    vector = np.asarray(
        embedding,
        dtype=np.float32,
    )

    if vector.shape != (
        MODEL_DIMENSION,
    ):
        raise ValueError(
            "Expected one embedding "
            f"with shape ({MODEL_DIMENSION},), "
            f"got {vector.shape}."
        )

    if not np.isfinite(
        vector
    ).all():
        raise ValueError(
            "Embedding contains "
            "NaN or infinite values."
        )

    return (
        "["
        + ",".join(
            format(
                float(value),
                ".9g",
            )
            for value in vector
        )
        + "]"
    )