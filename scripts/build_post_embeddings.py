#!/usr/bin/env python3
"""Build missing semantic embeddings for PostgreSQL posts."""

from __future__ import annotations

import argparse
import asyncio
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from psycopg import AsyncConnection

from app.infrastructure.postgres import connect_postgres


MODEL_DIMENSION = 512
DEFAULT_BATCH_SIZE = 32
DEFAULT_MODEL_PATH = Path(
    "/workspace/models/bge-small-zh-v1.5"
)


def build_post_text(row: Mapping[str, Any]) -> str:
    """Build the document text encoded for semantic retrieval."""

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
    """Validate output shape, finite values, and normalization."""

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
    """Load the local Sentence Transformer model lazily."""

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
    texts: list[str],
    *,
    batch_size: int,
) -> np.ndarray:
    """Encode document texts using the model's document API."""

    document_encoder = getattr(
        model,
        "encode_document",
        None,
    )

    if callable(document_encoder):
        embeddings = document_encoder(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    else:
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    return np.asarray(
        embeddings,
        dtype=np.float32,
    )


async def count_missing_embeddings(
    connection: AsyncConnection[dict[str, Any]],
    *,
    source: str | None,
) -> int:
    """Count rows that still need embeddings."""

    conditions = [
        "embedding IS NULL",
    ]
    parameters: dict[str, Any] = {}

    if source:
        conditions.append(
            "source = %(source)s"
        )
        parameters["source"] = source

    where_sql = " AND ".join(conditions)

    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT COUNT(*) AS missing_count
            FROM posts
            WHERE {where_sql}
            """,
            parameters,
        )
        row = await cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Missing-embedding count returned no row."
        )

    return int(row["missing_count"])


async def fetch_missing_batch(
    connection: AsyncConnection[dict[str, Any]],
    *,
    after_id: int,
    limit: int,
    source: str | None,
) -> list[dict[str, Any]]:
    """Fetch one stable batch of posts without embeddings."""

    conditions = [
        "embedding IS NULL",
        "id > %(after_id)s",
    ]

    parameters: dict[str, Any] = {
        "after_id": after_id,
        "limit": limit,
    }

    if source:
        conditions.append(
            "source = %(source)s"
        )
        parameters["source"] = source

    where_sql = " AND ".join(conditions)

    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT
                id,
                source,
                source_id,
                title,
                category,
                tags,
                content
            FROM posts
            WHERE {where_sql}
            ORDER BY id
            LIMIT %(limit)s
            """,
            parameters,
        )
        rows = await cursor.fetchall()

    return list(rows)


async def write_embedding_batch(
    connection: AsyncConnection[dict[str, Any]],
    *,
    rows: list[dict[str, Any]],
    embeddings: np.ndarray,
) -> None:
    """Persist one embedding batch atomically."""

    parameters = [
        {
            "id": int(row["id"]),
            "embedding": embedding_to_pgvector(
                embedding,
            ),
        }
        for row, embedding in zip(
            rows,
            embeddings,
            strict=True,
        )
    ]

    async with connection.cursor() as cursor:
        await cursor.executemany(
            """
            UPDATE posts
            SET
                embedding =
                    %(embedding)s::vector,
                embedding_updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = %(id)s
              AND embedding IS NULL
            """,
            parameters,
        )


def print_dry_run_samples(
    rows: list[dict[str, Any]],
    texts: list[str],
    norms: np.ndarray,
) -> None:
    """Print a compact, non-sensitive dry-run preview."""

    sample_count = min(
        len(rows),
        3,
    )

    for index in range(sample_count):
        row = rows[index]

        print(
            "sample",
            index + 1,
            "| id=",
            row["id"],
            "| source_id=",
            row["source_id"],
            "| norm=",
            round(float(norms[index]), 6),
        )

        print(
            "  text:",
            texts[index][:180].replace(
                "\n",
                " | ",
            ),
        )


