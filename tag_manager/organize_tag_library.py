# -*- coding: utf-8 -*-
"""全量整理夜之主衣柜 tag 分类。

不删除任何 tag，不改英文/中文原文。只重写一级/二级分类，并刷新 tag_library.json。
默认 dry-run；传入 --apply 才写库。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .tag_taxonomy import (
    CATEGORY_NOTES,
    CATEGORY_SORT,
    CONTROLLED_SUBS,
    PRIMARY_CATEGORIES,
    PRIMARY_MERGE,
    classify,
    merge_primary,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "tag_wardrobe.sqlite3"
JSON_PATH = BASE_DIR / "tag_library.json"

KEEP_GROUP_CATEGORIES = {"涩涩", "视角", "通用", "tag组合"}
DROP_EMPTY_TAG_CATEGORIES = set(PRIMARY_MERGE) | {"2.身体特征", "5.姿势动作", "6.构图镜头", "7.场景环境", "NSFW Tags"}


def backup_db(db_path: Path) -> Path:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = db_path.with_name(f"tag_wardrobe_backup_{ts}.sqlite3")
    shutil.copy2(db_path, dest)
    return dest


def ensure_categories(conn: sqlite3.Connection) -> None:
    for name, order in CATEGORY_SORT.items():
        conn.execute(
            """
            INSERT INTO categories (name, kind, sort_order, notes)
            VALUES (?, 'tag', ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                kind='tag',
                sort_order=excluded.sort_order,
                notes=COALESCE(NULLIF(excluded.notes, ''), categories.notes),
                updated_at=CURRENT_TIMESTAMP
            """,
            (name, order, CATEGORY_NOTES.get(name, "")),
        )


def export_library(conn: sqlite3.Connection, json_path: Path) -> None:
    categories = [
        {"name": r["name"], "kind": r["kind"], "sort_order": r["sort_order"], "notes": r["notes"]}
        for r in conn.execute("SELECT name, kind, sort_order, notes FROM categories ORDER BY sort_order, name")
    ]
    tags = [
        {
            "tag": r["tag"],
            "zh": r["zh"],
            "category": r["category"],
            "subcategory": r["subcategory"],
            "source": r["source"],
            "rating": r["rating"],
            "notes": r["notes"],
        }
        for r in conn.execute(
            "SELECT tag, zh, category, subcategory, source, rating, notes FROM tags ORDER BY category, subcategory, tag"
        )
    ]
    json_path.write_text(json.dumps({"categories": categories, "tags": tags}, ensure_ascii=False, indent=2), encoding="utf-8")


def drop_unused_tag_categories(conn: sqlite3.Connection) -> list[str]:
    used = {r[0] for r in conn.execute("SELECT DISTINCT category FROM tags")}
    removed = []
    for name, kind in conn.execute("SELECT name, kind FROM categories"):
        if kind != "tag":
            continue
        if name in KEEP_GROUP_CATEGORIES:
            continue
        if name in used:
            continue
        if name in DROP_EMPTY_TAG_CATEGORIES or name not in PRIMARY_CATEGORIES:
            conn.execute("DELETE FROM categories WHERE name=?", (name,))
            removed.append(name)
    return removed


def load_semantic_lookup() -> dict[str, tuple[str, str]]:
    map_path = BASE_DIR / "tag_review" / "manual_map.json"
    if not map_path.exists():
        return {}
    data = json.loads(map_path.read_text(encoding="utf-8"))
    lookup = {item["tag"]: (item["category"], item["subcategory"]) for item in data}
    try:
        from .tag_review.corrections import FIX
    except ImportError:
        FIX = {}
    lookup.update(FIX)
    return lookup


def plan_changes(rows: list[sqlite3.Row]) -> tuple[list[tuple], Counter, Counter, Counter]:
    updates: list[tuple] = []
    cat_moves: Counter = Counter()
    new_dist: Counter = Counter()
    sub_dist: Counter = Counter()
    semantic = load_semantic_lookup()
    for row in rows:
        if row["tag"] in semantic:
            new_cat, new_sub = semantic[row["tag"]]
        else:
            new_cat, new_sub = classify(row["tag"], row["zh"] or "", row["category"] or "", row["subcategory"] or "")
        old_cat, old_sub = row["category"] or "", row["subcategory"] or ""
        new_dist[new_cat] += 1
        sub_dist[(new_cat, new_sub)] += 1
        if new_cat != old_cat or new_sub != old_sub:
            updates.append((row["id"], row["tag"], old_cat, old_sub, new_cat, new_sub))
            if new_cat != old_cat:
                cat_moves[(old_cat, new_cat)] += 1
    return updates, cat_moves, new_dist, sub_dist


def print_report(original_count: int, updates: list[tuple], cat_moves: Counter, new_dist: Counter, sub_dist: Counter) -> None:
    print(f"原库 {original_count} 条，将改分类 {len(updates)} 条")
    print("\n一级分类迁移（原 → 新）:")
    for (old, new), n in cat_moves.most_common(30):
        print(f"  {old or '(空)'} → {new}: {n}")
    print("\n整理后一级分类存量:")
    for cat, n in sorted(new_dist.items(), key=lambda x: -x[1]):
        print(f"  {n:5d}  {cat}")
    print("\n整理后二级分类:")
    for (cat, sub), n in sorted(sub_dist.items(), key=lambda item: (item[0][0], -item[1], item[0][1])):
        print(f"  {n:5d}  {cat} / {sub}")
    print("\n抽样 25 条改动:")
    for item in updates[:25]:
        _id, tag, old_cat, old_sub, new_cat, new_sub = item
        print(f"  {tag} | {old_cat}/{old_sub} -> {new_cat}/{new_sub}")

    leftover_other = sum(n for (cat, sub), n in sub_dist.items() if sub in {"其他", "其他服饰", "其他角色"} and cat != "4.角色/作品")
    char_other = sub_dist.get(("4.角色/作品", "其他角色"), 0)
    print(f"\n「其他」类合计（不含角色）: {leftover_other}")
    print(f"4.角色/作品 / 其他角色: {char_other}")

    illegal = []
    for (cat, sub), n in sub_dist.items():
        if cat == "4.角色/作品":
            continue
        allowed = CONTROLLED_SUBS.get(cat)
        if allowed and sub not in allowed:
            illegal.append((cat, sub, n))
    if illegal:
        print("\n不受控二级分类:")
        for cat, sub, n in illegal:
            print(f"  {n:5d}  {cat} / {sub}")
    else:
        print("\n所有非角色二级分类均在受控词表内。")


def apply_updates(conn: sqlite3.Connection, updates: list[tuple]) -> None:
    conn.executemany(
        """
        UPDATE tags
        SET category=?, subcategory=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        [(new_cat, new_sub, row_id) for row_id, _tag, _o_cat, _o_sub, new_cat, new_sub in updates],
    )


