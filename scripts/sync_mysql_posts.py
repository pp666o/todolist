"""Synchronize posts from remote MySQL into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from psycopg import Error as PostgresError
from pymysql import MySQLError

from app.infrastructure.mysql_source import (
    connect_mysql_source,
    get_mysql_source_settings,
    quote_mysql_identifier,
)
from app.infrastructure.postgres import connect_postgres
from app.repositories.post_repository import post_repository
from app.services.mysql_post_mapper import (
    MYSQL_POST_SOURCE,
    map_mysql_post_row,
)


DEFAULT_BATCH_SIZE = 1000
DEFAULT_MAX_ROWS = 1000
MAX_BATCH_SIZE = 10000

DEFAULT_MAX_RETRIES = 3
MAX_RETRIES = 10
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
MAX_RETRY_BACKOFF_SECONDS = 60.0

DEFAULT_CHECKPOINT_PATH = Path(
    "/root/.config/geo-post-search/"
    "mysql_post_sync_checkpoint.json"
)

CHECKPOINT_VERSION = 1

SYNC_MODES = (
    "bootstrap",
    "append",
    "full",
)

RETRYABLE_EXCEPTIONS = (
    MySQLError,
    PostgresError,
    ConnectionError,
    TimeoutError,
    OSError,
)

T = TypeVar("T")


MYSQL_POST_COLUMNS = """
    id,
    title,
    detail,
    typecategory,
    tags,
    createtime,
    updatetime,
    from_lat,
    from_lng,
    country,
    province,
    city,
    district,
    address,
    likes,
    views,
    marks,
    dislikes,
    ratescore,
    visiblestatus,
    owenerid
"""


def utc_now_iso() -> str:
    """Return the current UTC timestamp in a stable format."""
    return datetime.now(timezone.utc).isoformat()


def read_mysql_posts(
    limit: int,
    after_id: int,
) -> list[dict[str, Any]]:
    """Read one deterministic batch from the remote MySQL source."""
    get_mysql_source_settings.cache_clear()
    settings = get_mysql_source_settings()
    table = quote_mysql_identifier(settings.table)

    with connect_mysql_source() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    {MYSQL_POST_COLUMNS}
                FROM {table}
                WHERE id > %s
                ORDER BY id
                LIMIT %s
                """,
                (after_id, limit),
            )
            return list(cursor.fetchall())


async def read_postgres_summary() -> dict[str, Any]:
    """Return synchronization statistics from PostgreSQL."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT
                    count(*) AS row_count,
                    count(DISTINCT source_id) AS distinct_source_ids,
                    min(source_id::bigint) AS min_source_id,
                    max(source_id::bigint) AS max_source_id,
                    count(*) FILTER (
                        WHERE embedding IS NOT NULL
                    ) AS embedded_count
                FROM posts
                WHERE source = %s
                """,
                (MYSQL_POST_SOURCE,),
            )
            summary = await cursor.fetchone()

            await cursor.execute(
                """
                SELECT category, count(*) AS row_count
                FROM posts
                WHERE source = %s
                GROUP BY category
                ORDER BY category
                """,
                (MYSQL_POST_SOURCE,),
            )
            category_rows = await cursor.fetchall()

            await cursor.execute(
                """
                SELECT visible_status, count(*) AS row_count
                FROM posts
                WHERE source = %s
                GROUP BY visible_status
                ORDER BY visible_status
                """,
                (MYSQL_POST_SOURCE,),
            )
            status_rows = await cursor.fetchall()

    if summary is None:
        raise RuntimeError(
            "PostgreSQL synchronization summary was empty."
        )

    return {
        **summary,
        "categories": {
            row["category"]: int(row["row_count"])
            for row in category_rows
        },
        "visible_statuses": {
            row["visible_status"]: int(row["row_count"])
            for row in status_rows
        },
    }


