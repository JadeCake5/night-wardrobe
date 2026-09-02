from __future__ import annotations

import os
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, ContextManager

from .db import connect

MANAGED_TABLES = {"gallery_images", "workflows"}


class FolderOperationError(ValueError):
    """可直接转换为页面提示的文件夹操作错误。"""

    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FolderInventory:
    folder_count: int = 0
    tracked_file_count: int = 0
    other_file_count: int = 0

    @property
    def is_empty(self) -> bool:
        return self.folder_count == 0 and self.tracked_file_count == 0 and self.other_file_count == 0

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "folder_count": self.folder_count,
            "tracked_file_count": self.tracked_file_count,
            "other_file_count": self.other_file_count,
            "is_empty": self.is_empty,
        }


@dataclass(frozen=True)
class FolderOperationResult:
    source: str
    target: str
    parent: str
    inventory: FolderInventory
    warning: str = ""


def normalize_relative_folder(folder: str) -> str:
    raw = str(folder or "").replace("\\", "/").strip()
    if not raw:
        return ""
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise FolderOperationError("文件夹路径不合法")
    parts = [part.strip() for part in raw.strip("/").split("/") if part.strip()]
    if any(part in (".", "..") for part in parts):
        raise FolderOperationError("文件夹路径不合法")
    return "/".join(parts)


def resolve_folder(root: Path, folder: str, *, allow_root: bool = False) -> Path:
    root = Path(root).resolve()
    relative = normalize_relative_folder(folder)
    if not relative and not allow_root:
        raise FolderOperationError("不能操作根目录")
    target = root.joinpath(*PurePosixPath(relative).parts) if relative else root
    resolved_target = target.resolve()
    if resolved_target != root and root not in resolved_target.parents:
        raise FolderOperationError("文件夹路径不合法")
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise FolderOperationError("不支持操作符号链接文件夹")
    return target


def _folder_chain(folder: str):
    current = normalize_relative_folder(folder)
    while current:
        yield current
        parent = PurePosixPath(current).parent
        current = "" if str(parent) == "." else parent.as_posix()
    yield ""


def build_folder_inventory_map(root: Path, tracked_extensions: set[str]) -> dict[str, FolderInventory]:
    root = Path(root).resolve()
    extensions = {suffix.lower() for suffix in tracked_extensions}
    mutable: dict[str, list[int]] = {"": [0, 0, 0]}
    if not root.exists():
        return {"": FolderInventory()}

    for current_raw, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_raw)
        current_rel = current.relative_to(root).as_posix()
        if current_rel == ".":
            current_rel = ""
        mutable.setdefault(current_rel, [0, 0, 0])

        retained_dirs: list[str] = []
        for name in dirnames:
            child = current / name
            if child.is_symlink():
                for ancestor in _folder_chain(current_rel):
                    mutable.setdefault(ancestor, [0, 0, 0])[2] += 1
                continue
            retained_dirs.append(name)
            child_rel = child.relative_to(root).as_posix()
            mutable.setdefault(child_rel, [0, 0, 0])
            for ancestor in _folder_chain(current_rel):
                mutable.setdefault(ancestor, [0, 0, 0])[0] += 1
        dirnames[:] = retained_dirs

        for name in filenames:
            path = current / name
            is_tracked = not path.is_symlink() and path.suffix.lower() in extensions
            index = 1 if is_tracked else 2
            for ancestor in _folder_chain(current_rel):
                mutable.setdefault(ancestor, [0, 0, 0])[index] += 1

    return {
        folder: FolderInventory(folder_count=counts[0], tracked_file_count=counts[1], other_file_count=counts[2])
        for folder, counts in mutable.items()
    }


def inspect_folder(root: Path, folder: str, tracked_extensions: set[str]) -> FolderInventory:
    relative = normalize_relative_folder(folder)
    target = resolve_folder(root, relative)
    if not target.exists() or not target.is_dir():
        raise FolderOperationError("文件夹不存在", "not_found")
    return build_folder_inventory_map(root, tracked_extensions).get(relative, FolderInventory())


def list_folder_options(
    root: Path,
    excluded_folder: str = "",
    *,
    inventory_map: dict[str, FolderInventory] | None = None,
) -> list[dict[str, str | int]]:
    root = Path(root).resolve()
    excluded = normalize_relative_folder(excluded_folder)
    folders = sorted(
        (inventory_map or build_folder_inventory_map(root, set())).keys(),
        key=lambda value: (value.count("/"), value.lower()),
    )
    result: list[dict[str, str | int]] = [{"path": "", "label": "根目录", "depth": 0}]
    for folder in folders:
        if not folder:
            continue
        if excluded and (folder == excluded or folder.startswith(excluded + "/")):
            continue
        depth = folder.count("/") + 1
        result.append({"path": folder, "label": "　" * depth + PurePosixPath(folder).name, "depth": depth})
    return result


def _validate_table(table: str) -> str:
    if table not in MANAGED_TABLES:
        raise FolderOperationError("不支持的文件夹类型")
    return table


