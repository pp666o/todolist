#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
PERSIST_ENV="${HOME}/.config/geo-post-search/env"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

[[ -x "${PYTHON_BIN}" ]] || {
  echo "ERROR: Python environment is not ready: ${PYTHON_BIN}" >&2
  exit 1
}

cd "${ROOT_DIR}"

exec "${PYTHON_BIN}" - "${ENV_FILE}" "${PERSIST_ENV}" <<'PY'
import getpass
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pymysql


env_path = Path(sys.argv[1])
persistent_path = Path(sys.argv[2])


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        values[key] = value

    return values


def is_valid(value: str | None) -> bool:
    if value is None or not value.strip():
        return False

    placeholders = (
        "replace_with",
        "your-server",
        "这里填写",
        "placeholder",
    )

    lowered = value.lower()

    return not any(marker.lower() in lowered for marker in placeholders)


def first_valid(*values: str | None) -> str | None:
    for value in values:
        if is_valid(value):
            return value

    return None


current = read_env(env_path)
persistent = read_env(persistent_path)

postgres_password = first_valid(
    os.getenv("POSTGRES_PASSWORD"),
    current.get("POSTGRES_PASSWORD"),
    persistent.get("POSTGRES_PASSWORD"),
)

if postgres_password is None:
    try:
        output = subprocess.check_output(
            [
                "docker",
                "inspect",
                "geo-postgres",
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )

        for line in output.splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                candidate = line.split("=", 1)[1]

                if is_valid(candidate):
                    postgres_password = candidate
                    break

    except (OSError, subprocess.CalledProcessError):
        pass

if postgres_password is None:
    postgres_password = secrets.token_urlsafe(32)
    print("[INFO] 为新的 PostgreSQL 环境生成随机密码")
else:
    print("[OK] 已复用 PostgreSQL 密码")


mysql_password = first_valid(
    os.getenv("MYSQL_SOURCE_PASSWORD"),
    current.get("MYSQL_SOURCE_PASSWORD"),
    persistent.get("MYSQL_SOURCE_PASSWORD"),
)

if mysql_password is None:
    mysql_password = getpass.getpass(
        "请输入 MySQL 密码（仅首次配置需要）: "
    ).strip()

if not mysql_password:
    raise SystemExit("ERROR: MySQL 密码不能为空")


mysql_user = first_valid(
    os.getenv("MYSQL_SOURCE_USER"),
    current.get("MYSQL_SOURCE_USER"),
    persistent.get("MYSQL_SOURCE_USER"),
) or "root"

mysql_database = first_valid(
    os.getenv("MYSQL_SOURCE_DATABASE"),
    current.get("MYSQL_SOURCE_DATABASE"),
    persistent.get("MYSQL_SOURCE_DATABASE"),
) or "db.transform.ss"

mysql_table = first_valid(
    os.getenv("MYSQL_SOURCE_TABLE"),
    current.get("MYSQL_SOURCE_TABLE"),
    persistent.get("MYSQL_SOURCE_TABLE"),
) or "tiezi_geo_new"


targets = [
    ("internal", "172.17.0.12", 3306),
    ("public", "sh-cdb-im8up7xq.sql.tencentcdb.com", 63944),
]

selected_target: tuple[str, str, int] | None = None
errors: list[str] = []

print("========== 检测 MySQL 地址 ==========")

for mode, host, port in targets:
    print(f"测试 {mode}: {host}:{port}", flush=True)

    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database,
            charset="utf8mb4",
            connect_timeout=6,
            read_timeout=10,
            write_timeout=10,
        )

        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), VERSION()")
            database_name, mysql_version = cursor.fetchone()

        connection.close()

        print(
            f"[OK] database={database_name}, "
            f"version={mysql_version}"
        )

        selected_target = (mode, host, port)
        break

    except Exception as exc:
        error = f"{mode}: {type(exc).__name__}: {exc}"
        errors.append(error)
        print(f"[WARN] {error}", flush=True)

if selected_target is None:
    raise SystemExit(
        "ERROR: MySQL 内网和公网地址均无法连接："
        + " | ".join(errors)
    )

mysql_mode, mysql_host, mysql_port = selected_target

print(
    f"[OK] 最终使用 MySQL {mysql_mode}: "
    f"{mysql_host}:{mysql_port}"
)


