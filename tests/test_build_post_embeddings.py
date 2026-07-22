from __future__ import annotations

import numpy as np
import pytest

from scripts.build_post_embeddings import (
    MODEL_DIMENSION,
    build_post_text,
    embedding_to_pgvector,
    validate_embedding_batch,
)


def test_build_post_text_uses_search_fields() -> None:
    text = build_post_text(
        {
            "id": 1,
            "title": "文件安全问题",
            "category": "求助",
            "tags": [
                "手机",
                "文件",
                "安全",
            ],
            "content": "如何处理手机文件安全问题？",
        }
    )

    assert text == (
        "标题：文件安全问题\n"
        "类别：求助\n"
        "标签：手机 文件 安全\n"
        "正文：如何处理手机文件安全问题？"
    )


def test_build_post_text_omits_empty_fields() -> None:
    text = build_post_text(
        {
            "id": 2,
            "title": "只有标题",
            "category": "",
            "tags": [],
            "content": "",
        }
    )

    assert text == "标题：只有标题"


def test_build_post_text_rejects_empty_post() -> None:
    with pytest.raises(
        ValueError,
        match="no encodable text",
    ):
        build_post_text(
            {
                "id": 3,
                "title": "",
                "category": "",
                "tags": [],
                "content": "",
            }
        )


def test_validate_embedding_batch_accepts_normalized() -> None:
    embeddings = np.zeros(
        (2, MODEL_DIMENSION),
        dtype=np.float32,
    )

    embeddings[0, 0] = 1.0
    embeddings[1, 1] = 1.0

    norms = validate_embedding_batch(
        embeddings,
        expected_rows=2,
    )

    assert norms.tolist() == [1.0, 1.0]


def test_validate_embedding_batch_rejects_wrong_shape() -> None:
    embeddings = np.zeros(
        (2, 384),
        dtype=np.float32,
    )

    with pytest.raises(
        ValueError,
        match="Expected embedding shape",
    ):
        validate_embedding_batch(
            embeddings,
            expected_rows=2,
        )


def test_embedding_to_pgvector_serializes_512_values() -> None:
    embedding = np.zeros(
        MODEL_DIMENSION,
        dtype=np.float32,
    )
    embedding[0] = 1.0

    literal = embedding_to_pgvector(
        embedding
    )

    assert literal.startswith("[1,")
    assert literal.endswith("]")
    assert len(
        literal.removeprefix("[")
        .removesuffix("]")
        .split(",")
    ) == MODEL_DIMENSION


def test_embedding_to_pgvector_rejects_nan() -> None:
    embedding = np.zeros(
        MODEL_DIMENSION,
        dtype=np.float32,
    )
    embedding[10] = np.nan

    with pytest.raises(
        ValueError,
        match="NaN or infinite",
    ):
        embedding_to_pgvector(
            embedding
        )
