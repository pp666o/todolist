#!/usr/bin/env bash

# 恢复 Geo-aware Post Search 所需的搜索资产：
#
# 1. 检查 PostgreSQL 正式帖子是否与远程 MySQL 一致。
# 2. 数据缺失时执行全量、幂等 MySQL 同步。
# 3. 按以下优先级恢复 BGE 模型：
#      本地模型
#      → Docker 模型卷
#      → 本地 recovery 备份包
#      → Hugging Face 下载
# 4. 检查并补齐缺失的帖子 Embedding。
# 5. 验证向量维度、范数和 HNSW 索引。
#
# 本脚本由 restore_dev.sh 调用，也可以单独执行。
# 所有 Python 命令均使用 .venv/bin/python，不依赖当前终端是否已 source。

set -Eeuo pipefail

ROOT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

ENV_FILE="${ROOT_DIR}/.env"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

POSTGRES_CONTAINER="geo-postgres"
POST_SOURCE="mysql_tiezi_geo_new"

MODEL_REPO="BAAI/bge-small-zh-v1.5"
MODEL_PATH="${ROOT_DIR}/models/bge-small-zh-v1.5"
MODEL_VOLUME="geo-post-search_model_cache"

EMBEDDING_DIMENSION=512
EMBEDDING_BATCH_SIZE=128
SYNC_BATCH_SIZE=1000

SKIP_SYNC=0
SKIP_MODEL_DOWNLOAD=0
SKIP_EMBEDDINGS=0


log() {
  printf '\n========== %s ==========\n' "$1"
}


warn() {
  printf '[WARN] %s\n' "$1" >&2
}


fail() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}


on_error() {
  local exit_code=$?
  local line_number="${BASH_LINENO[0]:-unknown}"
  local command_text="${BASH_COMMAND:-unknown}"

  printf '\n[ERROR] 搜索资产恢复失败\n' >&2
  printf 'exit_code: %s\n' "${exit_code}" >&2
  printf 'line: %s\n' "${line_number}" >&2
  printf 'command: %s\n' "${command_text}" >&2

  exit "${exit_code}"
}

trap on_error ERR


usage() {
  cat <<'EOF'
Usage:
  bash scripts/restore_search_assets.sh [options]

Options:
  --skip-sync
      不检查或同步远程 MySQL 数据。

  --skip-model-download
      模型不存在时不访问 Hugging Face。
      仍会尝试从 Docker volume 或 recovery 备份恢复。

  --skip-embeddings
      不构建缺失的帖子 Embedding。

  -h, --help
      显示帮助。
EOF
}


while (($# > 0)); do
  case "$1" in
    --skip-sync)
      SKIP_SYNC=1
      ;;
    --skip-model-download)
      SKIP_MODEL_DOWNLOAD=1
      ;;
    --skip-embeddings)
      SKIP_EMBEDDINGS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "未知参数：$1"
      ;;
  esac

  shift
done


cd "${ROOT_DIR}"

[[ -s "${ENV_FILE}" ]] \
  || fail "${ENV_FILE} 不存在或为空"

[[ -x "${PYTHON_BIN}" ]] \
  || fail "Python 虚拟环境不存在：${PYTHON_BIN}"

[[ -f "${ROOT_DIR}/scripts/sync_mysql_posts.py" ]] \
  || fail "缺少 scripts/sync_mysql_posts.py"

[[ -f "${ROOT_DIR}/scripts/build_post_embeddings.py" ]] \
  || fail "缺少 scripts/build_post_embeddings.py"

docker inspect "${POSTGRES_CONTAINER}" >/dev/null 2>&1 \
  || fail "PostgreSQL 容器不存在：${POSTGRES_CONTAINER}"


# 从 .env 安全读取单个配置值。
# 不直接 source .env，避免密码中的特殊字符被 Shell 解释。
read_env_value() {
  local key="$1"

  python3 - "${ENV_FILE}" "${key}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
target = sys.argv[2]

for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    key, value = line.split("=", 1)

    if key.strip() != target:
        continue

    value = value.strip()

    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]

    print(value)
    raise SystemExit(0)

print("")
PY
}