async def build_embeddings(
    args: argparse.Namespace,
) -> None:
    """Run the incremental embedding build."""

    model_path = args.model_path.resolve()

    if not model_path.is_dir():
        raise FileNotFoundError(
            f"Local model directory not found: "
            f"{model_path}"
        )

    effective_limit = args.limit

    if args.dry_run and effective_limit is None:
        effective_limit = 10

    device = resolve_device(args.device)

    print("========== embedding build ==========")
    print("model_path:", model_path)
    print("device:", device)
    print("dimension:", MODEL_DIMENSION)
    print("batch_size:", args.batch_size)
    print("source:", args.source or "<all>")
    print("limit:", effective_limit or "<all>")
    print("dry_run:", args.dry_run)

    model = load_model(
        model_path,
        device=device,
    )

    processed = 0
    last_id = 0

    async with await connect_postgres() as connection:
        missing_before = (
            await count_missing_embeddings(
                connection,
                source=args.source,
            )
        )
        await connection.commit()

        print(
            "missing_before:",
            missing_before,
        )

        if missing_before == 0:
            print(
                "[OK] no missing embeddings found"
            )
            return

        while True:
            if (
                effective_limit is not None
                and processed >= effective_limit
            ):
                break

            fetch_limit = args.batch_size

            if effective_limit is not None:
                fetch_limit = min(
                    fetch_limit,
                    effective_limit - processed,
                )

            rows = await fetch_missing_batch(
                connection,
                after_id=last_id,
                limit=fetch_limit,
                source=args.source,
            )
            await connection.commit()

            if not rows:
                break

            texts = [
                build_post_text(row)
                for row in rows
            ]

            embeddings = encode_documents(
                model,
                texts,
                batch_size=args.batch_size,
            )

            norms = validate_embedding_batch(
                embeddings,
                expected_rows=len(rows),
            )

            if args.dry_run:
                print_dry_run_samples(
                    rows,
                    texts,
                    norms,
                )
            else:
                await write_embedding_batch(
                    connection,
                    rows=rows,
                    embeddings=embeddings,
                )
                await connection.commit()

            processed += len(rows)
            last_id = int(rows[-1]["id"])

            print(
                "progress:",
                processed,
                "| last_id:",
                last_id,
                "| norm_range:",
                (
                    round(float(norms.min()), 6),
                    round(float(norms.max()), 6),
                ),
            )

        missing_after = (
            await count_missing_embeddings(
                connection,
                source=args.source,
            )
        )
        await connection.commit()

    print("========== summary ==========")
    print("processed:", processed)
    print("missing_before:", missing_before)
    print("missing_after:", missing_after)

    if args.dry_run:
        if missing_after != missing_before:
            raise RuntimeError(
                "Dry-run unexpectedly changed the database."
            )

        print(
            "[OK] dry-run completed without writes"
        )
    else:
        expected_after = (
            missing_before - processed
        )

        if missing_after != expected_after:
            raise RuntimeError(
                "Unexpected missing embedding count: "
                f"expected {expected_after}, "
                f"got {missing_after}."
            )

        print(
            "[OK] embedding batch committed"
        )


def positive_int(value: str) -> int:
    """Parse one strictly positive integer."""

    parsed = int(value)

    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return parsed


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate missing BGE embeddings for posts."
        )
    )

    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help=(
            "Local Sentence Transformer model directory."
        ),
    )

    parser.add_argument(
        "--batch-size",
        type=positive_int,
        default=DEFAULT_BATCH_SIZE,
        help="Encoding and database batch size.",
    )

    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        help=(
            "Maximum posts to process. "
            "Default processes all missing posts."
        ),
    )

    parser.add_argument(
        "--device",
        choices=(
            "auto",
            "cpu",
            "cuda",
        ),
        default="auto",
        help="Torch execution device.",
    )

    parser.add_argument(
        "--source",
        default=None,
        help=(
            "Optional posts.source filter."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Generate and validate vectors without "
            "writing to PostgreSQL."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """CLI entry point."""

    args = parse_args()

    try:
        asyncio.run(
            build_embeddings(args)
        )
    except KeyboardInterrupt:
        print(
            "\nInterrupted; previously committed batches "
            "remain valid."
        )
        raise SystemExit(130)


if __name__ == "__main__":
    main()
