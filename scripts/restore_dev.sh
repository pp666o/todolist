#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
PERSIST_ENV="${HOME}/.config/geo-post-search/env"

POSTGRES_COMPOSE_FILE="${ROOT_DIR}/compose.postgres.yml"
POSTGRES_CONTAINER="geo-postgres"
MIGRATIONS_DIR="${ROOT_DIR}/db/migrations"

CONFIGURE_REMOTE_SCRIPT="${ROOT_DIR}/scripts/configure_remote_sources.sh"
START_DEV_SCRIPT="${ROOT_DIR}/scripts/start_dev.sh"

INFRA_ONLY=0
SKIP_SYNC=0
RECONFIGURE=0


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
  --infra-only    Restore infrastructure, but do not start FastAPI/Vite.
  --skip-sync     Do not bootstrap posts from MySQL.
  --reconfigure   Re-detect MySQL and rewrite remote source configuration.
  -h, --help      Show this help.
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
    --reconfigure)
      RECONFIGURE=1
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


run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  fail "root or sudo permission is required"
}


bootstrap_system_dependencies() {
  log "自举系统基础依赖"

  local missing=0
  local command_name

  for command_name in python3 ssh node npm; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      printf 'Missing command: %s\n' "${command_name}"
      missing=1
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    if ! python3 -m venv --help >/dev/null 2>&1; then
      printf 'Missing Python venv module\n'
      missing=1
    fi
  fi

  if ((missing == 1)); then
    if command -v apt-get >/dev/null 2>&1; then
      run_as_root apt-get update

      run_as_root env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y \
          python3 \
          python3-venv \
          python3-pip \
          python3-dev \
          build-essential \
          libpq-dev \
          openssh-client \
          nodejs \
          npm \
          curl \
          ca-certificates

    elif command -v apk >/dev/null 2>&1; then
      run_as_root apk add --no-cache \
        python3 \
        py3-pip \
        py3-virtualenv \
        python3-dev \
        build-base \
        postgresql-dev \
        openssh-client \
        nodejs \
        npm \
        curl \
        ca-certificates

    elif command -v dnf >/dev/null 2>&1; then
      run_as_root dnf install -y \
        python3 \
        python3-pip \
        python3-devel \
        gcc \
        gcc-c++ \
        postgresql-devel \
        openssh-clients \
        nodejs \
        npm \
        curl \
        ca-certificates

    elif command -v yum >/dev/null 2>&1; then
      run_as_root yum install -y \
        python3 \
        python3-pip \
        python3-devel \
        gcc \
        gcc-c++ \
        postgresql-devel \
        openssh-clients \
        nodejs \
        npm \
        curl \
        ca-certificates

    else
      fail "unsupported package manager"
    fi
  fi

  for command_name in python3 ssh node npm docker; do
    command -v "${command_name}" >/dev/null 2>&1 \
      || fail "required command unavailable: ${command_name}"
  done

  python3 -m venv --help >/dev/null 2>&1 \
    || fail "python3 venv module is unavailable"

  docker compose version >/dev/null 2>&1 \
    || fail "Docker Compose plugin is unavailable"

  printf 'System dependencies: OK\n'
}


ensure_python_environment() {
  log "检查 Python 环境"

  if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf 'Creating .venv...\n'
    python3 -m venv "${ROOT_DIR}/.venv"
  fi

  local requirements_file="${ROOT_DIR}/requirements.txt"

  if [[ -f "${ROOT_DIR}/requirements-dev.txt" ]]; then
    requirements_file="${ROOT_DIR}/requirements-dev.txt"
  fi

  if ! "${ROOT_DIR}/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import httpx
import psycopg
import pymysql
import pytest
import redis
import pydantic
import pydantic_settings
PY
  then
    printf 'Installing Python dependencies from: %s\n' \
      "${requirements_file}"

    "${ROOT_DIR}/.venv/bin/python" \
      -m pip install \
      --disable-pip-version-check \
      -r "${requirements_file}"
  fi

  printf 'Python environment: OK\n'
}


env_configuration_valid() {
  [[ -f "${ENV_FILE}" ]] || return 1

  "${ROOT_DIR}/.venv/bin/python" \
    - "${ENV_FILE}" <<'PY'
import sys
from pathlib import Path


path = Path(sys.argv[1])
values = {}

for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    key, value = line.split("=", 1)
    value = value.strip()

    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]

    values[key.strip()] = value


required = (
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",

    "MYSQL_SOURCE_HOST",
    "MYSQL_SOURCE_PORT",
    "MYSQL_SOURCE_USER",
    "MYSQL_SOURCE_PASSWORD",
    "MYSQL_SOURCE_DATABASE",
    "MYSQL_SOURCE_TABLE",

    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_SSH_HOST",
    "REDIS_SSH_USER",
    "REDIS_REMOTE_HOST",
    "REDIS_REMOTE_PORT",
)