def _assert_real_directory(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise FolderOperationError("文件夹不存在", "not_found")
    if path.is_symlink():
        raise FolderOperationError("不支持操作符号链接文件夹")


def _assert_no_links(path: Path) -> None:
    for current_raw, dirnames, filenames in os.walk(path, followlinks=False):
        current = Path(current_raw)
        for name in [*dirnames, *filenames]:
            if (current / name).is_symlink():
                raise FolderOperationError("文件夹中包含符号链接，无法执行此操作")


def _rows_under_folder(conn: Any, table: str, folder: str) -> list[Any]:
    prefix = normalize_relative_folder(folder) + "/"
    rows = conn.execute(f"SELECT id, path FROM {table} ORDER BY path").fetchall()
    return [row for row in rows if str(row["path"]).startswith(prefix)]


def _parent_folder(folder: str) -> str:
    parent = PurePosixPath(normalize_relative_folder(folder)).parent
    return "" if str(parent) == "." else parent.as_posix()


def move_managed_folder(
    root: Path,
    table: str,
    source: str,
    destination_parent: str,
    *,
    tracked_extensions: set[str],
    connect_factory: Callable[[], ContextManager[Any]] = connect,
) -> FolderOperationResult:
    table = _validate_table(table)
    source = normalize_relative_folder(source)
    destination_parent = normalize_relative_folder(destination_parent)
    source_path = resolve_folder(root, source)
    destination_path = resolve_folder(root, destination_parent, allow_root=True)
    _assert_real_directory(source_path)
    _assert_real_directory(destination_path)
    _assert_no_links(source_path)

    if destination_path == source_path or source_path in destination_path.parents:
        raise FolderOperationError("不能把文件夹移动到自身或其子文件夹", "conflict")

    target_folder = f"{destination_parent}/{PurePosixPath(source).name}" if destination_parent else PurePosixPath(source).name
    target_path = resolve_folder(root, target_folder)
    if target_path == source_path:
        raise FolderOperationError("文件夹已位于目标位置", "conflict")
    if target_path.exists():
        raise FolderOperationError("目标中已存在同名文件夹", "conflict")

    inventory = inspect_folder(root, source, tracked_extensions)
    moved = False
    try:
        with connect_factory() as conn:
            moving_rows = _rows_under_folder(conn, table, source)
            moving_ids = {int(row["id"]) for row in moving_rows}
            existing_paths = {
                str(row["path"])
                for row in conn.execute(f"SELECT id, path FROM {table}").fetchall()
                if int(row["id"]) not in moving_ids
            }
            updates = []
            source_prefix = source + "/"
            target_prefix = target_folder + "/"
            for row in moving_rows:
                new_path = target_prefix + str(row["path"])[len(source_prefix):]
                if new_path in existing_paths:
                    raise FolderOperationError("目标路径与现有数据库记录冲突", "conflict")
                updates.append((new_path, int(row["id"])))
            for new_path, row_id in updates:
                conn.execute(
                    f"UPDATE {table} SET path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (new_path, row_id),
                )
            source_path.rename(target_path)
            moved = True
    except FolderOperationError:
        raise
    except Exception as exc:
        if moved and target_path.exists() and not source_path.exists():
            try:
                target_path.rename(source_path)
            except Exception as restore_exc:
                raise FolderOperationError(f"移动失败且自动恢复失败：{restore_exc}", "io_error") from exc
        raise FolderOperationError(f"移动失败：{exc}", "io_error") from exc

    return FolderOperationResult(
        source=source,
        target=target_folder,
        parent=destination_parent,
        inventory=inventory,
    )


def delete_managed_folder(
    root: Path,
    table: str,
    folder: str,
    *,
    recursive: bool,
    tracked_extensions: set[str],
    connect_factory: Callable[[], ContextManager[Any]] = connect,
) -> FolderOperationResult:
    table = _validate_table(table)
    folder = normalize_relative_folder(folder)
    source_path = resolve_folder(root, folder)
    _assert_real_directory(source_path)
    _assert_no_links(source_path)
    inventory = inspect_folder(root, folder, tracked_extensions)
    if not inventory.is_empty and not recursive:
        raise FolderOperationError("文件夹非空，请确认同时删除其中所有内容", "not_empty")

    staging_root = Path(root).resolve().parent / ".folder-trash" / Path(root).name
    staging_root.mkdir(parents=True, exist_ok=True)
    staged_path = staging_root / f"{uuid.uuid4().hex}-{source_path.name}"
    staged = False
    try:
        source_path.rename(staged_path)
        staged = True
        with connect_factory() as conn:
            rows = _rows_under_folder(conn, table, folder)
            if rows:
                placeholders = ",".join("?" for _ in rows)
                conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(int(row["id"]) for row in rows))
    except FolderOperationError:
        raise
    except Exception as exc:
        if staged and staged_path.exists() and not source_path.exists():
            try:
                staged_path.rename(source_path)
            except Exception as restore_exc:
                raise FolderOperationError(f"删除失败且自动恢复失败：{restore_exc}", "io_error") from exc
        raise FolderOperationError(f"删除失败：{exc}", "io_error") from exc

    warning = ""
    try:
        shutil.rmtree(staged_path)
    except Exception as exc:
        warning = f"文件夹已从页面删除，但暂存清理失败：{exc}"
    for candidate in (staging_root, staging_root.parent):
        try:
            candidate.rmdir()
        except OSError:
            pass

    return FolderOperationResult(
        source=folder,
        target="",
        parent=_parent_folder(folder),
        inventory=inventory,
        warning=warning,
    )


