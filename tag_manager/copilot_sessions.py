"""Workshop Copilot 会话与消息的 SQLite 数据层。

Session 是 Copilot 对话，不是 Workshop Prompt 快照。打开旧会话不得写回工作区。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .db import connect

DEFAULT_TITLE = "新会话"
TITLE_MAX_CHARS = 20
VALID_ROLES = ("user", "assistant", "error")
SNAPSHOT_KEYS = (
    "character",
    "outfit",
    "artist",
    "scene",
    "negative_template",
    "positive_preview",
    "negative_preview",
)


class SessionNotFound(Exception):
    """指定 session_id 不存在。"""

    def __init__(self, session_id: str = "") -> None:
        super().__init__("会话不存在")
        self.session_id = session_id
        self.message = "会话不存在"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return str(uuid.uuid4())


def _load_object(raw: Any, default: dict | None = None) -> dict:
    if default is None:
        default = {}
    if isinstance(raw, dict):
        return raw
    if not raw:
        return dict(default)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def normalize_snapshot(raw: Any) -> dict:
    """只保留轻量上下文字段，全部转为字符串。"""
    source = raw if isinstance(raw, dict) else {}
    snapshot = {}
    for key in SNAPSHOT_KEYS:
        value = source.get(key)
        snapshot[key] = "" if value is None else str(value)
    return snapshot


def default_title_from_text(text: str) -> str:
    """第一条 user message：清换行后截取约 18–24 个中文字符，不调用 LLM。"""
    cleaned = re.sub(r"[\r\n]+", " ", text or "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    if not cleaned:
        return DEFAULT_TITLE
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned
    return cleaned[:TITLE_MAX_CHARS]


def _row_session(row) -> dict:
    data = dict(row)
    return {
        "id": data["id"],
        "title": data["title"] or DEFAULT_TITLE,
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "context_snapshot": normalize_snapshot(_load_object(data.get("context_snapshot_json"))),
        "metadata": _load_object(data.get("metadata_json")),
        "parent_session_id": data.get("parent_session_id"),
    }


def _row_message(row) -> dict:
    data = dict(row)
    content = _load_object(data.get("content_json"))
    if not content.get("id"):
        content["id"] = data["id"]
    if not content.get("role"):
        content["role"] = data["role"]
    if not content.get("created_at"):
        content["created_at"] = data["created_at"]
    return {
        "id": data["id"],
        "session_id": data["session_id"],
        "seq": int(data["seq"]),
        "role": data["role"],
        "content": content,
        "created_at": data["created_at"],
    }


def create_session(
    *,
    title: str = DEFAULT_TITLE,
    context_snapshot: dict | None = None,
    metadata: dict | None = None,
    parent_session_id: str | None = None,
    connect_factory: Callable = connect,
) -> dict:
    session_id = _new_id()
    now = _now()
    cleaned_title = (title or "").strip() or DEFAULT_TITLE
    if len(cleaned_title) > TITLE_MAX_CHARS * 2:
        cleaned_title = cleaned_title[: TITLE_MAX_CHARS * 2]
    snapshot = normalize_snapshot(context_snapshot)
    meta = metadata if isinstance(metadata, dict) else {}
    parent = parent_session_id if parent_session_id else None
    with connect_factory() as conn:
        conn.execute(
            """
            INSERT INTO copilot_sessions
                (id, title, created_at, updated_at, context_snapshot_json, metadata_json, parent_session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, cleaned_title, now, now, _dump(snapshot), _dump(meta), parent),
        )
        row = conn.execute("SELECT * FROM copilot_sessions WHERE id=?", (session_id,)).fetchone()
    return _row_session(row)


def get_session(session_id: str, *, connect_factory: Callable = connect) -> dict | None:
    session_id = (session_id or "").strip()
    if not session_id:
        return None
    with connect_factory() as conn:
        row = conn.execute("SELECT * FROM copilot_sessions WHERE id=?", (session_id,)).fetchone()
    return _row_session(row) if row else None


def get_latest_session(*, connect_factory: Callable = connect) -> dict | None:
    with connect_factory() as conn:
        row = conn.execute(
            "SELECT * FROM copilot_sessions ORDER BY updated_at DESC, created_at DESC, id DESC LIMIT 1"
        ).fetchone()
    return _row_session(row) if row else None


def list_sessions(
    *,
    q: str = "",
    connect_factory: Callable = connect,
) -> list[dict]:
    query = "SELECT * FROM copilot_sessions"
    params: list[str] = []
    needle = (q or "").strip()
    if needle:
        query += " WHERE title LIKE ?"
        params.append(f"%{needle}%")
    query += " ORDER BY updated_at DESC, created_at DESC, id DESC"
    with connect_factory() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_session(row) for row in rows]


def list_messages(session_id: str, *, connect_factory: Callable = connect) -> list[dict]:
    session_id = (session_id or "").strip()
    if not session_id:
        return []
    with connect_factory() as conn:
        rows = conn.execute(
            "SELECT * FROM copilot_messages WHERE session_id=? ORDER BY seq ASC, created_at ASC",
            (session_id,),
        ).fetchall()
    return [_row_message(row) for row in rows]


