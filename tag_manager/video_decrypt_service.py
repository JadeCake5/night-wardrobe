from __future__ import annotations

import inspect
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable

from fastapi import UploadFile

from .db import BASE_DIR, connect
from .video_decrypt_adapter import VideoDecryptAdapter, VideoDecryptError

VIDEO_DECRYPT_DIR = BASE_DIR / "video_decrypt"
UPLOAD_CHUNK_SIZE = 1024 * 1024
PENDING_STATUSES = ("uploading", "queued", "running")
STATUS_LABELS = {
    "uploading": "上传中",
    "queued": "排队中",
    "running": "正在解密",
    "succeeded": "已完成",
    "failed": "失败",
    "interrupted": "已中断",
}

ConnectFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


class VideoDecryptServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def safe_source_name(filename: str) -> str:
    normalized = str(filename or "").replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].strip()
    if not name or Path(name).suffix.lower() != ".evideo":
        raise VideoDecryptServiceError("invalid_extension", "只能上传插件 2.0 生成的 .evideo 文件")
    return name


def safe_output_name(output_name: str, source_name: str) -> str:
    raw = (output_name or "").strip()
    if not raw:
        raw = f"{Path(source_name).stem}_restored.mp4"
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw) or "/" in raw or "\\" in raw:
        raise VideoDecryptServiceError("invalid_output_name", "输出名称不能包含路径")
    if Path(raw).suffix and Path(raw).suffix.lower() != ".mp4":
        raise VideoDecryptServiceError("invalid_output_name", "输出文件必须使用 .mp4 扩展名")
    if not Path(raw).suffix:
        raw += ".mp4"
    stem = re.sub(r'[\\/:*?"<>|]+', "_", Path(raw).stem)
    stem = re.sub(r"\s+", "_", stem).strip("._ ")
    if not stem:
        raise VideoDecryptServiceError("invalid_output_name", "输出名称不合法")
    return f"{stem}.mp4"