async def read_postgres_max_source_id() -> int:
    """Return the greatest synchronized numeric MySQL source ID."""
    async with await connect_postgres() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT max(source_id::bigint) AS max_source_id
                FROM posts
                WHERE source = %s
                  AND source_id ~ '^[0-9]+$'
                """,
                (MYSQL_POST_SOURCE,),
            )
            row = await cursor.fetchone()

    if row is None or row["max_source_id"] is None:
        return 0

    return int(row["max_source_id"])


def validate_sync_parameters(
    *,
    batch_size: int,
    after_id: int,
    max_rows: int | None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> None:
    """Validate synchronization controls."""
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size must be between 1 and {MAX_BATCH_SIZE}."
        )

    if after_id < 0:
        raise ValueError("after_id cannot be negative.")

    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be positive when provided.")

    if not 0 <= max_retries <= MAX_RETRIES:
        raise ValueError(
            f"max_retries must be between 0 and {MAX_RETRIES}."
        )

    if not 0 <= retry_backoff_seconds <= MAX_RETRY_BACKOFF_SECONDS:
        raise ValueError(
            "retry_backoff_seconds must be between 0 and "
            f"{MAX_RETRY_BACKOFF_SECONDS}."
        )


def parse_numeric_source_ids(posts: list[Any]) -> list[int]:
    """Validate that mapped source IDs form a strictly increasing batch."""
    try:
        source_ids = [int(post.source_id) for post in posts]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "MySQL source IDs must be integer-compatible."
        ) from exc

    if len(set(source_ids)) != len(source_ids):
        raise RuntimeError(
            "Duplicate source IDs were found in the MySQL batch."
        )

    if any(
        current_id <= previous_id
        for previous_id, current_id in zip(
            source_ids,
            source_ids[1:],
        )
    ):
        raise RuntimeError(
            "MySQL source IDs were not strictly increasing."
        )

    return source_ids


def retry_delay(
    *,
    retry_number: int,
    backoff_seconds: float,
) -> float:
    """Return exponential retry delay for a 1-based retry number."""
    return backoff_seconds * (2 ** (retry_number - 1))


def run_with_retry(
    operation: Callable[[], T],
    *,
    operation_name: str,
    max_retries: int,
    backoff_seconds: float,
) -> T:
    """Run a synchronous transient operation with retry."""
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except RETRYABLE_EXCEPTIONS as exc:
            if attempt >= max_retries:
                print(
                    f"[ERROR] {operation_name} failed after "
                    f"{attempt + 1} attempts: "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

            retry_number = attempt + 1
            delay = retry_delay(
                retry_number=retry_number,
                backoff_seconds=backoff_seconds,
            )

            print(
                f"[WARN] {operation_name} failed: "
                f"{type(exc).__name__}: {exc}; "
                f"retry {retry_number}/{max_retries} "
                f"in {delay:.3f}s"
            )

            if delay > 0:
                time.sleep(delay)

    raise RuntimeError("Unreachable synchronous retry state.")


async def run_async_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    operation_name: str,
    max_retries: int,
    backoff_seconds: float,
) -> T:
    """Run an asynchronous transient operation with retry."""
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except RETRYABLE_EXCEPTIONS as exc:
            if attempt >= max_retries:
                print(
                    f"[ERROR] {operation_name} failed after "
                    f"{attempt + 1} attempts: "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

            retry_number = attempt + 1
            delay = retry_delay(
                retry_number=retry_number,
                backoff_seconds=backoff_seconds,
            )

            print(
                f"[WARN] {operation_name} failed: "
                f"{type(exc).__name__}: {exc}; "
                f"retry {retry_number}/{max_retries} "
                f"in {delay:.3f}s"
            )

            if delay > 0:
                await asyncio.sleep(delay)

    raise RuntimeError("Unreachable asynchronous retry state.")


def load_checkpoint(path: Path) -> dict[str, Any]:
    """Load and validate a synchronization checkpoint."""
    if not path.exists():
        raise FileNotFoundError(
            f"Synchronization checkpoint does not exist: {path}"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Synchronization checkpoint is not valid JSON: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            "Synchronization checkpoint must contain a JSON object."
        )

    if payload.get("version") != CHECKPOINT_VERSION:
        raise ValueError(
            "Unsupported synchronization checkpoint version: "
            f"{payload.get('version')!r}"
        )

    if payload.get("source") != MYSQL_POST_SOURCE:
        raise ValueError(
            "Synchronization checkpoint source does not match "
            f"{MYSQL_POST_SOURCE!r}."
        )

    try:
        last_source_id = int(payload["last_source_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Synchronization checkpoint has an invalid last_source_id."
        ) from exc

    if last_source_id < 0:
        raise ValueError(
            "Synchronization checkpoint last_source_id cannot be negative."
        )

    return payload


def write_checkpoint(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write a checkpoint atomically."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_name(
        f".{path.name}.tmp"
    )

    temporary_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(path)


def remove_checkpoint(path: Path) -> None:
    """Remove a previous checkpoint when present."""
    try:
        path.unlink()
    except FileNotFoundError:
        return


def build_checkpoint(
    *,
    status: str,
    initial_after_id: int,
    last_source_id: int,
    batch_size: int,
    max_rows: int | None,
    batch_count: int,
    loaded_rows: int,
    upserted_rows: int,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Build a serializable synchronization checkpoint."""
    payload: dict[str, Any] = {
        "version": CHECKPOINT_VERSION,
        "source": MYSQL_POST_SOURCE,
        "status": status,
        "initial_after_id": initial_after_id,
        "last_source_id": last_source_id,
        "batch_size": batch_size,
        "max_rows": max_rows,
        "batch_count": batch_count,
        "loaded_rows": loaded_rows,
        "upserted_rows": upserted_rows,
        "updated_at": utc_now_iso(),
    }

    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)

    return payload


