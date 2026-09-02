# -*- coding: utf-8 -*-
"""把逐条语义映射写回 SQLite。不删 tag，不改原文。"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from .organize_tag_library import (
    DB_PATH,
    JSON_PATH,
    backup_db,
    drop_unused_tag_categories,
    ensure_categories,
    export_library,
    verify_golden,
)
from .tag_taxonomy import CONTROLLED_SUBS, PRIMARY_CATEGORIES

BASE_DIR = Path(__file__).resolve().parent
MAP_PATH = BASE_DIR / "tag_review" / "manual_map.json"


def load_fixes() -> dict[str, tuple[str, str]]:
    from .tag_review.corrections import FIX

    return FIX


def validate_pair(cat: str, sub: str) -> tuple[str, str]:
    if cat not in PRIMARY_CATEGORIES:
        raise ValueError(f"非法一级分类: {cat}/{sub}")
    if cat == "4.角色/作品":
        if not sub:
            return cat, "其他角色"
        return cat, sub
    allowed = CONTROLLED_SUBS[cat]
    if sub not in allowed:
        raise ValueError(f"非法二级分类: {cat}/{sub}")
    return cat, sub


def apply(db_path: Path = DB_PATH, json_path: Path = JSON_PATH) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    fixes = load_fixes()
    by_id = {item["id"]: item for item in mapping}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT id, tag, zh, category, subcategory FROM tags"))
    if len(rows) != len(by_id):
        print(f"映射 {len(by_id)} 条，数据库 {len(rows)} 条，拒绝写入")
        conn.close()
        return 1

    updates = []
    dist: Counter = Counter()
    other: Counter = Counter()
    for row in rows:
        item = by_id.get(row["id"])
        if not item or item.get("tag") != row["tag"]:
            print("id/tag 对不上", row["id"], row["tag"], item)
            conn.close()
            return 1
        cat, sub = item["category"], item["subcategory"]
        if row["tag"] in fixes:
            cat, sub = fixes[row["tag"]]
        cat, sub = validate_pair(cat, sub)
        dist[cat] += 1
        if sub in {"其他", "其他服饰", "其他角色"}:
            other[f"{cat}/{sub}"] += 1
        if cat != (row["category"] or "") or sub != (row["subcategory"] or ""):
            updates.append((cat, sub, row["id"]))

    print(f"将更新 {len(updates)} 条，总数 {len(rows)}")
    print("一级存量:")
    for cat, n in dist.most_common():
        print(f"  {n:5d}  {cat}")
    print("其他桶:")
    for k, n in other.most_common():
        print(f"  {n:5d}  {k}")

    backup = backup_db(db_path)
    print("备份", backup.name)
    ensure_categories(conn)
    conn.executemany(
        "UPDATE tags SET category=?, subcategory=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        updates,
    )
    drop_unused_tag_categories(conn)
    export_library(conn, json_path)
    conn.commit()
    leftover = conn.execute(
        "SELECT COUNT(*) FROM tags WHERE subcategory IS NULL OR subcategory='' OR subcategory='未分类'"
    ).fetchone()[0]
    print("未分类", leftover, "现存量", conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0])
    ok = verify_golden(conn)
    conn.close()
    return 0 if ok and leftover == 0 else 1


def main() -> int:
    return apply()


if __name__ == "__main__":
    raise SystemExit(main())
