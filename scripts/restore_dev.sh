#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
POSTGRES_COMPOSE_FILE="${ROOT_DIR}/compose.postgres.yml"
POSTGRES_CONTAINER="geo-postgres"
POSTS_MIGRATION="${ROOT_DIR}/db/migrations/001_create_posts.sql"

INFRA_ONLY=0
SKIP_SYNC=0

log() {
  printf '\n========== %s ==========\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  bash scripts/restore_dev.sh [options]

Options:
  --infra-only   Restore PostgreSQL, Redis, migration and bootstrap data,
                 but do not start FastAPI/Vite.
  --skip-sync    Do not bootstrap posts from MySQL.
  -h, --help     Show this help.
EOF
}

while (($# > 0)); do
  case "$1" in
    --infra-only)
      INFRA_ONLY=1
      ;;
    --skip-sync)
      SKIP_SYNC=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
  shift
done

cd "${ROOT_DIR}"

[[ -f "${ENV_FILE}" ]] || fail ".env does not exist"
[[ -f "${POSTGRES_COMPOSE_FILE}" ]] || fail "compose.postgres.yml does not exist"
[[ -f "${POSTS_MIGRATION}" ]] || fail "posts migration does not exist"
[[ -f "${ROOT_DIR}/scripts/start_dev.sh" ]] || fail "scripts/start_dev.sh does not exist"

for command_name in docker ssh python3; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || fail "required command not found: ${command_name}"
done

read_env_value() {
  local key="$1"

  python3 - "${ENV_FILE}" "${key}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
target = sys.argv[2]
value = ""

for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    key, candidate = line.split("=", 1)

    if key.strip() != target:
        continue

    value = candidate.strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

print(value)
PY
}

env_value_or_default() {
  local key="$1"
  local default_value="$2"
  local configured_value

  configured_value="$(read_env_value "${key}")"

  if [[ -n "${configured_value}" ]]; then
    printf '%s' "${configured_value}"
  else
    printf '%s' "${default_value}"
  fi
}

redis_ping() {
  local host="$1"
  local port="$2"

  python3 - "${host}" "${port}" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        response = sock.recv(128).decode("utf-8", errors="replace").strip()
except OSError:
    raise SystemExit(1)

if response != "+PONG":
    raise SystemExit(1)
PY
}

start_postgres() {
  log "启动 PostgreSQL"

  docker compose \
    --env-file "${ENV_FILE}" \
    -f "${POSTGRES_COMPOSE_FILE}" \
    up -d

  local status=""
  local attempt

  for attempt in $(seq 1 60); do
    status="$(
      docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "${POSTGRES_CONTAINER}" \
        2>/dev/null || true
    )"

    if [[ "${status}" == "healthy" ]]; then
      printf 'PostgreSQL status: healthy\n'
      return
    fi

    if [[ "${status}" == "exited" || "${status}" == "dead" ]]; then
      docker logs --tail 100 "${POSTGRES_CONTAINER}" || true
      fail "PostgreSQL container stopped unexpectedly"
    fi

    sleep 1
  done

  docker logs --tail 100 "${POSTGRES_CONTAINER}" || true
  fail "PostgreSQL health check timed out; last status: ${status:-unknown}"
}

apply_migration() {
  log "执行 PostgreSQL 迁移"

  local postgres_user
  local postgres_db

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

  [[ -n "${postgres_user}" ]] || fail "POSTGRES_USER is missing from .env"
  [[ -n "${postgres_db}" ]] || fail "POSTGRES_DB is missing from .env"

  docker exec -i "${POSTGRES_CONTAINER}" \
    psql \
    -v ON_ERROR_STOP=1 \
    -U "${postgres_user}" \
    -d "${postgres_db}" \
    < "${POSTS_MIGRATION}"

  printf 'PostgreSQL migration: OK\n'
}

ensure_redis_tunnel() {
  log "检查 Redis SSH 隧道"

  local redis_host
  local redis_port
  local ssh_host
  local ssh_user
  local remote_host
  local remote_port

  redis_host="$(env_value_or_default REDIS_HOST 127.0.0.1)"
  redis_port="$(env_value_or_default REDIS_PORT 16379)"
  ssh_host="$(read_env_value REDIS_SSH_HOST)"
  ssh_user="$(env_value_or_default REDIS_SSH_USER ubuntu)"
  remote_host="$(env_value_or_default REDIS_REMOTE_HOST 127.0.0.1)"
  remote_port="$(env_value_or_default REDIS_REMOTE_PORT 6379)"

  if redis_ping "${redis_host}" "${redis_port}"; then
    printf 'Redis tunnel already available: %s:%s\n' \
      "${redis_host}" "${redis_port}"
    return
  fi

  [[ -n "${ssh_host}" ]] \
    || fail "REDIS_SSH_HOST is missing from .env"

  printf 'Restoring tunnel: %s:%s -> %s:%s via %s@%s\n' \
    "${redis_host}" \
    "${redis_port}" \
    "${remote_host}" \
    "${remote_port}" \
    "${ssh_user}" \
    "${ssh_host}"

  ssh \
    -fN \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -L "${redis_host}:${redis_port}:${remote_host}:${remote_port}" \
    "${ssh_user}@${ssh_host}"

  sleep 1

  redis_ping "${redis_host}" "${redis_port}" \
    || fail "Redis tunnel was created but PING failed"

  printf 'Redis tunnel: PONG\n'
}