postgres_scalar() {
  local sql="$1"
  local postgres_user
  local postgres_db

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

  [[ -n "${postgres_user}" ]] \
    || fail "POSTGRES_USER 未配置"

  [[ -n "${postgres_db}" ]] \
    || fail "POSTGRES_DB 未配置"

  docker exec "${POSTGRES_CONTAINER}" \
    psql \
    -U "${postgres_user}" \
    -d "${postgres_db}" \
    -Atqc "${sql}"
}


ensure_embedding_dependencies() {
  log "检查 BGE Python 依赖"

  if "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import huggingface_hub
import sentence_transformers
PY
  then
    printf 'Embedding dependencies: OK\n'
    return
  fi

  printf '安装 requirements-embedding.txt...\n'

  "${PYTHON_BIN}" -m pip install \
    -r "${ROOT_DIR}/requirements-embedding.txt"

  "${PYTHON_BIN}" - <<'PY' >/dev/null
import huggingface_hub
import sentence_transformers
PY

  printf 'Embedding dependencies: installed\n'
}


model_files_valid() {
  local path="$1"

  [[ -s "${path}/config.json" ]] || return 1

  if [[ -s "${path}/model.safetensors" ]]; then
    return 0
  fi

  if [[ -s "${path}/pytorch_model.bin" ]]; then
    return 0
  fi

  return 1
}


restore_model_from_volume() {
  docker volume inspect "${MODEL_VOLUME}" >/dev/null 2>&1 \
    || return 1

  docker run --rm \
    --entrypoint sh \
    -v "${MODEL_VOLUME}:/backup:ro" \
    pgvector/pgvector:pg17 \
    -c '
      test -s /backup/config.json &&
      (
        test -s /backup/model.safetensors ||
        test -s /backup/pytorch_model.bin
      )
    ' >/dev/null 2>&1 \
    || return 1

  log "从 Docker volume 恢复 BGE 模型"

  mkdir -p "${MODEL_PATH}"

  docker run --rm \
    --entrypoint sh \
    -v "${MODEL_VOLUME}:/backup:ro" \
    -v "${MODEL_PATH}:/target" \
    pgvector/pgvector:pg17 \
    -c '
      set -eu

      find /target \
        -mindepth 1 \
        -maxdepth 1 \
        -exec rm -rf {} +

      cp -a /backup/. /target/
    '

  model_files_valid "${MODEL_PATH}"
}


find_latest_model_archive() {
  find "${ROOT_DIR}/backups" \
    -type f \
    -name 'bge-small-zh-v1.5_*.tar.gz' \
    -print 2>/dev/null \
    | sort \
    | tail -n 1
}


restore_model_from_archive() {
  local archive

  archive="$(find_latest_model_archive)"

  [[ -n "${archive}" ]] || return 1
  [[ -s "${archive}" ]] || return 1

  log "从 recovery 备份包恢复 BGE 模型"

  printf 'Model archive: %s\n' "${archive}"

  rm -rf "${MODEL_PATH}"
  mkdir -p "${ROOT_DIR}/models"

  tar \
    -xzf "${archive}" \
    -C "${ROOT_DIR}/models"

  model_files_valid "${MODEL_PATH}"
}


download_model() {
  ((SKIP_MODEL_DOWNLOAD == 0)) || return 1

  log "从 Hugging Face 下载 BGE 模型"

  mkdir -p "${MODEL_PATH}"

  HF_HUB_DISABLE_XET=1 \
  "${PYTHON_BIN}" - "${MODEL_REPO}" "${MODEL_PATH}" <<'PY'
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
target = Path(sys.argv[2])

target.mkdir(parents=True, exist_ok=True)

result = snapshot_download(
    repo_id=repo_id,
    local_dir=str(target),
)

print("repo_id:", repo_id)
print("model_path:", result)
print(
    "config_exists:",
    (target / "config.json").is_file(),
)
PY

  model_files_valid "${MODEL_PATH}"
}