GOLDEN = {
    "touhou": ("4.角色/作品", "东方"),
    "genshin_impact": ("4.角色/作品", "原神"),
    "azur_lane": ("4.角色/作品", "碧蓝航线"),
    "blonde_hair": ("2.人物", "头发颜色"),
    "red_eyes": ("2.人物", "眼睛"),
    "large_breasts": ("2.人物", "身体"),
    "cowboy_shot": ("1.镜头", "景别"),
    "looking_at_viewer": ("5.动作", "视线"),
    "masterpiece": ("8.画风与质量", "质量"),
    "bikini": ("3.服饰", "内衣泳装"),
    "school_uniform": ("3.服饰", "制服套装"),
    "smile": ("4.表情", "笑"),
    "indoors": ("6.场景道具", "室内"),
    "outdoors": ("6.场景道具", "室外"),
    "sword": ("6.场景道具", "武器"),
    "after_sex": ("0.可以涩涩", "性行为"),
    "mosaic_censoring": ("0.可以涩涩", "马赛克"),
    "shiratama_(shiratamaco)": ("8.画风与质量", "画师"),
    "unleashed": ("5.动作", "动作"),
    "lunar": ("6.场景道具", "天气时间"),
    "tenga": ("0.可以涩涩", "其他"),
    "lycoris_recoil": ("4.角色/作品", "莉可丽丝"),
}


def verify_golden(conn: sqlite3.Connection) -> bool:
    ok = True
    for tag, (expect_cat, expect_sub) in GOLDEN.items():
        row = conn.execute("SELECT category, subcategory FROM tags WHERE tag=?", (tag,)).fetchone()
        if not row:
            print(f"  跳过（库中无此 tag）: {tag}")
            continue
        status = "OK" if (row["category"], row["subcategory"]) == (expect_cat, expect_sub) else "FAIL"
        if status != "OK":
            ok = False
        print(f"  {status} {tag} → {row['category']}/{row['subcategory']} (期望 {expect_cat}/{expect_sub})")
    return ok


def organize(db_path: Path, json_path: Path, apply: bool) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if not db_path.exists():
        print("找不到数据库", db_path)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    original_rows = list(conn.execute("SELECT * FROM tags"))
    original_names = [r["tag"] for r in original_rows]
    original_count = len(original_rows)
    updates, cat_moves, new_dist, sub_dist = plan_changes(original_rows)
    print_report(original_count, updates, cat_moves, new_dist, sub_dist)

    if not apply:
        print("\n这是 dry-run，未写库。通过 --apply 才会备份并提交。")
        conn.close()
        return 0

    backup = backup_db(db_path)
    print(f"\n已备份: {backup.name}")
    ensure_categories(conn)
    apply_updates(conn, updates)
    removed = drop_unused_tag_categories(conn)
    export_library(conn, json_path)
    conn.commit()

    final_count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    still = {r["tag"] for r in conn.execute("SELECT tag FROM tags")}
    missing = [t for t in original_names if t not in still]
    leftover = conn.execute(
        "SELECT COUNT(*) FROM tags WHERE subcategory IS NULL OR subcategory='' OR subcategory='未分类'"
    ).fetchone()[0]
    print("\n========== 校验 ==========")
    print(f"原 {original_count} → 现 {final_count}，删除 {len(missing)}，未分类 {leftover}")
    if removed:
        print("已删除空一级分类:", ", ".join(removed))
    print(f"已刷新 {json_path.name}")
    ok = verify_golden(conn)
    conn.close()
    if missing or leftover or not ok:
        print("校验未完全通过。")
        return 1
    print("完成。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全量整理 tag 一级/二级分类")
    parser.add_argument("--apply", action="store_true", help="写回 SQLite 并导出 JSON；默认只预览")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    args = parser.parse_args(argv)
    return organize(args.db, args.json, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