def resolve_after_id(
    *,
    after_id: int,
    resume: bool,
    checkpoint_path: Path | None,
) -> int:
    """Resolve the initial cursor from CLI input or checkpoint."""
    if not resume:
        return after_id

    if checkpoint_path is None:
        raise ValueError(
            "--resume cannot be used together with --no-checkpoint."
        )

    if after_id != 0:
        raise ValueError(
            "--resume cannot be combined with a non-zero --after-id."
        )

    checkpoint = load_checkpoint(checkpoint_path)
    resolved_after_id = int(checkpoint["last_source_id"])

    print("========== Resume checkpoint ==========")
    print("checkpoint:", checkpoint_path)
    print("previous status:", checkpoint.get("status"))
    print("last source_id:", resolved_after_id)
    print("previous loaded rows:", checkpoint.get("loaded_rows"))
    print("previous updated_at:", checkpoint.get("updated_at"))

    return resolved_after_id


async def resolve_starting_after_id(
    *,
    mode: str,
    after_id: int,
    resume: bool,
    checkpoint_path: Path | None,
    max_retries: int,
    retry_backoff_seconds: float,
) -> int:
    """Resolve the starting source ID for a synchronization run."""
    if resume:
        return resolve_after_id(
            after_id=after_id,
            resume=True,
            checkpoint_path=checkpoint_path,
        )

    if mode == "append":
        resolved_after_id = await run_async_with_retry(
            read_postgres_max_source_id,
            operation_name=(
                "Read PostgreSQL append synchronization cursor"
            ),
            max_retries=max_retries,
            backoff_seconds=retry_backoff_seconds,
        )

        print("========== Append cursor ==========")
        print(
            "PostgreSQL max synchronized source_id:",
            resolved_after_id,
        )

        return resolved_after_id

    return after_id


