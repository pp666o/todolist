#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="/workspace"
ENV_FILE="${PROJECT_ROOT}/.env"

MYSQL_INTERNAL_HOST="172.17.0.12"
MYSQL_INTERNAL_PORT="3306"

MYSQL_PUBLIC_HOST="sh-cdb-im8up7xq.sql.tencentcdb.com"
MYSQL_PUBLIC_PORT="63944"

MYSQL_USER="root"
MYSQL_DATABASE="db.transform.ss"
MYSQL_TABLE="tiezi_geo_new"

REDIS_HOST="127.0.0.1"
REDIS_PORT="16379"

cd "$PROJECT_ROOT"

if [ ! -f "$ENV_FILE" ]; then
    touch "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

read -rs -p "请输入 MySQL 密码: " MYSQL_PASSWORD
echo

if [ -z "$MYSQL_PASSWORD" ]; then
    echo "MySQL 密码不能为空"
    exit 1
fi

export \
    MYSQL_INTERNAL_HOST \
    MYSQL_INTERNAL_PORT \
    MYSQL_PUBLIC_HOST \
    MYSQL_PUBLIC_PORT \
    MYSQL_USER \
    MYSQL_PASSWORD \
    MYSQL_DATABASE \
    MYSQL_TABLE \
    REDIS_HOST \
    REDIS_PORT

echo "========== 检测 MySQL 地址 =========="

MYSQL_RESULT="$(
.venv/bin/python - <<'PY'
import os
import pymysql

targets = [
    (
        "internal",
        os.environ["MYSQL_INTERNAL_HOST"],
        int(os.environ["MYSQL_INTERNAL_PORT"]),
    ),
    (
        "public",
        os.environ["MYSQL_PUBLIC_HOST"],
        int(os.environ["MYSQL_PUBLIC_PORT"]),
    ),
]

for name, host, port in targets:
    print(f"测试 {name}: {host}:{port}", flush=True)

    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=os.environ["MYSQL_USER"],
            password=os.environ["MYSQL_PASSWORD"],
            database=os.environ["MYSQL_DATABASE"],
            charset="utf8mb4",
            connect_timeout=6,
            read_timeout=10,
            write_timeout=10,
        )

        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), VERSION()")
            database, version = cursor.fetchone()

        connection.close()

        print(f"SUCCESS|{name}|{host}|{port}|{database}|{version}")
        break

    except Exception as exc:
        print(f"失败: {type(exc).__name__}: {exc}", flush=True)
else:
    raise SystemExit("两个 MySQL 地址均无法连接")
PY
)"

echo "$MYSQL_RESULT"

SUCCESS_LINE="$(printf '%s\n' "$MYSQL_RESULT" | grep '^SUCCESS|' | tail -1)"

MYSQL_MODE="$(printf '%s' "$SUCCESS_LINE" | cut -d'|' -f2)"
MYSQL_HOST="$(printf '%s' "$SUCCESS_LINE" | cut -d'|' -f3)"
MYSQL_PORT="$(printf '%s' "$SUCCESS_LINE" | cut -d'|' -f4)"

export MYSQL_HOST MYSQL_PORT

echo
echo "最终使用 MySQL ${MYSQL_MODE}: ${MYSQL_HOST}:${MYSQL_PORT}"

echo "========== 检测 Redis =========="

.venv/bin/python - <<'PY'
import os
import socket

host = os.environ["REDIS_HOST"]
port = int(os.environ["REDIS_PORT"])

with socket.create_connection((host, port), timeout=5) as sock:
    sock.sendall(b"*1\r\n$4\r\nPING\r\n")
    response = sock.recv(1024).decode("utf-8", errors="replace").strip()

print(f"Redis {host}:{port} 响应: {response}")

if not response:
    raise SystemExit("Redis 没有返回响应")
PY

echo "========== 写入唯一配置 =========="

.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

env_path = Path("/workspace/.env")
existing_lines = env_path.read_text(encoding="utf-8").splitlines()

managed_prefixes = (
    "MYSQL_SOURCE_",
    "REDIS_",
)

kept_lines = []

for line in existing_lines:
    stripped = line.strip()

    if any(stripped.startswith(prefix) for prefix in managed_prefixes):
        continue

    kept_lines.append(line)

settings = {
    "MYSQL_SOURCE_HOST": os.environ["MYSQL_HOST"],
    "MYSQL_SOURCE_PORT": os.environ["MYSQL_PORT"],
    "MYSQL_SOURCE_USER": os.environ["MYSQL_USER"],
    "MYSQL_SOURCE_PASSWORD": os.environ["MYSQL_PASSWORD"],
    "MYSQL_SOURCE_DATABASE": os.environ["MYSQL_DATABASE"],
    "MYSQL_SOURCE_TABLE": os.environ["MYSQL_TABLE"],
    "MYSQL_SOURCE_CHARSET": "utf8mb4",

    "REDIS_HOST": os.environ["REDIS_HOST"],
    "REDIS_PORT": os.environ["REDIS_PORT"],
}

kept_lines.extend([
    "",
    "# Remote MySQL post source",
])

for key in (
    "MYSQL_SOURCE_HOST",
    "MYSQL_SOURCE_PORT",
    "MYSQL_SOURCE_USER",
    "MYSQL_SOURCE_PASSWORD",
    "MYSQL_SOURCE_DATABASE",
    "MYSQL_SOURCE_TABLE",
    "MYSQL_SOURCE_CHARSET",
):
    kept_lines.append(
        f"{key}={json.dumps(settings[key], ensure_ascii=False)}"
    )

kept_lines.extend([
    "",
    "# Remote Redis realtime feature service",
    f"REDIS_HOST={json.dumps(settings['REDIS_HOST'])}",
    f"REDIS_PORT={json.dumps(settings['REDIS_PORT'])}",
])

env_path.write_text(
    "\n".join(kept_lines).rstrip() + "\n",
    encoding="utf-8",
)
env_path.chmod(0o600)

print(".env 已更新，旧的重复 MYSQL_SOURCE/REDIS 配置已删除")
PY

unset MYSQL_PASSWORD

echo "========== 最终 MySQL 业务检查 =========="

# 当前 Shell 可能继承旧 MYSQL_SOURCE_* 环境变量。
# Pydantic Settings 中进程环境变量优先于 .env，因此验证前必须清除。
unset MYSQL_SOURCE_HOST || true
unset MYSQL_SOURCE_PORT || true
unset MYSQL_SOURCE_USER || true
unset MYSQL_SOURCE_PASSWORD || true
unset MYSQL_SOURCE_DATABASE || true
unset MYSQL_SOURCE_TABLE || true
unset MYSQL_SOURCE_CHARSET || true


.venv/bin/python - <<'PY'
from app.infrastructure.mysql_source import (
    check_mysql_source_connection,
    get_mysql_source_settings,
)

get_mysql_source_settings.cache_clear()
result = check_mysql_source_connection()

print("database:", result["database_name"])
print("table:", result["table_name"])
print("row_count:", result["row_count"])
print("mysql_version:", result["mysql_version"])
PY

echo "========== 配置状态 =========="

.venv/bin/python - <<'PY'
from collections import Counter
from pathlib import Path

keys = []

for raw in Path(".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    key = line.split("=", 1)[0]

    if key.startswith("MYSQL_SOURCE_") or key.startswith("REDIS_"):
        keys.append(key)

counts = Counter(keys)

for key in sorted(counts):
    print(f"{key}: {counts[key]} occurrence")

if any(count != 1 for count in counts.values()):
    raise SystemExit("仍存在重复配置")
PY

echo
echo "远程 MySQL 和 Redis 配置完成。"