placeholders = (
    "replace_with",
    "your-server",
    "这里填写",
    "placeholder",
)

invalid = []

for key in required:
    value = values.get(key, "")

    if not value:
        invalid.append(f"{key}=EMPTY")
        continue

    lowered = value.lower()

    if any(marker.lower() in lowered for marker in placeholders):
        invalid.append(f"{key}=PLACEHOLDER")

if invalid:
    print("Invalid environment: " + ", ".join(invalid))
    raise SystemExit(1)
PY
}


ensure_env_configuration() {
  log "检查环境配置"

  if [[ ! -f "${ENV_FILE}" && -f "${PERSIST_ENV}" ]]; then
    cp "${PERSIST_ENV}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"

    printf '.env restored from: %s\n' "${PERSIST_ENV}"
  fi

  if ((RECONFIGURE == 1)); then
    bash "${CONFIGURE_REMOTE_SCRIPT}"
  elif ! env_configuration_valid; then
    printf 'Environment is missing or incomplete; configuring...\n'
    bash "${CONFIGURE_REMOTE_SCRIPT}"
  fi

  env_configuration_valid \
    || fail ".env remains invalid after configuration"

  mkdir -p "$(dirname "${PERSIST_ENV}")"
  chmod 700 "$(dirname "${PERSIST_ENV}")"

  cp "${ENV_FILE}" "${PERSIST_ENV}"

  chmod 600 \
    "${ENV_FILE}" \
    "${PERSIST_ENV}"

  printf 'Environment configuration: OK\n'
}


read_env_value() {
  local key="$1"

  "${ROOT_DIR}/.venv/bin/python" \
    - "${ENV_FILE}" "${key}" <<'PY'
import sys
from pathlib import Path


path = Path(sys.argv[1])
target = sys.argv[2]
result = ""

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

    result = value
    break

print(result)
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

  "${ROOT_DIR}/.venv/bin/python" \
    - "${host}" "${port}" <<'PY'
import socket
import sys


host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection(
        (host, port),
        timeout=3,
    ) as sock:
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        response = sock.recv(128).decode(
            "utf-8",
            errors="replace",
        ).strip()
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
        --format \
        '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
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

  fail \
    "PostgreSQL health check timed out; status=${status:-unknown}"
}



# managed-postgres-password-sync-v1
synchronize_postgres_password() {
  log "同步 PostgreSQL 用户密码"

  local postgres_user
  local postgres_db
  local sql_file

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

  [[ -n "${postgres_user}" ]] \
    || fail "POSTGRES_USER is missing"

  [[ -n "${postgres_db}" ]] \
    || fail "POSTGRES_DB is missing"

  sql_file="$(mktemp)"

  "${ROOT_DIR}/.venv/bin/python" \
    - "${ENV_FILE}" "${sql_file}" <<'PYSQL'
import sys
from pathlib import Path


env_path = Path(sys.argv[1])
sql_path = Path(sys.argv[2])

values = {}

for raw_line in env_path.read_text(
    encoding="utf-8"
).splitlines():
    line = raw_line.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    key, value = line.split("=", 1)
    value = value.strip()

    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]

    values[key.strip()] = value


user = values.get("POSTGRES_USER", "")
password = values.get("POSTGRES_PASSWORD", "")

if not user:
    raise SystemExit("POSTGRES_USER is empty")

if not password:
    raise SystemExit("POSTGRES_PASSWORD is empty")

if "\n" in user or "\n" in password:
    raise SystemExit("PostgreSQL credentials contain invalid newline")


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


sql = (
    f"ALTER ROLE {quote_identifier(user)} "
    f"WITH PASSWORD {quote_literal(password)};\n"
)

sql_path.write_text(sql, encoding="utf-8")
sql_path.chmod(0o600)
PYSQL

  if ! docker exec -i "${POSTGRES_CONTAINER}" \
    psql \
    -v ON_ERROR_STOP=1 \
    -U "${postgres_user}" \
    -d "${postgres_db}" \
    < "${sql_file}"
  then
    rm -f "${sql_file}"
    fail "could not synchronize PostgreSQL password"
  fi

  rm -f "${sql_file}"

  printf 'PostgreSQL user password: synchronized\n'
}

