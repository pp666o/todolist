from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor


COLUMNS = [
    "id",
    "title",
    "detail",
    "imgurl",
    "likes",
    "views",
    "marks",
    "typecategory",
    "ratescore",
    "visiblestatus",
    "owenerid",
    "createtime",
    "updatetime",
    "from_lat",
    "from_lng",
    "dislikes",
    "country",
    "province",
    "city",
    "address",
    "district",
    "tags",
]


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} 未配置")
    return value


def validate_identifier(value: str, name: str) -> str:
    # 数据库名中允许点，例如 db.transform.ss。
    safe = value.replace("_", "").replace(".", "")
    if not safe.isalnum():
        raise ValueError(f"{name} 包含不安全字符: {value!r}")
    return value


def serialize(value: object) -> str:
    if value is None:
        return ""

    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")

    return str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从腾讯云 MySQL 导出 tiezi_geo_new 为 TSV"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出 TSV 文件路径",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="最大导出行数，默认 100",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="起始偏移量，默认 0",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.limit <= 0:
        raise ValueError("--limit 必须大于 0")

    if args.offset < 0:
        raise ValueError("--offset 不能小于 0")

    host = required_env("SOURCE_MYSQL_HOST")
    port = int(required_env("SOURCE_MYSQL_PORT"))
    user = required_env("SOURCE_MYSQL_USER")
    password = required_env("SOURCE_MYSQL_PASSWORD")
    database = validate_identifier(
        required_env("SOURCE_MYSQL_DATABASE"),
        "SOURCE_MYSQL_DATABASE",
    )
    table = validate_identifier(
        required_env("SOURCE_MYSQL_TABLE"),
        "SOURCE_MYSQL_TABLE",
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    quoted_columns = ", ".join(f"`{column}`" for column in COLUMNS)
    query = (
        f"SELECT {quoted_columns} "
        f"FROM `{database}`.`{table}` "
        f"ORDER BY `id` "
        f"LIMIT {int(args.limit)} OFFSET {int(args.offset)}"
    )

    print(
        f"[INFO] MySQL source: {host}:{port}/"
        f"{database}.{table}"
    )
    print(
        f"[INFO] Export range: offset={args.offset}, "
        f"limit={args.limit}"
    )

    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=60,
        write_timeout=30,
        cursorclass=DictCursor,
        ssl_verify_cert=False,
        ssl_verify_identity=False,
    )

    exported = 0

    try:
        with connection.cursor() as cursor:
            cursor.execute(query)

            with output.open(
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=COLUMNS,
                    delimiter="\t",
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()

                while True:
                    rows = cursor.fetchmany(500)

                    if not rows:
                        break

                    for row in rows:
                        writer.writerow(
                            {
                                column: serialize(row.get(column))
                                for column in COLUMNS
                            }
                        )
                        exported += 1
    finally:
        connection.close()

    print(f"[OK] Exported rows: {exported}")
    print(f"[OK] Output: {output.resolve()}")


if __name__ == "__main__":
    main()
