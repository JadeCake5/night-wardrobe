from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .default_prompts import DEFAULT_NEGATIVE_TEMPLATE, DEFAULT_POSITIVE_TEMPLATE, DEFAULT_SYSTEM_PROMPT

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = BASE_DIR / "tag_wardrobe.sqlite3"


@contextmanager
def connect(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                kind TEXT DEFAULT 'tag',
                sort_order INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL UNIQUE,
                zh TEXT DEFAULT '',
                category TEXT DEFAULT '',
                subcategory TEXT DEFAULT '',
                source TEXT DEFAULT '',
                rating INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tag_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT '',
                positive_prompt TEXT DEFAULT '',
                negative_prompt TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                source TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS prompt_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                positive_template TEXT DEFAULT '',
                negative_template TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS gallery_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                category TEXT DEFAULT '',
                positive_prompt TEXT DEFAULT '',
                negative_prompt TEXT DEFAULT '',
                workflow_json TEXT DEFAULT '',
                prompt_json TEXT DEFAULT '',
                parameters TEXT DEFAULT '',
                checkpoint TEXT DEFAULT '',
                loras TEXT DEFAULT '',
                rating INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS llm_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                base_url TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                model TEXT DEFAULT '',
                default_system_prompt TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                lora TEXT DEFAULT '',
                lora_weight REAL DEFAULT 1.0,
                trigger_words TEXT DEFAULT '',
                appearance TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS character_outfits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                tags TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'scene',
                positive_prompt TEXT DEFAULT '',
                negative_prompt TEXT DEFAULT '',
                params_json TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                source TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        default_categories = [
            ("1.镜头", "tag", 10),
            ("2.人物", "tag", 20),
            ("3.服饰", "tag", 30),
            ("4.表情", "tag", 40),
            ("5.动作", "tag", 50),
            ("6.场景道具", "tag", 60),
            ("0.可以涩涩", "tag", 70),
            ("NSFW Tags", "tag", 80),
            ("tag组合", "group", 90),
            ("手工添加", "tag", 100),
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO categories (name, kind, sort_order)
            VALUES (?, ?, ?)
            """,
            default_categories,
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO prompt_templates
                (name, positive_template, negative_template, notes)
            VALUES (?, ?, ?, ?)
            """,
            ("默认 SDXL 提示词模板", DEFAULT_POSITIVE_TEMPLATE, DEFAULT_NEGATIVE_TEMPLATE, "内置默认模板，可在页面中编辑。"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO llm_settings
                (id, base_url, api_key, model, default_system_prompt)
            VALUES (1, '', '', '', ?)
            """,
            (DEFAULT_SYSTEM_PROMPT,),
        )


def upsert_category(name: str, kind: str = "tag", sort_order: int = 0, notes: str = "") -> None:
    name = clean_text(name)
    if not name:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO categories (name, kind, sort_order, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                kind=excluded.kind,
                notes=COALESCE(NULLIF(excluded.notes, ''), categories.notes),
                updated_at=CURRENT_TIMESTAMP
            """,
            (name, clean_text(kind) or "tag", sort_order, clean_text(notes)),
        )


def upsert_tag(tag: str, zh: str = "", category: str = "", subcategory: str = "", source: str = "", notes: str = "") -> None:
    tag = clean_text(tag)
    category = clean_text(category)
    if category:
        upsert_category(category)
    if not tag:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tags (tag, zh, category, subcategory, source, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tag) DO UPDATE SET
                zh = COALESCE(NULLIF(excluded.zh, ''), tags.zh),
                category = COALESCE(NULLIF(excluded.category, ''), tags.category),
                subcategory = COALESCE(NULLIF(excluded.subcategory, ''), tags.subcategory),
                source = CASE
                    WHEN tags.source = '' THEN excluded.source
                    WHEN excluded.source = '' THEN tags.source
                    WHEN instr(tags.source, excluded.source) > 0 THEN tags.source
                    ELSE tags.source || '; ' || excluded.source
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (tag, clean_text(zh), clean_text(category), clean_text(subcategory), clean_text(source), clean_text(notes)),
        )


def upsert_many_tags(rows: Iterable[tuple[str, str, str, str, str]]) -> int:
    count = 0
    for tag, zh, category, subcategory, source in rows:
        if clean_text(tag):
            upsert_tag(tag, zh, category, subcategory, source)
            count += 1
    return count


def upsert_group(name: str, category: str = "", positive_prompt: str = "", negative_prompt: str = "", notes: str = "", source: str = "") -> None:
    name = clean_text(name)
    category = clean_text(category)
    if category:
        upsert_category(category, kind="group")
    if not name:
        return
    with connect() as conn:
        existing = conn.execute("SELECT id FROM tag_groups WHERE name = ? AND source = ?", (name, source)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE tag_groups SET category=?, positive_prompt=?, negative_prompt=?, notes=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (category, positive_prompt, negative_prompt, notes, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO tag_groups (name, category, positive_prompt, negative_prompt, notes, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, category, positive_prompt, negative_prompt, notes, source),
            )


def upsert_character(name: str, lora: str = "", lora_weight: float = 1.0, trigger_words: str = "", appearance: str = "", notes: str = "") -> int:
    name = clean_text(name)
    if not name:
        return 0
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO characters (name, lora, lora_weight, trigger_words, appearance, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                lora=COALESCE(NULLIF(excluded.lora, ''), characters.lora),
                lora_weight=excluded.lora_weight,
                trigger_words=COALESCE(NULLIF(excluded.trigger_words, ''), characters.trigger_words),
                appearance=COALESCE(NULLIF(excluded.appearance, ''), characters.appearance),
                notes=COALESCE(NULLIF(excluded.notes, ''), characters.notes),
                updated_at=CURRENT_TIMESTAMP
            """,
            (name, clean_text(lora), lora_weight, clean_text(trigger_words), clean_text(appearance), clean_text(notes)),
        )
        row = conn.execute("SELECT id FROM characters WHERE name=?", (name,)).fetchone()
        return row["id"] if row else 0


def add_outfit(character_id: int, name: str, tags: str = "", notes: str = "") -> None:
    name = clean_text(name)
    if not name or not character_id:
        return
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM character_outfits WHERE character_id=? AND name=?", (character_id, name)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE character_outfits SET tags=?, notes=? WHERE id=?",
                (clean_text(tags), clean_text(notes), existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO character_outfits (character_id, name, tags, notes) VALUES (?, ?, ?, ?)",
                (character_id, name, clean_text(tags), clean_text(notes)),
            )


def upsert_recipe(name: str, type: str = "scene", positive_prompt: str = "", negative_prompt: str = "", params_json: str = "", notes: str = "", source: str = "") -> None:
    name = clean_text(name)
    if not name:
        return
    with connect() as conn:
        existing = conn.execute("SELECT id FROM recipes WHERE name=? AND type=?", (name, type)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE recipes SET positive_prompt=?, negative_prompt=?, params_json=?, notes=?, source=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (positive_prompt, negative_prompt, params_json, clean_text(notes), clean_text(source), existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO recipes (name, type, positive_prompt, negative_prompt, params_json, notes, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, type, positive_prompt, negative_prompt, params_json, clean_text(notes), clean_text(source)),
            )


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


init_db()
