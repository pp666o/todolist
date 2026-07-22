from __future__ import annotations

import numpy as np

from app.search.embedding import (
    MODEL_DIMENSION,
    build_post_text,
    build_query_text,
    embedding_to_pgvector,
    validate_embedding_batch,
)


def test_document_embedding_text_contract() -> None:
    text = build_post_text(
        {
            "id": 1,
            "title": "文件安全问题",
            "category": "求助",
            "tags": [
                "手机",
                "安全",
            ],
            "content": "如何处理手机文件安全问题？",
        }
    )

    assert text == (
        "标题：文件安全问题\n"
        "类别：求助\n"
        "标签：手机 安全\n"
        "正文：如何处理手机文件安全问题？"
    )


def test_query_embedding_text_contract() -> None:
    query_text = build_query_text(
        "手机文件安全吗？"
    )

    assert query_text == (
        "为这个句子生成表示以用于检索相关文章："
        "手机文件安全吗？"
    )


def test_vector_contract() -> None:
    vector = np.zeros(
        MODEL_DIMENSION,
        dtype=np.float32,
    )

    vector[0] = 1.0

    validate_embedding_batch(
        np.asarray(
            [vector],
            dtype=np.float32,
        ),
        expected_rows=1,
    )

    literal = embedding_to_pgvector(vector)

    assert len(
        literal.removeprefix("[")
        .removesuffix("]")
        .split(",")
    ) == MODEL_DIMENSION