backup_model_to_volume() {
  log "检查 Docker 模型缓存"

  # 已有完整模型缓存时直接复用，避免每次恢复都复制约 184 MB。
  #
  # 同时检查配置文件和主模型权重，防止空卷或不完整卷被误判
  # 为可用缓存。
  if docker volume inspect \
      "${MODEL_VOLUME}" >/dev/null 2>&1
  then
    if docker run --rm \
        --entrypoint sh \
        -v "${MODEL_VOLUME}:/backup:ro" \
        pgvector/pgvector:pg17 \
        -c '
          set -eu

          test -s /backup/config.json

          if test -s /backup/model.safetensors; then
            exit 0
          fi

          if test -s /backup/pytorch_model.bin; then
            exit 0
          fi

          exit 1
        ' >/dev/null 2>&1
    then
      printf 'Docker model cache: available\n'
      return
    fi
  fi

  log "同步 BGE 模型到 Docker volume"

  docker volume create "${MODEL_VOLUME}" >/dev/null

  docker run --rm \
    --entrypoint sh \
    -v "${MODEL_PATH}:/source:ro" \
    -v "${MODEL_VOLUME}:/backup" \
    pgvector/pgvector:pg17 \
    -c '
      set -eu

      find /backup \
        -mindepth 1 \
        -maxdepth 1 \
        -exec rm -rf {} +

      cp -a /source/. /backup/

      test -s /backup/config.json

      if ! test -s /backup/model.safetensors \
          && ! test -s /backup/pytorch_model.bin
      then
        echo "[ERROR] copied model weights are missing" >&2
        exit 1
      fi

      echo "model files: $(find /backup -type f | wc -l)"
      echo "model size: $(du -sh /backup | cut -f1)"
    '
}

validate_model_runtime() {
  log "验证 BGE 模型"

  "${PYTHON_BIN}" - "${MODEL_PATH}" "${EMBEDDING_DIMENSION}" <<'PY'
import sys

import numpy as np
from sentence_transformers import SentenceTransformer

model_path = sys.argv[1]
expected_dimension = int(sys.argv[2])

model = SentenceTransformer(
    model_path,
    device="cpu",
)

vectors = np.asarray(
    model.encode(
        [
            "为这个句子生成表示以用于检索相关文章："
            "附近有人需要搬家帮助吗"
        ],
        normalize_embeddings=True,
    )
)

print("shape:", vectors.shape)
print("finite:", bool(np.isfinite(vectors).all()))
print(
    "norm:",
    float(np.linalg.norm(vectors[0])),
)

if vectors.shape != (1, expected_dimension):
    raise RuntimeError(
        f"Unexpected embedding shape: {vectors.shape}"
    )

if not np.isfinite(vectors).all():
    raise RuntimeError(
        "Embedding contains non-finite values"
    )
PY
}


ensure_model() {
  ensure_embedding_dependencies

  if model_files_valid "${MODEL_PATH}"; then
    log "检查本地 BGE 模型"
    printf 'Local model: available\n'
  elif restore_model_from_volume; then
    printf 'Model restored from Docker volume.\n'
  elif restore_model_from_archive; then
    printf 'Model restored from recovery archive.\n'
  elif download_model; then
    printf 'Model downloaded from Hugging Face.\n'
  else
    fail \
      "无法恢复 BGE 模型；请提供模型备份或允许 Hugging Face 下载"
  fi

  validate_model_runtime
  backup_model_to_volume
}


read_remote_mysql_count() {
  PYTHONPATH="${ROOT_DIR}" \
  "${PYTHON_BIN}" - <<'PY'
from app.infrastructure.mysql_source import (
    check_mysql_source_connection,
)

result = check_mysql_source_connection()
print(int(result["row_count"]))
PY
}


restore_posts() {
  if ((SKIP_SYNC == 1)); then
    log "跳过 MySQL 数据同步"
    return
  fi

  log "检查 MySQL 与 PostgreSQL 帖子数量"

  local remote_count
  local postgres_count

  remote_count="$(read_remote_mysql_count)"
  postgres_count="$(
    postgres_scalar "
      SELECT COUNT(*)
      FROM posts
      WHERE source = '${POST_SOURCE}';
    "
  )"

  remote_count="${remote_count//[[:space:]]/}"
  postgres_count="${postgres_count//[[:space:]]/}"

  [[ "${remote_count}" =~ ^[0-9]+$ ]] \
    || fail "无法读取远程 MySQL 帖子数量"

  [[ "${postgres_count}" =~ ^[0-9]+$ ]] \
    || fail "无法读取 PostgreSQL 帖子数量"

  printf 'Remote MySQL posts: %s\n' "${remote_count}"
  printf 'PostgreSQL posts:   %s\n' "${postgres_count}"

  if [[ "${remote_count}" == "${postgres_count}" ]]; then
    printf 'Post synchronization: not required\n'
  else
    log "执行 MySQL 全量幂等同步"

    # 必须使用 full 模式。
    # 不能再使用旧的 --limit 1000 bootstrap，否则新数据库只会恢复
    # 1,000 条帖子，并被误判为已经完成。
    PYTHONPATH="${ROOT_DIR}" \
    "${PYTHON_BIN}" \
      "${ROOT_DIR}/scripts/sync_mysql_posts.py" \
      --mode full \
      --batch-size "${SYNC_BATCH_SIZE}" \
      --reset-checkpoint
  fi

  log "执行 MySQL/PostgreSQL 数据对账"

  PYTHONPATH="${ROOT_DIR}" \
  "${PYTHON_BIN}" \
    "${ROOT_DIR}/scripts/audit_post_data.py" \
    --sample-size 20
}