redis_ssh_host = first_valid(
    os.getenv("REDIS_SSH_HOST"),
    current.get("REDIS_SSH_HOST"),
    persistent.get("REDIS_SSH_HOST"),
) or "101.43.72.189"

redis_ssh_user = first_valid(
    os.getenv("REDIS_SSH_USER"),
    current.get("REDIS_SSH_USER"),
    persistent.get("REDIS_SSH_USER"),
) or "ubuntu"

redis_password = (
    os.getenv("REDIS_PASSWORD")
    if os.getenv("REDIS_PASSWORD") is not None
    else current.get(
        "REDIS_PASSWORD",
        persistent.get("REDIS_PASSWORD", ""),
    )
)


settings = {
    "POSTGRES_DB": "geo_posts",
    "POSTGRES_USER": "geo_posts",
    "POSTGRES_PASSWORD": postgres_password,
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",

    "MYSQL_SOURCE_HOST": mysql_host,
    "MYSQL_SOURCE_PORT": str(mysql_port),
    "MYSQL_SOURCE_USER": mysql_user,
    "MYSQL_SOURCE_PASSWORD": mysql_password,
    "MYSQL_SOURCE_DATABASE": mysql_database,
    "MYSQL_SOURCE_TABLE": mysql_table,
    "MYSQL_SOURCE_CHARSET": "utf8mb4",

    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "16379",
    "REDIS_DB": "0",
    "REDIS_PASSWORD": redis_password or "",
    "REDIS_SOCKET_TIMEOUT_SECONDS": "3",

    "REDIS_SSH_HOST": redis_ssh_host,
    "REDIS_SSH_USER": redis_ssh_user,
    "REDIS_REMOTE_HOST": "127.0.0.1",
    "REDIS_REMOTE_PORT": "6379",

    "POST_BOOTSTRAP_LIMIT": "1000",
}


managed_prefixes = (
    "POSTGRES_",
    "MYSQL_SOURCE_",
    "REDIS_",
)

managed_keys = {
    "POST_BOOTSTRAP_LIMIT",
}

kept_lines: list[str] = []

if env_path.exists():
    for raw_line in env_path.read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = raw_line.strip()

        if (
            stripped
            and not stripped.startswith("#")
            and "=" in stripped
        ):
            key = stripped.split("=", 1)[0].strip()

            if (
                key.startswith(managed_prefixes)
                or key in managed_keys
            ):
                continue

        kept_lines.append(raw_line)

while kept_lines and not kept_lines[-1].strip():
    kept_lines.pop()


sections = [
    (
        "PostgreSQL / pgvector",
        (
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
        ),
    ),
    (
        "Remote MySQL post source",
        (
            "MYSQL_SOURCE_HOST",
            "MYSQL_SOURCE_PORT",
            "MYSQL_SOURCE_USER",
            "MYSQL_SOURCE_PASSWORD",
            "MYSQL_SOURCE_DATABASE",
            "MYSQL_SOURCE_TABLE",
            "MYSQL_SOURCE_CHARSET",
        ),
    ),
    (
        "Redis realtime feature service",
        (
            "REDIS_HOST",
            "REDIS_PORT",
            "REDIS_DB",
            "REDIS_PASSWORD",
            "REDIS_SOCKET_TIMEOUT_SECONDS",
        ),
    ),
    (
        "Redis SSH tunnel",
        (
            "REDIS_SSH_HOST",
            "REDIS_SSH_USER",
            "REDIS_REMOTE_HOST",
            "REDIS_REMOTE_PORT",
        ),
    ),
    (
        "Bootstrap",
        (
            "POST_BOOTSTRAP_LIMIT",
        ),
    ),
]

output = list(kept_lines)

for section_name, keys in sections:
    output.append("")
    output.append(f"# {section_name}")

    for key in keys:
        output.append(
            f"{key}="
            f"{json.dumps(settings[key], ensure_ascii=False)}"
        )

content = "\n".join(output).lstrip("\n").rstrip() + "\n"

env_path.write_text(content, encoding="utf-8")
env_path.chmod(0o600)

persistent_path.parent.mkdir(parents=True, exist_ok=True)
persistent_path.parent.chmod(0o700)

persistent_path.write_text(content, encoding="utf-8")
persistent_path.chmod(0o600)

print(f"[OK] 配置已写入：{env_path}")
print(f"[OK] 持久化配置：{persistent_path}")
print("[OK] Redis 将在恢复脚本中建立隧道后检查")
PY
