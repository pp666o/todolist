"""Shared embedding utilities for offline and online retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any




MODEL_DIMENSION = 512
DEFAULT_BATCH_SIZE = 32
DEFAULT_MODEL_PATH = Path(
    "/workspace/models/bge-small-zh-v1.5"
)

QUERY_INSTRUCTION = (
    "为这个句子生成表示以用于检索相关文章："
)