restore_embeddings() {
  if ((SKIP_EMBEDDINGS == 1)); then
    log "跳过帖子 Embedding"
    return
  fi

  log "检查帖子 Embedding"

  local total_count
  local embedded_count
  local missing_count

  total_count="$(
    postgres_scalar "
      SELECT COUNT(*)
      FROM posts
      WHERE source = '${POST_SOURCE}';
    "
  )"

  embedded_count="$(
    postgres_scalar "
      SELECT COUNT(embedding)
      FROM posts
      WHERE source = '${POST_SOURCE}';
    "
  )"

  missing_count="$(
    postgres_scalar "
      SELECT COUNT(*)
      FROM posts
      WHERE source = '${POST_SOURCE}'
        AND embedding IS NULL;
    "
  )"

  printf 'Total posts:        %s\n' "${total_count}"
  printf 'Embedded posts:     %s\n' "${embedded_count}"
  printf 'Missing embeddings: %s\n' "${missing_count}"

  if [[ "${missing_count}" == "0" ]]; then
    printf 'Embedding build: not required\n'
    return
  fi

  log "构建缺失的帖子 Embedding"

  # build_post_embeddings.py 只读取 embedding IS NULL 的记录，
  # 已经提交的批次不会重复计算，因此支持安全断点续跑。
  PYTHONPATH="${ROOT_DIR}" \
  "${PYTHON_BIN}" \
    "${ROOT_DIR}/scripts/build_post_embeddings.py" \
    --model-path "${MODEL_PATH}" \
    --batch-size "${EMBEDDING_BATCH_SIZE}" \
    --device auto \
    --source "${POST_SOURCE}"
}


show_asset_summary() {
  log "搜索资产恢复结果"

  local postgres_user
  local postgres_db

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

  docker exec "${POSTGRES_CONTAINER}" \
    psql \
    -U "${postgres_user}" \
    -d "${postgres_db}" \
    -v ON_ERROR_STOP=1 \
    -c "
      SELECT
          COUNT(*) AS total_posts,
          COUNT(DISTINCT source_id)
              AS distinct_source_ids,
          COUNT(embedding)
              AS embedded_posts,
          COUNT(*) FILTER (
              WHERE embedding IS NULL
          ) AS missing_embeddings,
          COUNT(*) FILTER (
              WHERE embedding IS NOT NULL
                AND vector_dims(embedding)
                    <> ${EMBEDDING_DIMENSION}
          ) AS invalid_dimensions
      FROM posts
      WHERE source = '${POST_SOURCE}';
    " \
    -c "
      SELECT
          vector_dims(embedding) AS dimensions,
          COUNT(*) AS row_count,
          MIN(vector_norm(embedding)) AS min_norm,
          MAX(vector_norm(embedding)) AS max_norm
      FROM posts
      WHERE source = '${POST_SOURCE}'
        AND embedding IS NOT NULL
      GROUP BY vector_dims(embedding);
    " \
    -c "
      SELECT
          indexname,
          pg_size_pretty(
              pg_relation_size(indexname::regclass)
          ) AS index_size
      FROM pg_indexes
      WHERE tablename = 'posts'
        AND indexname = 'idx_posts_embedding_hnsw';
    "

  printf '\n当前终端如需激活 Python 环境，请执行：\n'
  printf '  source %s/scripts/activate_dev.sh\n' "${ROOT_DIR}"
}


# 模型和数据库向量是两类独立资产。
# 即使 PostgreSQL 已恢复全部 Embedding，
# 在线 Query 编码仍然需要本地 BGE 模型。
restore_posts
ensure_model
restore_embeddings
show_asset_summary
