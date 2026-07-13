#!/usr/bin/env python3

import argparse
import csv
import statistics
from collections import Counter
from pathlib import Path


REQUIRED_COLUMNS = {
    "id",
    "owenerid",
    "title",
    "detail",
    "typecategory",
    "tags",
    "createtime",
    "from_lat",
    "from_lng",
    "city",
    "district",
    "visiblestatus",
}


def clean(value: str | None) -> str:
    if value is None or value == r"\N":
        return ""
    return (
        value.replace(r"\n", "\n")
        .replace(r"\t", "\t")
        .replace(r"\\", "\\")
        .strip()
    )


def parse_float(value: str | None) -> float | None:
    value = clean(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def percentile(values: list[int], ratio: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = int((len(ordered) - 1) * ratio)
    return float(ordered[index])


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 tiezi_geo_new TSV 数据质量")
    parser.add_argument("input_file", type=Path)
    args = parser.parse_args()

    path = args.input_file
    if not path.exists():
        raise SystemExit(f"文件不存在：{path}")

    total = 0
    ids: set[str] = set()
    duplicate_ids: list[str] = []

    categories: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    cities: Counter[str] = Counter()

    empty_titles = 0
    empty_details = 0
    empty_all_text = 0
    invalid_geo = 0
    missing_geo = 0

    text_lengths: list[int] = []
    samples: list[dict[str, str]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")

        if reader.fieldnames is None:
            raise SystemExit("未检测到 TSV 表头")

        print("字段数量：", len(reader.fieldnames))
        print("字段列表：")
        for index, name in enumerate(reader.fieldnames, start=1):
            print(f"  {index:02d}. {name!r}")

        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            raise SystemExit(
                "缺少必要字段：" + ", ".join(sorted(missing_columns))
            )

        for row in reader:
            total += 1

            source_id = clean(row.get("id"))
            title = clean(row.get("title"))
            detail = clean(row.get("detail"))
            category = clean(row.get("typecategory")) or "[EMPTY]"
            status = clean(row.get("visiblestatus")) or "[EMPTY]"
            city = clean(row.get("city")) or "[EMPTY]"

            if source_id in ids:
                duplicate_ids.append(source_id)
            else:
                ids.add(source_id)

            categories[category] += 1
            statuses[status] += 1
            cities[city] += 1

            if not title:
                empty_titles += 1
            if not detail:
                empty_details += 1
            if not title and not detail:
                empty_all_text += 1

            latitude = parse_float(row.get("from_lat"))
            longitude = parse_float(row.get("from_lng"))

            if latitude is None or longitude is None:
                missing_geo += 1
            elif not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                invalid_geo += 1

            embedding_text = "\n".join(
                part
                for part in (
                    title,
                    detail,
                    f"类别：{category}" if category != "[EMPTY]" else "",
                    f"标签：{clean(row.get('tags'))}"
                    if clean(row.get("tags"))
                    else "",
                )
                if part
            )
            text_lengths.append(len(embedding_text))

            if len(samples) < 3:
                samples.append(
                    {
                        "id": source_id,
                        "title": title[:80],
                        "detail": detail[:120],
                        "category": category,
                        "city": city,
                    }
                )

    print("\n========== 基础统计 ==========")
    print(f"总数据行数：{total}")
    print(f"唯一 ID 数：{len(ids)}")
    print(f"重复 ID 数：{len(duplicate_ids)}")
    print(f"空标题数：{empty_titles}")
    print(f"空正文数：{empty_details}")
    print(f"标题正文均为空：{empty_all_text}")
    print(f"缺失经纬度：{missing_geo}")
    print(f"非法经纬度：{invalid_geo}")

    if text_lengths:
        print("\n========== 向量文本长度 ==========")
        print(f"最短：{min(text_lengths)}")
        print(f"平均：{statistics.mean(text_lengths):.2f}")
        print(f"中位数：{statistics.median(text_lengths):.2f}")
        print(f"P95：{percentile(text_lengths, 0.95):.0f}")
        print(f"最长：{max(text_lengths)}")

    print("\n========== 类别分布 ==========")
    for name, count in categories.most_common():
        print(f"{name}: {count}")

    print("\n========== 状态分布 ==========")
    for name, count in statuses.most_common():
        print(f"{name}: {count}")

    print("\n========== 城市 Top 10 ==========")
    for name, count in cities.most_common(10):
        print(f"{name}: {count}")

    print("\n========== 脱敏样本 ==========")
    for sample in samples:
        print(
            f"id={sample['id']} | "
            f"category={sample['category']} | "
            f"city={sample['city']}\n"
            f"title={sample['title']}\n"
            f"detail={sample['detail']}\n"
        )

    if total == 0:
        raise SystemExit("检查失败：文件中没有数据")

    if duplicate_ids:
        print("警告：检测到重复 ID，例如：", duplicate_ids[:10])

    print("检查完成。")


if __name__ == "__main__":
    main()