apply_migrations() {
  log "执行 PostgreSQL Migration"

  local postgres_database
  local postgres_user
  local migration_file
  local -a migration_files=()

  postgres_database="$(
    env_value_or_default "POSTGRES_DB" "geo_posts"
  )"

  postgres_user="$(
    env_value_or_default "POSTGRES_USER" "geo_posts"
  )"

  mapfile -t migration_files < <(
    find "${MIGRATIONS_DIR}" \
      -maxdepth 1 \
      -type f \
      -name '*.sql' \
      -print \
      | sort
  )

  ((${#migration_files[@]} > 0)) \
    || fail \
      "no PostgreSQL migrations found in ${MIGRATIONS_DIR}"

  for migration_file in "${migration_files[@]}"; do
    printf \
      'Applying PostgreSQL migration: %s\n' \
      "$(basename "${migration_file}")"

    docker exec -i "${POSTGRES_CONTAINER}" \
      psql \
      -U "${postgres_user}" \
      -d "${postgres_database}" \
      -v ON_ERROR_STOP=1 \
      < "${migration_file}"
  done

  printf \
    'PostgreSQL migrations: OK (%d files)\n' \
    "${#migration_files[@]}"
}


ensure_redis_tunnel() {
  log "检查 Redis SSH 隧道"

  local redis_host
  local redis_port
  local ssh_host
  local ssh_user
  local remote_host
  local remote_port

  redis_host="$(
    env_value_or_default REDIS_HOST 127.0.0.1
  )"

  redis_port="$(
    env_value_or_default REDIS_PORT 16379
  )"

  ssh_host="$(read_env_value REDIS_SSH_HOST)"

  ssh_user="$(
    env_value_or_default REDIS_SSH_USER ubuntu
  )"

  remote_host="$(
    env_value_or_default REDIS_REMOTE_HOST 127.0.0.1
  )"

  remote_port="$(
    env_value_or_default REDIS_REMOTE_PORT 6379
  )"

  if redis_ping "${redis_host}" "${redis_port}"; then
    printf 'Redis tunnel already available: %s:%s\n' \
      "${redis_host}" \
      "${redis_port}"

    return
  fi

  [[ -n "${ssh_host}" ]] \
    || fail "REDIS_SSH_HOST is missing"

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


bootstrap_posts() {
  # 保留原函数名，避免修改主恢复流程的调用顺序。
  #
  # 旧实现仅同步 POST_BOOTSTRAP_LIMIT（默认 1000）条帖子，
  # 在 Docker 数据卷丢失后会留下一个看似正常、实际不完整的数据库。
  #
  # 新实现委托给 restore_search_assets.sh：
  #   远程 MySQL 精确对账
  #   → 必要时全量幂等同步
  #   → BGE 模型恢复或下载
  #   → 缺失 Embedding 断点续建
  #   → HNSW 和向量完整性检查
  local restore_args=()

  if ((SKIP_SYNC == 1)); then
    restore_args+=(--skip-sync)
  fi

  bash \
    "${ROOT_DIR}/scripts/restore_search_assets.sh" \
    "${restore_args[@]}"
}

show_summary() {
  log "恢复结果"

  local postgres_user
  local postgres_db
  local redis_host
  local redis_port

  postgres_user="$(read_env_value POSTGRES_USER)"
  postgres_db="$(read_env_value POSTGRES_DB)"

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

  redis_host="$(
    env_value_or_default REDIS_HOST 127.0.0.1
  )"

  redis_port="$(
    env_value_or_default REDIS_PORT 16379
  )"

  if redis_ping "${redis_host}" "${redis_port}"; then
    printf 'Redis tunnel: PONG (%s:%s)\n' \
      "${redis_host}" \
      "${redis_port}"
  else
    fail "Redis PING failed during final summary"
  fi

  printf 'Python environment: %s\n' \
    "${ROOT_DIR}/.venv/bin/python"

  printf 'Environment file: %s\n' \
    "${ENV_FILE}"
}


main() {
  cd "${ROOT_DIR}"

  [[ -f "${POSTGRES_COMPOSE_FILE}" ]] \
    || fail "compose.postgres.yml does not exist"

  [[ -d "${MIGRATIONS_DIR}" ]] \
    || fail "PostgreSQL migrations directory does not exist"

  compgen -G "${MIGRATIONS_DIR}/*.sql" >/dev/null \
    || fail "no PostgreSQL migration files found"

  [[ -f "${CONFIGURE_REMOTE_SCRIPT}" ]] \
    || fail "configure_remote_sources.sh does not exist"

  [[ -f "${START_DEV_SCRIPT}" ]] \
    || fail "start_dev.sh does not exist"

  [[ -f "${ROOT_DIR}/requirements.txt" ]] \
    || fail "requirements.txt does not exist"

  bootstrap_system_dependencies
  ensure_python_environment
  ensure_env_configuration

  start_postgres
  synchronize_postgres_password
  apply_migrations
  ensure_redis_tunnel
  bootstrap_posts
  show_summary

  if ((INFRA_ONLY == 1)); then
    log "基础设施恢复完成"
    return
  fi

  log "启动开发服务"

  bash "${START_DEV_SCRIPT}"
}


main