ensure_python_environment() {
  log "检查 Python 环境"

  if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf 'Creating .venv...\n'
    python3 -m venv "${ROOT_DIR}/.venv"
  fi

  if ! "${ROOT_DIR}/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import psycopg
import pymysql
import redis
import pydantic_settings
PY
  then
    printf 'Installing Python dependencies...\n'
    "${ROOT_DIR}/.venv/bin/python" -m pip install -r requirements.txt
  fi

  printf 'Python environment: OK\n'
}

bootstrap_posts() {
  if ((SKIP_SYNC == 1)); then
    log "跳过帖子数据补齐"
    return
  fi

  log "检查 PostgreSQL 帖子数据"

  local bootstrap_limit
  local current_count
  local postgres_user
  local postgres_db

  bootstrap_limit="$(env_value_or_default POST_BOOTSTRAP_LIMIT 1000)"

  [[ "${bootstrap_limit}" =~ ^[0-9]+$ ]] \
    || fail "POST_BOOTSTRAP_LIMIT must be an integer"

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

  [[ -n "${postgres_user}" ]] || fail "POSTGRES_USER is missing from .env"
  [[ -n "${postgres_db}" ]] || fail "POSTGRES_DB is missing from .env"

  current_count="$(
    docker exec "${POSTGRES_CONTAINER}" \
      psql \
      -U "${postgres_user}" \
      -d "${postgres_db}" \
      -Atqc "
        SELECT count(*)
        FROM posts
        WHERE source = 'mysql_tiezi_geo_new';
      "
  )"

  current_count="${current_count//[[:space:]]/}"

  [[ "${current_count}" =~ ^[0-9]+$ ]] \
    || fail "could not determine PostgreSQL post count"

  printf 'Current MySQL-derived posts: %s\n' "${current_count}"
  printf 'Bootstrap target: %s\n' "${bootstrap_limit}"

  if ((current_count >= bootstrap_limit)); then
    printf 'Post bootstrap not required.\n'
    return
  fi

  unset MYSQL_SOURCE_HOST || true
  unset MYSQL_SOURCE_PORT || true
  unset MYSQL_SOURCE_USER || true
  unset MYSQL_SOURCE_PASSWORD || true
  unset MYSQL_SOURCE_DATABASE || true
  unset MYSQL_SOURCE_TABLE || true
  unset MYSQL_SOURCE_CHARSET || true

  PYTHONPATH="${ROOT_DIR}" \
    "${ROOT_DIR}/.venv/bin/python" \
    "${ROOT_DIR}/scripts/sync_mysql_posts.py" \
    --limit "${bootstrap_limit}" \
    --after-id 0
}

show_summary() {
  log "恢复结果"

  local postgres_user
  local postgres_db

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

  [[ -n "${postgres_user}" ]] || fail "POSTGRES_USER is missing from .env"
  [[ -n "${postgres_db}" ]] || fail "POSTGRES_DB is missing from .env"

  docker exec "${POSTGRES_CONTAINER}" \
    psql \
    -U "${postgres_user}" \
    -d "${postgres_db}" \
    -c "
      SELECT
        count(*) AS post_count,
        count(DISTINCT source_id) AS distinct_source_ids,
        count(*) FILTER (
          WHERE embedding IS NOT NULL
        ) AS embedded_count
      FROM posts
      WHERE source = 'mysql_tiezi_geo_new';
    "

  local redis_host
  local redis_port

  redis_host="$(env_value_or_default REDIS_HOST 127.0.0.1)"
  redis_port="$(env_value_or_default REDIS_PORT 16379)"

  if redis_ping "${redis_host}" "${redis_port}"; then
    printf 'Redis: PONG at %s:%s\n' "${redis_host}" "${redis_port}"
  else
    fail "Redis failed after restoration"
  fi
}

main() {
  start_postgres
  apply_migration
  ensure_redis_tunnel
  ensure_python_environment
  bootstrap_posts
  show_summary

  if ((INFRA_ONLY == 1)); then
    log "基础设施恢复完成"
    printf 'Run the full stack with:\n'
    printf '  bash scripts/restore_dev.sh\n'
    return
  fi

  log "启动 FastAPI 和 Vite"
  exec bash "${ROOT_DIR}/scripts/start_dev.sh"
}

main "$@"
