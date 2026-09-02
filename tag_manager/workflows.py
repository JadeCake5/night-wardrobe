from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .db import BASE_DIR, connect, init_db
from .gallery import find_checkpoints_and_loras

WORKFLOW_DIR = BASE_DIR / "workflows"
WORKFLOW_EXTENSIONS = {".json"}


def ensure_workflow_dir() -> None:
    WORKFLOW_DIR.mkdir(exist_ok=True)


def safe_workflow_name(name: str) -> str:
    stem = Path(name or "workflow").stem.strip() or "workflow"
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem).strip("._ ") or "workflow"
    return f"{stem}.json"


def safe_workflow_relative_path(path: str | Path) -> Path:
    raw = str(path or "workflow.json").replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("工作流路径不合法")
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if not parts or any(part in (".", "..") for part in parts):
        raise ValueError("工作流路径不合法")
    folders = [re.sub(r'[\\/:*?"<>|]+', "_", part).strip("._ ") for part in parts[:-1]]
    folders = [part for part in folders if part]
    return Path(*folders, safe_workflow_name(parts[-1]))


def unique_workflow_path(filename: str | Path) -> Path:
    ensure_workflow_dir()
    target = WORKFLOW_DIR / safe_workflow_relative_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        return target
    stem = target.stem
    for index in range(2, 10000):
        candidate = target.with_name(f"{stem}_{index}.json")
        if not candidate.exists():
            return candidate
    raise RuntimeError("无法生成不重复的工作流文件名")


def iter_workflows(root: Path = WORKFLOW_DIR):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in WORKFLOW_EXTENSIONS:
            yield path


def load_workflow_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def count_nodes(data: Any) -> int:
    if isinstance(data, dict):
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            return len(nodes)
        return sum(1 for value in data.values() if isinstance(value, dict) and "class_type" in value)
    return 0


def read_workflow_summary(path: Path) -> dict[str, Any]:
    data = load_workflow_json(path)
    checkpoint, loras = find_checkpoints_and_loras(data)
    rel = path.relative_to(WORKFLOW_DIR).as_posix()
    return {
        "path": rel,
        "title": path.stem,
        "node_count": count_nodes(data),
        "checkpoint": checkpoint,
        "loras": ", ".join(dict.fromkeys(loras)),
    }


def upsert_workflow_record(path: Path, title: str = "", category: str = "", notes: str = "") -> None:
    summary = read_workflow_summary(path)
    rel = summary["path"]
    with connect() as conn:
        existing = conn.execute("SELECT title, category, notes FROM workflows WHERE path=?", (rel,)).fetchone()
        final_title = title or (existing["title"] if existing and existing["title"] else summary["title"])
        final_category = category if category else (existing["category"] if existing else "")
        final_notes = notes if notes else (existing["notes"] if existing else "")
        conn.execute(
            """
            INSERT INTO workflows (path, title, category, node_count, checkpoint, loras, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title,
                category=excluded.category,
                node_count=excluded.node_count,
                checkpoint=excluded.checkpoint,
                loras=excluded.loras,
                notes=excluded.notes,
                updated_at=CURRENT_TIMESTAMP
            """,
            (rel, final_title, final_category, summary["node_count"], summary["checkpoint"], summary["loras"], final_notes),
        )


def save_workflow_bytes(data: bytes, filename: str, title: str = "", category: str = "", notes: str = "") -> Path:
    target = unique_workflow_path(filename)
    json.loads(data.decode("utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    upsert_workflow_record(target, title=title, category=category, notes=notes)
    return target


def scan_workflows(root: Path = WORKFLOW_DIR) -> int:
    ensure_workflow_dir()
    init_db()
    count = 0
    with connect() as conn:
        known_paths = {r["path"] for r in conn.execute("SELECT path FROM workflows").fetchall()}
    seen_paths: set[str] = set()
    for path in iter_workflows(root):
        try:
            upsert_workflow_record(path)
        except Exception:
            continue
        seen_paths.add(path.relative_to(WORKFLOW_DIR).as_posix())
        count += 1
    missing = known_paths - seen_paths
    if missing:
        placeholders = ",".join("?" for _ in missing)
        with connect() as conn:
            conn.execute(f"DELETE FROM workflows WHERE path IN ({placeholders})", tuple(missing))
    return count


def export_workflows_zip() -> bytes:
    ensure_workflow_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in iter_workflows(WORKFLOW_DIR):
            arcname = path.relative_to(WORKFLOW_DIR).as_posix()
            zf.write(path, arcname)
    return buf.getvalue()


def import_workflows_zip(data: bytes, folder: str = "") -> int:
    ensure_workflow_dir()
    folder = safe_workflow_relative_path(f"{folder}/placeholder.json").parent.as_posix() if folder else ""
    count = 0
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for info in zf.infolist():
            if info.is_dir() or Path(info.filename).suffix.lower() not in WORKFLOW_EXTENSIONS:
                continue
            try:
                rel = safe_workflow_relative_path(info.filename)
            except ValueError:
                continue
            filename = Path(folder) / rel if folder else rel
            target = unique_workflow_path(filename)
            with zf.open(info) as src:
                payload = src.read()
            json.loads(payload.decode("utf-8"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            count += 1
    scan_workflows()
    return count


def sync_workflows_from_directory(source_root: Path) -> int:
    ensure_workflow_dir()
    source_root = Path(source_root)
    count = 0
    for source in iter_workflows(source_root):
        rel = safe_workflow_relative_path(source.relative_to(source_root))
        target = WORKFLOW_DIR / rel
        json.loads(source.read_text(encoding="utf-8"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    scan_workflows()
    return count