def _image_rows_by_ids(conn: Any, ids: list[int]) -> list[Any]:
    clean_ids = sorted({int(value) for value in ids})
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    return conn.execute(
        f"SELECT id, path FROM gallery_images WHERE id IN ({placeholders}) ORDER BY path",
        tuple(clean_ids),
    ).fetchall()


def _restore_renamed_files(pairs: list[tuple[Path, Path]]) -> None:
    for source_path, staged_path in reversed(pairs):
        if staged_path.exists() and not source_path.exists():
            try:
                staged_path.rename(source_path)
            except OSError:
                pass


def move_gallery_images(
    root: Path,
    ids: list[int],
    destination_folder: str,
    *,
    connect_factory: Callable[[], ContextManager[Any]] = connect,
) -> dict[str, Any]:
    destination = normalize_relative_folder(destination_folder)
    destination_path = resolve_folder(root, destination, allow_root=True)
    _assert_real_directory(destination_path)

    moved: list[tuple[Path, Path]] = []
    try:
        with connect_factory() as conn:
            rows = _image_rows_by_ids(conn, ids)
            if not rows:
                raise FolderOperationError("没有可操作的图片", "not_found")
            updates = []
            for row in rows:
                relative = normalize_relative_folder(row["path"])
                name = PurePosixPath(relative).name
                target_rel = f"{destination}/{name}" if destination else name
                if target_rel == relative:
                    raise FolderOperationError(f"图片「{name}」已位于目标位置", "conflict")
                target_path = resolve_folder(root, target_rel)
                if target_path.exists():
                    raise FolderOperationError(f"目标文件夹已存在同名图片「{name}」", "conflict")
                updates.append((int(row["id"]), relative, target_rel, target_path))
            target_rels = [item[2] for item in updates]
            if len(set(target_rels)) != len(target_rels):
                raise FolderOperationError("选中图片存在同名文件，无法移入同一文件夹", "conflict")
            moving_ids = {item[0] for item in updates}
            placeholders = ",".join("?" for _ in target_rels)
            for conflict in conn.execute(
                f"SELECT id FROM gallery_images WHERE path IN ({placeholders})",
                tuple(target_rels),
            ).fetchall():
                if int(conflict["id"]) not in moving_ids:
                    raise FolderOperationError("目标路径与现有数据库记录冲突", "conflict")

            category = PurePosixPath(destination).name if destination else ""
            for row_id, relative, target_rel, target_path in updates:
                source_path = resolve_folder(root, relative)
                if not source_path.exists():
                    raise FolderOperationError(f"图片文件不存在：{relative}", "not_found")
                conn.execute(
                    "UPDATE gallery_images SET path=?, category=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (target_rel, category, row_id),
                )
                source_path.rename(target_path)
                moved.append((source_path, target_path))
    except FolderOperationError:
        _restore_renamed_files(moved)
        raise
    except Exception as exc:
        _restore_renamed_files(moved)
        raise FolderOperationError(f"移动失败：{exc}", "io_error") from exc

    return {"moved": len(moved), "destination": destination}


def delete_gallery_images(
    root: Path,
    ids: list[int],
    *,
    connect_factory: Callable[[], ContextManager[Any]] = connect,
) -> dict[str, Any]:
    staging_root = Path(root).resolve().parent / ".folder-trash" / Path(root).name
    staged: list[tuple[Path, Path]] = []
    deleted = 0
    try:
        with connect_factory() as conn:
            rows = _image_rows_by_ids(conn, ids)
            if not rows:
                raise FolderOperationError("没有可操作的图片", "not_found")
            staging_root.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            for row in rows:
                relative = normalize_relative_folder(row["path"])
                source_path = resolve_folder(root, relative)
                if not source_path.exists():
                    continue
                staged_path = staging_root / f"{token}-{len(staged)}-{source_path.name}"
                source_path.rename(staged_path)
                staged.append((source_path, staged_path))
            placeholders = ",".join("?" for _ in rows)
            conn.execute(
                f"DELETE FROM gallery_images WHERE id IN ({placeholders})",
                tuple(int(row["id"]) for row in rows),
            )
            deleted = len(rows)
    except FolderOperationError:
        _restore_renamed_files(staged)
        raise
    except Exception as exc:
        _restore_renamed_files(staged)
        raise FolderOperationError(f"删除失败：{exc}", "io_error") from exc

    warning = ""
    for _, staged_path in staged:
        try:
            staged_path.unlink()
        except OSError as exc:
            warning = f"图片已从页面删除，但暂存清理失败：{exc}"
    for candidate in (staging_root, staging_root.parent):
        try:
            candidate.rmdir()
        except OSError:
            pass

    return {"deleted": deleted, "warning": warning}
