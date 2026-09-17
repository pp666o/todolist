from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from app.algorithms.search.embedding import (
    MODEL_DIMENSION,
    QUERY_INSTRUCTION,
    build_query_text,
)

from app.infrastructure.search.embedding_runtime import (
    encode_documents,
    encode_queries,
    encode_query,
)

class FakeModel:
    def __init__(
        self,
        *,
        provide_document_encoder: bool = False,
    ) -> None:
        self.calls: list[
            tuple[str, list[str], dict[str, Any]]
        ] = []

        if provide_document_encoder:
            self.encode_document = (
                self._encode_document
            )

    @staticmethod
    def _vectors(count: int) -> np.ndarray:
        vectors = np.zeros(
            (count, MODEL_DIMENSION),
            dtype=np.float32,
        )

        for index in range(count):
            vectors[index, index] = 1.0

        return vectors

    def encode(
        self,
        texts: list[str],
        **kwargs: Any,
    ) -> np.ndarray:
        self.calls.append(
            (
                "encode",
                list(texts),
                dict(kwargs),
            )
        )

        return self._vectors(len(texts))

    def _encode_document(
        self,
        texts: list[str],
        **kwargs: Any,
    ) -> np.ndarray:
        self.calls.append(
            (
                "encode_document",
                list(texts),
                dict(kwargs),
            )
        )

        return self._vectors(len(texts))


def test_build_query_text_adds_explicit_instruction() -> None:
    query_text = build_query_text(
        "  手机文件安全吗？  "
    )

    assert query_text == (
        QUERY_INSTRUCTION
        + "手机文件安全吗？"
    )


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
    ],
)
def test_build_query_text_rejects_blank_query(
    query: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="must not be blank",
    ):
        build_query_text(query)


def test_encode_queries_uses_canonical_instruction() -> None:
    model = FakeModel()

    vectors = encode_queries(
        model,
        [
            "手机文件安全",
            "附近软件开发",
        ],
        batch_size=8,
    )

    assert vectors.shape == (
        2,
        MODEL_DIMENSION,
    )

    method_name, texts, kwargs = model.calls[0]

    assert method_name == "encode"
    assert texts == [
        QUERY_INSTRUCTION + "手机文件安全",
        QUERY_INSTRUCTION + "附近软件开发",
    ]
    assert kwargs == {
        "batch_size": 8,
        "normalize_embeddings": True,
        "convert_to_numpy": True,
        "show_progress_bar": False,
    }


def test_encode_query_returns_one_normalized_vector() -> None:
    model = FakeModel()

    vector = encode_query(
        model,
        "程序开发需要准备什么工具？",
    )

    assert vector.shape == (
        MODEL_DIMENSION,
    )
    assert vector.dtype == np.float32
    assert np.linalg.norm(vector) == pytest.approx(
        1.0
    )


def test_encode_documents_prefers_document_api() -> None:
    model = FakeModel(
        provide_document_encoder=True,
    )

    vectors = encode_documents(
        model,
        [
            "标题：测试帖子",
        ],
        batch_size=4,
    )

    assert vectors.shape == (
        1,
        MODEL_DIMENSION,
    )

    method_name, texts, kwargs = model.calls[0]

    assert method_name == "encode_document"
    assert texts == [
        "标题：测试帖子",
    ]
    assert kwargs["normalize_embeddings"] is True


def test_encode_documents_falls_back_to_encode() -> None:
    model = FakeModel()

    encode_documents(
        model,
        [
            "标题：测试帖子",
        ],
    )

    assert model.calls[0][0] == "encode"


def test_encode_queries_rejects_single_string_argument() -> None:
    model = FakeModel()

    with pytest.raises(
        TypeError,
        match="sequence of strings",
    ):
        encode_queries(
            model,
            "错误参数",  # type: ignore[arg-type]
        )
