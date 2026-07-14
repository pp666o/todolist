#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose-infra.yaml"
PID_FILE="$ROOT_DIR/.fastapi.pid"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/fastapi.log"

log() {
    printf '\n========== %s ==========\n' "$1"
}

cd "$ROOT_DIR"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env 不存在，请先运行：" >&2
    echo "  ./scripts/bootstrap_env.sh" >&2
    exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "ERROR: .venv 不存在，请先运行：" >&2
    echo "  ./scripts/bootstrap_env.sh" >&2
    exit 1
fi

if ! compgen -G "$ROOT_DIR/cpp_core/todo_core*.so" >/dev/null; then
    echo "ERROR: C++ 扩展不存在，请先运行：" >&2
    echo "  ./scripts/bootstrap_env.sh" >&2
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

PYTHON="$VENV_DIR/bin/python"

log "启动 PostgreSQL"

docker compose \
    -f "$COMPOSE_FILE" \
    up -d postgres

POSTGRES_READY=0

for _ in $(seq 1 40); do
    if pg_isready \
        -h "$POSTGRES_BIND_IP" \
        -p "$POSTGRES_HOST_PORT" \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        >/dev/null 2>&1
    then
        POSTGRES_READY=1
        break
    fi

    sleep 2
done

if [ "$POSTGRES_READY" -ne 1 ]; then
    echo "ERROR: PostgreSQL 启动失败" >&2
    docker logs todo-postgres --tail 100 >&2
    exit 1
fi

echo "[OK] PostgreSQL ${POSTGRES_BIND_IP}:${POSTGRES_HOST_PORT}"

log "连接远程 Redis"

redis_ping() {
    redis-cli \
        -h 127.0.0.1 \
        -p "$REDIS_LOCAL_PORT" \
        --raw PING 2>/dev/null \
        | grep -qx "PONG"
}

if ! redis_ping; then
    ssh \
        -fNT \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=accept-new \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -L "127.0.0.1:${REDIS_LOCAL_PORT}:${REDIS_REMOTE_HOST}:${REDIS_REMOTE_PORT}" \
        "${REDIS_SSH_USER}@${REDIS_SSH_HOST}"
fi

if ! redis_ping; then
    echo "ERROR: Redis SSH 隧道创建失败" >&2
    exit 1
fi

echo "[OK] Redis 127.0.0.1:${REDIS_LOCAL_PORT}"

log "启动 FastAPI"

mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"

    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID"
        sleep 3
    fi

    rm -f "$PID_FILE"
fi

nohup "$PYTHON" -m uvicorn app.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"

API_READY=0

for _ in $(seq 1 120); do
    if curl -fsS \
        "http://127.0.0.1:${APP_PORT:-8000}/engine/status" \
        >/dev/null 2>&1
    then
        API_READY=1
        break
    fi

    sleep 2
done

if [ "$API_READY" -ne 1 ]; then
    echo "ERROR: FastAPI 启动失败" >&2
    tail -n 100 "$LOG_FILE" >&2
    exit 1
fi

echo "[OK] FastAPI http://127.0.0.1:${APP_PORT:-8000}"

log "运行状态"

curl -fsS \
    "http://127.0.0.1:${APP_PORT:-8000}/engine/status" \
    | "$PYTHON" -m json.tool

echo
echo "日志：$LOG_FILE"
echo "PostgreSQL volume：todo_postgres_data"
