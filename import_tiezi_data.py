#!/usr/bin/env python3
"""Import a TSV export of db.transform.ss.tiezi_geo_new into PostgreSQL."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

SOURCE_NAME = "tiezi_geo_new"
SOURCE_TZ = ZoneInfo("Asia/Shanghai")


def clean(value: str | None) -> str | None:
    if value is None or value == r"\N":
        return None
    value = value.strip()
    return value or None


def parse_int(value: str | None) -> int | None:
    value = clean(value)
    return int(value) if value is not None else None


def parse_float(value: str | None) -> float | None:
    value = clean(value)
    return float(value) if value is not None else None


def parse_datetime(value: str | None) -> datetime | None:
    value = clean(value)
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SOURCE_TZ)
    return parsed


def build_content(title: str | None, detail: str | None) -> str:
    parts = [part for part in (title, detail) if part]
    return "\n".join(parts)


def build_embedding_text(
    title: str | None,
    detail: str | None,
    category: str | None,
    tags: str | None,
) -> str:
    parts = [
        title,
        detail,
        f"类别：{category}" if category else None,
        f"标签：{tags}" if tags else None,
    ]
    return "\n".join(part for part in parts if part)


def chunks(items: list[dict[str, str]], size: int) -> Iterable[list[dict[str, str]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def load_rows(path: Path, max_rows: int | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "id" not in reader.fieldnames:
            raise ValueError("TSV is missing the id column")
        for row in reader:
            rows.append(row)
            if max_rows is not None and len(rows) >= max_rows:
                break
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = load_rows(args.input_file, args.max_rows)
    print(f"Loaded {len(rows)} rows from {args.input_file}")

    if args.dry_run:
        sample = rows[0]
        print("Dry run only. First source id:", sample.get("id"))
        print("First embedding text length:", len(build_embedding_text(
            clean(sample.get("title")),
            clean(sample.get("detail")),
            clean(sample.get("typecategory")),
            clean(sample.get("tags")),
        )))
        return

    # Heavy dependencies are imported only for a real database import.
    # This keeps --dry-run usable before PostgreSQL and ML dependencies
    # are installed.
    from sqlalchemy import select

    from app.database import Base, SessionLocal, engine
    from app.models import Todo
    from app.utils import model

    Base.metadata.create_all(bind=engine)

    inserted = 0
    skipped = 0
    with SessionLocal() as session:
        existing_ids = set(
            session.scalars(
                select(Todo.source_id).where(Todo.source == SOURCE_NAME)
            ).all()
        )

        for batch_number, batch in enumerate(chunks(rows, args.batch_size), start=1):
            pending = [row for row in batch if clean(row.get("id")) not in existing_ids]
            skipped += len(batch) - len(pending)
            if not pending:
                continue

            texts = [
                build_embedding_text(
                    clean(row.get("title")),
                    clean(row.get("detail")),
                    clean(row.get("typecategory")),
                    clean(row.get("tags")),
                )
                for row in pending
            ]
            vectors = model.encode(
                texts,
                batch_size=args.batch_size,
                show_progress_bar=False,
                normalize_embeddings=False,
            )

            objects: list[Todo] = []
            for row, vector in zip(pending, vectors, strict=True):
                source_id = clean(row.get("id"))
                title = clean(row.get("title"))
                detail = clean(row.get("detail"))
                objects.append(
                    Todo(
                        source=SOURCE_NAME,
                        source_id=source_id,
                        user_id=parse_int(row.get("owenerid")),
                        title=title,
                        detail=detail,
                        content=build_content(title, detail),
                        category=clean(row.get("typecategory")),
                        tags=clean(row.get("tags")),
                        created_at=parse_datetime(row.get("createtime")),
                        updated_at=parse_datetime(row.get("updatetime")),
                        latitude=parse_float(row.get("from_lat")),
                        longitude=parse_float(row.get("from_lng")),
                        country=clean(row.get("country")),
                        province=clean(row.get("province")),
                        city=clean(row.get("city")),
                        district=clean(row.get("district")),
                        address=clean(row.get("address")),
                        like_count=parse_int(row.get("likes")),
                        view_count=parse_int(row.get("views")),
                        mark_count=parse_int(row.get("marks")),
                        dislike_count=parse_int(row.get("dislikes")),
                        rate_score=parse_float(row.get("ratescore")),
                        visible_status=parse_int(row.get("visiblestatus")),
                        embedding=vector.tolist(),
                        start_time=None,
                    )
                )
                existing_ids.add(source_id)

            session.add_all(objects)
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise

            inserted += len(objects)
            print(
                f"Batch {batch_number}: inserted={len(objects)} "
                f"total_inserted={inserted} skipped={skipped}"
            )

    print(f"Import complete: inserted={inserted}, skipped={skipped}")


if __name__ == "__main__":
    main()