def get_session_detail(session_id: str, *, connect_factory: Callable = connect) -> dict:
    session = get_session(session_id, connect_factory=connect_factory)
    if session is None:
        raise SessionNotFound(session_id)
    return {
        "session": session,
        "messages": list_messages(session_id, connect_factory=connect_factory),
    }


def rename_session(
    session_id: str,
    title: str,
    *,
    connect_factory: Callable = connect,
) -> dict:
    session = get_session(session_id, connect_factory=connect_factory)
    if session is None:
        raise SessionNotFound(session_id)
    cleaned = (title or "").strip()
    if not cleaned:
        raise ValueError("标题不能为空")
    if len(cleaned) > TITLE_MAX_CHARS * 2:
        cleaned = cleaned[: TITLE_MAX_CHARS * 2]
    now = _now()
    with connect_factory() as conn:
        conn.execute(
            "UPDATE copilot_sessions SET title=?, updated_at=? WHERE id=?",
            (cleaned, now, session_id),
        )
    updated = get_session(session_id, connect_factory=connect_factory)
    if updated is None:
        raise SessionNotFound(session_id)
    return updated


def delete_session(session_id: str, *, connect_factory: Callable = connect) -> dict:
    session = get_session(session_id, connect_factory=connect_factory)
    if session is None:
        raise SessionNotFound(session_id)
    with connect_factory() as conn:
        conn.execute("DELETE FROM copilot_messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM copilot_sessions WHERE id=?", (session_id,))
    return session


def require_session(session_id: str, *, connect_factory: Callable = connect) -> dict:
    session = get_session(session_id, connect_factory=connect_factory)
    if session is None:
        raise SessionNotFound(session_id)
    return session


def resolve_or_create_session(
    session_id: str | None,
    *,
    context_snapshot: dict | None = None,
    connect_factory: Callable = connect,
) -> dict:
    sid = (session_id or "").strip()
    if sid:
        return require_session(sid, connect_factory=connect_factory)
    return create_session(context_snapshot=context_snapshot, connect_factory=connect_factory)


def append_message(
    session_id: str,
    role: str,
    content: dict,
    *,
    connect_factory: Callable = connect,
) -> dict:
    session = require_session(session_id, connect_factory=connect_factory)
    if role not in VALID_ROLES:
        raise ValueError("未知的消息角色")
    if not isinstance(content, dict):
        content = {"text": str(content or ""), "parts": []}
    now = _now()
    message_id = str(content.get("id") or _new_id())
    payload = dict(content)
    payload["id"] = message_id
    payload["role"] = role
    payload.setdefault("created_at", now)
    payload.setdefault("parts", [])
    payload.setdefault("text", "")
    with connect_factory() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM copilot_messages WHERE session_id=?",
            (session_id,),
        ).fetchone()
        seq = int(row["max_seq"] if row else 0) + 1
        conn.execute(
            """
            INSERT INTO copilot_messages (id, session_id, seq, role, content_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, session_id, seq, role, _dump(payload), payload["created_at"]),
        )
        new_title = session["title"]
        if (
            role == "user"
            and (not session["title"] or session["title"] == DEFAULT_TITLE)
            and seq == 1
        ):
            new_title = default_title_from_text(str(payload.get("text") or ""))
        conn.execute(
            "UPDATE copilot_sessions SET title=?, updated_at=? WHERE id=?",
            (new_title, now, session_id),
        )
        stored = conn.execute(
            "SELECT * FROM copilot_messages WHERE id=?",
            (message_id,),
        ).fetchone()
    return _row_message(stored)


def patch_message_content(
    session_id: str,
    message_id: str,
    patch: dict,
    *,
    connect_factory: Callable = connect,
) -> dict:
    require_session(session_id, connect_factory=connect_factory)
    message_id = (message_id or "").strip()
    if not message_id:
        raise SessionNotFound(message_id)
    allowed = ("applied", "discarded", "checked", "text")
    with connect_factory() as conn:
        row = conn.execute(
            "SELECT * FROM copilot_messages WHERE id=? AND session_id=?",
            (message_id, session_id),
        ).fetchone()
        if row is None:
            raise SessionNotFound(message_id)
        content = _load_object(row["content_json"])
        incoming = patch if isinstance(patch, dict) else {}
        for key in allowed:
            if key in incoming:
                content[key] = incoming[key]
        conn.execute(
            "UPDATE copilot_messages SET content_json=? WHERE id=? AND session_id=?",
            (_dump(content), message_id, session_id),
        )
        stored = conn.execute(
            "SELECT * FROM copilot_messages WHERE id=?",
            (message_id,),
        ).fetchone()
    return _row_message(stored)


def touch_session(session_id: str, *, connect_factory: Callable = connect) -> dict:
    require_session(session_id, connect_factory=connect_factory)
    now = _now()
    with connect_factory() as conn:
        conn.execute("UPDATE copilot_sessions SET updated_at=? WHERE id=?", (now, session_id))
    session = get_session(session_id, connect_factory=connect_factory)
    if session is None:
        raise SessionNotFound(session_id)
    return session
