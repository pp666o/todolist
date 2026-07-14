#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_TOTAL="${EXPECTED_TIEZI_TOTAL:-38062}"
BATCH_SIZE="${IMPORT_BATCH_SIZE:-64}"
OUTPUT_FILE="$ROOT_DIR/data/tiezi_geo_new_all.tsv"

cd "$ROOT_DIR"

if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "ERROR: .env 不存在" >&2
    exit 1
fi

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
    echo "ERROR: .venv 不存在" >&2
    exit 1
fi

set -a
source "$ROOT_DIR/.env"
set +a

PYTHON="$ROOT_DIR/.venv/bin/python"

mkdir -p "$ROOT_DIR/data"

echo "========== 启动 PostgreSQL =========="

docker compose \
    -f "$ROOT_DIR/docker-compose-infra.yaml" \
    up -d postgres

for _ in $(seq 1 40); do
    if pg_isready \
        -h "$POSTGRES_BIND_IP" \
        -p "$POSTGRES_HOST_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        >/dev/null 2>&1
    then
        break
    fi

    sleep 2
done

pg_isready \
    -h "$POSTGRES_BIND_IP" \
    -p "$POSTGRES_HOST_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB"

echo
echo "========== 停止 FastAPI =========="

if [ -f "$ROOT_DIR/.fastapi.pid" ] \
    && kill -0 "$(cat "$ROOT_DIR/.fastapi.pid")" 2>/dev/null
then
    kill "$(cat "$ROOT_DIR/.fastapi.pid")"
    sleep 3
fi

rm -f "$ROOT_DIR/.fastapi.pid"

echo
echo "========== 从 MySQL 导出 =========="

"$PYTHON" "$ROOT_DIR/scripts/export_tiezi_mysql.py" \
    --output "$OUTPUT_FILE" \
    --limit "$EXPECTED_TOTAL"

echo
echo "========== 验证导出文件 =========="

"$PYTHON" - "$OUTPUT_FILE" "$EXPECTED_TOTAL" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = int(sys.argv[2])

total = 0
source_ids = set()

with path.open(encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter="\t")

    for row in reader:
        total += 1
        source_ids.add(row["id"])

print("exported_rows:", total)
print("unique_source_ids:", len(source_ids))

if total != expected:
    raise SystemExit(
        f"ERROR: expected={expected}, actual={total}"
    )

if len(source_ids) != expected:
    raise SystemExit("ERROR: source_id 存在重复")

print("[PASS] TSV")
PY

echo
echo "========== 导入 PostgreSQL =========="

"$PYTHON" "$ROOT_DIR/import_tiezi_data.py" \
    "$OUTPUT_FILE" \
    --max-rows "$EXPECTED_TOTAL" \
    --batch-size "$BATCH_SIZE"

echo
echo "========== 验证数据库 =========="

"$PYTHON" - "$EXPECTED_TOTAL" <<'PY'
import os
import sys

from sqlalchemy import create_engine, text

expected = int(sys.argv[1])
engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as connection:
    stats = connection.execute(
        text(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(embedding) AS embedding_total,
                COUNT(DISTINCT source_id) AS distinct_source_ids
            FROM todos
            WHERE source = 'tiezi_geo_new'
            """
        )
    ).mappings().one()

    dimensions = connection.execute(
        text(
            """
            SELECT
                vector_dims(embedding) AS dimension,
                COUNT(*) AS total
            FROM todos
            WHERE source = 'tiezi_geo_new'
              AND embedding IS NOT NULL
            GROUP BY vector_dims(embedding)
            """
        )
    ).mappings().all()

print("total:", stats["total"])
print("embedding_total:", stats["embedding_total"])
print("distinct_source_ids:", stats["distinct_source_ids"])
print("dimensions:", [dict(row) for row in dimensions])

if stats["total"] != expected:
    raise SystemExit("ERROR: 帖子总数不正确")

if stats["embedding_total"] != expected:
    raise SystemExit("ERROR: embedding 数量不正确")

if stats["distinct_source_ids"] != expected:
    raise SystemExit("ERROR: source_id 去重异常")

if len(dimensions) != 1:
    raise SystemExit("ERROR: embedding 维度不唯一")

if dimensions[0]["dimension"] != 384:
    raise SystemExit("ERROR: embedding 不是 384 维")

if dimensions[0]["total"] != expected:
    raise SystemExit("ERROR: 384维向量数量不正确")

print("[PASS] PostgreSQL tiezi data")
PY

echo
echo "========== 全量导入完成 =========="
echo "运行 ./scripts/dev_up.sh 恢复 FastAPI 和 C++ 索引。"