class VideoDecryptService:
    def __init__(
        self,
        *,
        storage_root: Path = VIDEO_DECRYPT_DIR,
        connect_factory: ConnectFactory = connect,
        adapter: Any | None = None,
    ) -> None:
        self.storage_root = Path(storage_root)
        self.inbox_dir = self.storage_root / "inbox"
        self.output_dir = self.storage_root / "outputs"
        self.connect_factory = connect_factory
        self.adapter = adapter or VideoDecryptAdapter()
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def ensure_storage(self) -> None:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="视频解密")
            return self._executor

    def _resolve_relative(self, relative_path: str) -> Path:
        if not relative_path:
            raise VideoDecryptServiceError("file_missing", "任务文件路径为空", 404)
        root = self.storage_root.resolve()
        target = (root / Path(relative_path)).resolve()
        if target == root or root not in target.parents:
            raise VideoDecryptServiceError("invalid_path", "任务文件路径超出受管目录", 400)
        return target

    def inspect_runtime(self):
        return self.adapter.inspect_runtime()

    def startup(self) -> int:
        self.ensure_storage()
        with self.connect_factory() as conn:
            rows = conn.execute(
                "SELECT id, input_path, output_path FROM video_decrypt_jobs WHERE status IN (?, ?, ?)",
                PENDING_STATUSES,
            ).fetchall()
            conn.execute(
                """
                UPDATE video_decrypt_jobs
                SET status='interrupted', error_code='interrupted',
                    error_message='应用重启导致任务中断，请重新提交',
                    progress=0, progress_message='',
                    completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE status IN (?, ?, ?)
                """,
                PENDING_STATUSES,
            )
        for row in rows:
            self._cleanup_job_files(row["input_path"], row["output_path"], include_output=True)
        return len(rows)

    def shutdown(self) -> None:
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    async def create_job(self, upload: UploadFile, password: str, output_name: str = "") -> dict[str, Any]:
        runtime = self.inspect_runtime()
        if not runtime.available:
            raise VideoDecryptServiceError("runtime_unavailable", runtime.message, 503)
        if not password:
            raise VideoDecryptServiceError("empty_password", "请输入加密密码")
        source_name = safe_source_name(upload.filename or "")
        final_output_name = safe_output_name(output_name, source_name)
        self.ensure_storage()

        with self.connect_factory() as conn:
            cursor = conn.execute(
                """
                INSERT INTO video_decrypt_jobs (source_name, output_name, status)
                VALUES (?, ?, 'uploading')
                """,
                (source_name, final_output_name),
            )
            job_id = int(cursor.lastrowid)
            input_relative = f"inbox/{job_id}.evideo"
            output_relative = f"outputs/{job_id}_{final_output_name}"
            conn.execute(
                "UPDATE video_decrypt_jobs SET input_path=?, output_path=? WHERE id=?",
                (input_relative, output_relative, job_id),
            )

        input_path = self._resolve_relative(input_relative)
        uploading_path = input_path.with_name(f"{input_path.name}.uploading")
        size = 0
        try:
            with uploading_path.open("wb") as target:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    target.write(chunk)
                    size += len(chunk)
            if size <= 0:
                raise VideoDecryptServiceError("empty_file", "上传的视频文件为空")
            os.replace(uploading_path, input_path)
            with self.connect_factory() as conn:
                conn.execute(
                    """
                    UPDATE video_decrypt_jobs
                    SET input_size=?, status='queued', updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='uploading'
                    """,
                    (size, job_id),
                )
        except VideoDecryptServiceError as exc:
            uploading_path.unlink(missing_ok=True)
            input_path.unlink(missing_ok=True)
            self._mark_failed(job_id, exc.code, exc.message)
            raise
        except OSError as exc:
            uploading_path.unlink(missing_ok=True)
            input_path.unlink(missing_ok=True)
            code = "disk_full" if getattr(exc, "errno", None) == 28 else "upload_failed"
            message = "磁盘空间不足，上传已清理" if code == "disk_full" else f"上传文件失败：{exc}"
            self._mark_failed(job_id, code, message)
            raise VideoDecryptServiceError(code, message, 507 if code == "disk_full" else 500) from exc
        finally:
            await upload.close()

        self._ensure_executor().submit(self._run_job, job_id, password)
        job = self.get_job(job_id)
        if job is None:
            raise VideoDecryptServiceError("job_missing", "任务创建后未找到", 500)
        return job

    def _claim_job(self, job_id: int):
        with self.connect_factory() as conn:
            cursor = conn.execute(
                """
                UPDATE video_decrypt_jobs
                SET status='running', progress=0, progress_message='',
                    started_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='queued'
                """,
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
            return conn.execute("SELECT * FROM video_decrypt_jobs WHERE id=?", (job_id,)).fetchone()

    def _run_job(self, job_id: int, password: str) -> None:
        row = self._claim_job(job_id)
        if row is None:
            return
        input_path = self._resolve_relative(row["input_path"])
        output_path = self._resolve_relative(row["output_path"])
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result = Path(
                self._decrypt_with_progress(input_path, output_path, password, job_id)
            ).resolve()
            if result != output_path.resolve() or not output_path.is_file():
                raise VideoDecryptError("output_missing", "解密器未生成预期输出文件")
            with self.connect_factory() as conn:
                conn.execute(
                    """
                    UPDATE video_decrypt_jobs
                    SET status='succeeded', error_code='', error_message='',
                        progress=1, completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='running'
                    """,
                    (job_id,),
                )
        except VideoDecryptError as exc:
            self._cleanup_output_artifacts(output_path, include_output=True)
            self._mark_failed(job_id, exc.code, exc.message)
        except Exception as exc:
            self._cleanup_output_artifacts(output_path, include_output=True)
            self._mark_failed(job_id, "unexpected_error", f"解密失败：{exc}")
        finally:
            input_path.unlink(missing_ok=True)
            password = ""

    def _decrypt_with_progress(
        self,
        input_path: Path,
        output_path: Path,
        password: str,
        job_id: int,
    ) -> Path:
        last_percent = -1

        def progress_callback(value: float, message: str) -> None:
            nonlocal last_percent
            try:
                progress = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return
            percent = int(progress * 100)
            if percent == last_percent:
                return
            last_percent = percent
            with self.connect_factory() as conn:
                conn.execute(
                    """
                    UPDATE video_decrypt_jobs
                    SET progress=?, progress_message=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='running'
                    """,
                    (progress, str(message or ""), job_id),
                )

        decrypt = self.adapter.decrypt
        kwargs: dict[str, Any] = {}
        try:
            parameters = inspect.signature(decrypt).parameters
        except (TypeError, ValueError):
            parameters = {}
        # 旧测试 FakeAdapter.decrypt 无 progress_callback 形参，按签名决定是否传入。
        if "progress_callback" in parameters or any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        ):
            kwargs["progress_callback"] = progress_callback
        return Path(decrypt(input_path, output_path, password, **kwargs))

    def _mark_failed(self, job_id: int, code: str, message: str) -> None:
        with self.connect_factory() as conn:
            conn.execute(
                """
                UPDATE video_decrypt_jobs
                SET status='failed', error_code=?, error_message=?,
                    progress=0, progress_message='',
                    completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status != 'succeeded'
                """,
                (code, message, job_id),
            )

    def _public_job(self, row: sqlite3.Row) -> dict[str, Any]:
        status = str(row["status"])
        return {
            "id": int(row["id"]),
            "source_name": row["source_name"],
            "output_name": row["output_name"],
            "input_size": int(row["input_size"] or 0),
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "progress": float(row["progress"] or 0),
            "progress_message": row["progress_message"] or "",
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
            "can_download": status == "succeeded",
            "can_delete": status != "running" and status != "uploading",
        }

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect_factory() as conn:
            row = conn.execute("SELECT * FROM video_decrypt_jobs WHERE id=?", (job_id,)).fetchone()
        return self._public_job(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.connect_factory() as conn:
            rows = conn.execute(
                "SELECT * FROM video_decrypt_jobs ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._public_job(row) for row in rows]

    def get_download(self, job_id: int) -> tuple[Path, str]:
        with self.connect_factory() as conn:
            row = conn.execute(
                "SELECT status, output_path, output_name FROM video_decrypt_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if not row:
            raise VideoDecryptServiceError("job_missing", "视频解密任务不存在", 404)
        if row["status"] != "succeeded":
            raise VideoDecryptServiceError("job_not_ready", "视频解密任务尚未完成", 409)
        output_path = self._resolve_relative(row["output_path"])
        if not output_path.is_file():
            raise VideoDecryptServiceError("file_missing", "解密输出文件不存在", 404)
        return output_path, row["output_name"]

    def delete_job(self, job_id: int) -> None:
        with self.connect_factory() as conn:
            row = conn.execute(
                "SELECT status, input_path, output_path FROM video_decrypt_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                raise VideoDecryptServiceError("job_missing", "视频解密任务不存在", 404)
            if row["status"] in ("running", "uploading"):
                raise VideoDecryptServiceError("job_busy", "任务正在处理，暂时不能删除", 409)
            conn.execute("DELETE FROM video_decrypt_jobs WHERE id=?", (job_id,))
        self._cleanup_job_files(row["input_path"], row["output_path"], include_output=True)

    def _cleanup_job_files(self, input_relative: str, output_relative: str, *, include_output: bool) -> None:
        for relative in (input_relative, output_relative):
            if not relative:
                continue
            try:
                path = self._resolve_relative(relative)
            except VideoDecryptServiceError:
                continue
            path.with_name(f"{path.name}.uploading").unlink(missing_ok=True)
            if relative == output_relative:
                self._cleanup_output_artifacts(path, include_output=include_output)
            if relative == input_relative or include_output:
                path.unlink(missing_ok=True)

    @staticmethod
    def _cleanup_output_artifacts(output_path: Path, *, include_output: bool) -> None:
        output_path.with_name(f"{output_path.name}.fragmented.partial").unlink(missing_ok=True)
        output_path.with_name(f"{output_path.name}.partial").unlink(missing_ok=True)
        if include_output:
            output_path.unlink(missing_ok=True)


video_decrypt_service = VideoDecryptService()