async def synchronize(
    *,
    batch_size: int,
    after_id: int,
    max_rows: int | None,
    checkpoint_path: Path | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """Read and upsert one or more deterministic MySQL batches."""
    validate_sync_parameters(
        batch_size=batch_size,
        after_id=after_id,
        max_rows=max_rows,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )

    started_at = time.monotonic()
    cursor_id = after_id

    batch_count = 0
    total_loaded = 0
    total_upserted = 0

    category_counts: Counter[str] = Counter()
    status_counts: Counter[str | None] = Counter()

    source_exhausted = False

    def save_checkpoint(
        status: str,
        *,
        error: BaseException | None = None,
    ) -> None:
        if checkpoint_path is None:
            return

        write_checkpoint(
            checkpoint_path,
            build_checkpoint(
                status=status,
                initial_after_id=after_id,
                last_source_id=cursor_id,
                batch_size=batch_size,
                max_rows=max_rows,
                batch_count=batch_count,
                loaded_rows=total_loaded,
                upserted_rows=total_upserted,
                error=error,
            ),
        )

    print("========== Synchronization configuration ==========")
    print("batch_size:", batch_size)
    print("after_id:", after_id)
    print(
        "max_rows:",
        "all available rows" if max_rows is None else max_rows,
    )
    print("max_retries:", max_retries)
    print("retry_backoff_seconds:", retry_backoff_seconds)
    print(
        "checkpoint:",
        checkpoint_path if checkpoint_path else "disabled",
    )

    save_checkpoint("running")

    try:
        while max_rows is None or total_loaded < max_rows:
            if max_rows is None:
                current_limit = batch_size
            else:
                current_limit = min(
                    batch_size,
                    max_rows - total_loaded,
                )

            raw_rows = run_with_retry(
                lambda: read_mysql_posts(
                    limit=current_limit,
                    after_id=cursor_id,
                ),
                operation_name=(
                    f"MySQL batch read after source_id={cursor_id}"
                ),
                max_retries=max_retries,
                backoff_seconds=retry_backoff_seconds,
            )

            if not raw_rows:
                source_exhausted = True
                break

            if len(raw_rows) > current_limit:
                raise RuntimeError(
                    "MySQL returned more rows than the requested "
                    "batch limit."
                )

            posts = [
                map_mysql_post_row(row)
                for row in raw_rows
            ]
            source_ids = parse_numeric_source_ids(posts)

            first_source_id = source_ids[0]
            last_source_id = source_ids[-1]

            if first_source_id <= cursor_id:
                raise RuntimeError(
                    "MySQL cursor did not advance beyond after_id."
                )

            affected = await run_async_with_retry(
                lambda: post_repository.upsert_many(posts),
                operation_name=(
                    "PostgreSQL batch upsert "
                    f"{first_source_id}-{last_source_id}"
                ),
                max_retries=max_retries,
                backoff_seconds=retry_backoff_seconds,
            )

            if affected != len(posts):
                raise RuntimeError(
                    "PostgreSQL upsert count did not match "
                    "mapped post count."
                )

            batch_count += 1
            total_loaded += len(raw_rows)
            total_upserted += affected
            cursor_id = last_source_id

            category_counts.update(
                post.category for post in posts
            )
            status_counts.update(
                post.visible_status for post in posts
            )

            save_checkpoint("running")

            elapsed_seconds = time.monotonic() - started_at

            print(f"\n========== Batch {batch_count} ==========")
            print("requested rows:", current_limit)
            print("loaded rows:", len(raw_rows))
            print("first source_id:", first_source_id)
            print("last source_id:", last_source_id)
            print("upserted rows:", affected)
            print("total loaded:", total_loaded)
            print("total upserted:", total_upserted)
            print("elapsed seconds:", round(elapsed_seconds, 3))

            if len(raw_rows) < current_limit:
                source_exhausted = True
                break

        summary = await run_async_with_retry(
            read_postgres_summary,
            operation_name="PostgreSQL synchronization summary",
            max_retries=max_retries,
            backoff_seconds=retry_backoff_seconds,
        )

        if int(summary["row_count"]) != int(
            summary["distinct_source_ids"]
        ):
            raise RuntimeError(
                "PostgreSQL row count and distinct source ID "
                "count differ."
            )

        stopped_by_max_rows = (
            max_rows is not None
            and total_loaded >= max_rows
            and not source_exhausted
        )

        final_status = (
            "completed"
            if source_exhausted
            else "stopped_by_max_rows"
        )
        save_checkpoint(final_status)

        result = {
            "batch_count": batch_count,
            "loaded_rows": total_loaded,
            "upserted_rows": total_upserted,
            "initial_after_id": after_id,
            "last_source_id": cursor_id,
            "source_exhausted": source_exhausted,
            "stopped_by_max_rows": stopped_by_max_rows,
            "checkpoint_status": final_status,
            "checkpoint_path": (
                str(checkpoint_path)
                if checkpoint_path is not None
                else None
            ),
            "categories_in_run": dict(category_counts),
            "visible_statuses_in_run": dict(status_counts),
            "elapsed_seconds": round(
                time.monotonic() - started_at,
                3,
            ),
            "postgres_summary": summary,
        }

        print("\n========== Synchronization result ==========")
        for key, value in result.items():
            print(f"{key}: {value}")

        return result

    except Exception as exc:
        save_checkpoint(
            "failed",
            error=exc,
        )

        print("\n========== Synchronization failed ==========")
        print("last committed source_id:", cursor_id)
        print("committed batches:", batch_count)
        print("committed rows:", total_upserted)

        if checkpoint_path is not None:
            print(
                "resume command: "
                "PYTHONPATH=/workspace "
                ".venv/bin/python "
                "scripts/sync_mysql_posts.py "
                "--all --resume"
            )

        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize deterministic MySQL post batches "
            "into PostgreSQL."
        )
    )

    parser.add_argument(
        "--mode",
        choices=SYNC_MODES,
        default=None,
        help=(
            "Synchronization mode. bootstrap keeps the legacy "
            "bounded behavior; append starts after the greatest "
            "PostgreSQL source_id; full scans until MySQL is "
            "exhausted. Legacy --all selects full mode."
        ),
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "Rows read and committed per batch. "
            f"Default: {DEFAULT_BATCH_SIZE}."
        ),
    )

    parser.add_argument(
        "--after-id",
        type=int,
        default=0,
        help=(
            "Only synchronize MySQL rows with id greater "
            "than this value."
        ),
    )

    scope_group = parser.add_mutually_exclusive_group()

    scope_group.add_argument(
        "--all",
        action="store_true",
        help="Continue until no more MySQL rows are available.",
    )

    scope_group.add_argument(
        "--max-rows",
        "--limit",
        dest="max_rows",
        type=int,
        default=None,
        help=(
            "Maximum total rows synchronized in this run. "
            "--limit is retained for backward compatibility."
        ),
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=(
            "Retries after a transient MySQL or PostgreSQL "
            f"failure. Default: {DEFAULT_MAX_RETRIES}."
        ),
    )

    parser.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=DEFAULT_RETRY_BACKOFF_SECONDS,
        help=(
            "Initial exponential retry delay in seconds. "
            f"Default: {DEFAULT_RETRY_BACKOFF_SECONDS}."
        ),
    )

    parser.add_argument(
        "--checkpoint-file",
        default=str(DEFAULT_CHECKPOINT_PATH),
        help=(
            "Persistent checkpoint path. "
            f"Default: {DEFAULT_CHECKPOINT_PATH}."
        ),
    )

    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable checkpoint reads and writes for this run.",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume after the last successfully committed source ID.",
    )

    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Delete the selected checkpoint before starting.",
    )

    args = parser.parse_args()

    if args.mode is None:
        args.mode = "full" if args.all else "bootstrap"

    if args.all and args.mode != "full":
        parser.error(
            "--all is only compatible with --mode full."
        )

    if args.mode == "full":
        if args.max_rows is not None:
            parser.error(
                "--mode full cannot be combined with "
                "--max-rows or --limit."
            )

        args.max_rows = None

    elif args.mode == "append":
        if args.after_id != 0:
            parser.error(
                "--mode append cannot be combined with "
                "a non-zero --after-id."
            )

        # None means synchronize every currently available new row.
        # A positive --max-rows may be used for bounded verification.

    else:
        if args.all:
            parser.error(
                "--mode bootstrap cannot be combined with --all."
            )

        if args.max_rows is None:
            args.max_rows = DEFAULT_MAX_ROWS

    if args.no_checkpoint and args.resume:
        parser.error(
            "--resume cannot be combined with --no-checkpoint."
        )

    if args.no_checkpoint and args.reset_checkpoint:
        parser.error(
            "--reset-checkpoint cannot be combined "
            "with --no-checkpoint."
        )

    if args.resume and args.reset_checkpoint:
        parser.error(
            "--resume cannot be combined with --reset-checkpoint."
        )

    if args.resume and args.after_id != 0:
        parser.error(
            "--resume cannot be combined with "
            "a non-zero --after-id."
        )

    try:
        validate_sync_parameters(
            batch_size=args.batch_size,
            after_id=args.after_id,
            max_rows=args.max_rows,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))

    return args


def main() -> None:
    args = parse_args()

    checkpoint_path = (
        None
        if args.no_checkpoint
        else Path(args.checkpoint_file).expanduser()
    )

    if args.reset_checkpoint:
        if checkpoint_path is None:
            raise SystemExit(
                "ERROR: no checkpoint path was selected."
            )

        remove_checkpoint(checkpoint_path)
        print(
            "[OK] removed synchronization checkpoint:",
            checkpoint_path,
        )

    print("Selected synchronization mode:", args.mode)

    try:
        resolved_after_id = asyncio.run(
            resolve_starting_after_id(
                mode=args.mode,
                after_id=args.after_id,
                resume=args.resume,
                checkpoint_path=checkpoint_path,
                max_retries=args.max_retries,
                retry_backoff_seconds=(
                    args.retry_backoff_seconds
                ),
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    asyncio.run(
        synchronize(
            batch_size=args.batch_size,
            after_id=resolved_after_id,
            max_rows=args.max_rows,
            checkpoint_path=checkpoint_path,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
    )


if __name__ == "__main__":
    main()
