from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable

from fastapi import UploadFile

from .db import BASE_DIR, connect
from .manga_composer import (
    DEFAULT_COVER_DURATION_MS,
    DEFAULT_DURATION_MS,
    DEFAULT_LOOP,
    RESIZE_STRATEGIES,
    MangaComposeError,
    compose_apng,
    compose_pdf,
    list_image_files,
)

MANGA_DIR = BASE_DIR / "manga"
CONFIG_PATH = BASE_DIR / "manga_config.json"
UPLOAD_CHUNK_SIZE = 1024 * 1024
PENDING_STATUSES = ("queued", "running")
STATUS_LABELS = {
    "queued": "排队中",
    "running": "进行中",
    "succeeded": "已完成",
    "failed": "失败",
    "interrupted": "已中断",
}
KIND_LABELS = {"download": "漫画下载", "compose": "APNG 合成"}
FORMAT_LABELS = {"pdf": "PDF", "apng": "APNG"}

DEFAULT_CONFIG = {
    "output_dir": str(BASE_DIR / "manga_downloads"),
    "proxy": "",
    "domains": [],
    "duration_ms": DEFAULT_DURATION_MS,
    "cover_duration_ms": DEFAULT_COVER_DURATION_MS,
    "loop": DEFAULT_LOOP,
    "resize": "pad",
}

ConnectFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


class MangaServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def parse_jmid(raw: str) -> str:
    digits = "".join(re.findall(r"\d+", str(raw or "")))
    if not digits:
        raise MangaServiceError("invalid_jmid", "请输入有效的 JM 车牌号（纯数字）")
    return digits


def sanitize_filename(raw: str, fallback: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(raw or ""))
    name = re.sub(r"\s+", " ", name).strip("._ ")
    if not name:
        name = fallback
    return name[:120]


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            config.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    except (OSError, ValueError):
        pass
    if not isinstance(config["domains"], list):
        config["domains"] = []
    config["domains"] = [str(d).strip() for d in config["domains"] if str(d).strip()]
    config["proxy"] = str(config["proxy"] or "").strip()
    config["output_dir"] = str(config["output_dir"] or DEFAULT_CONFIG["output_dir"]).strip()
    config["duration_ms"] = _clamp_int(config["duration_ms"], 10, 60000, DEFAULT_DURATION_MS)
    config["cover_duration_ms"] = _clamp_int(config["cover_duration_ms"], 10, 60000, DEFAULT_COVER_DURATION_MS)
    config["loop"] = max(0, _clamp_int(config["loop"], 0, 9999, DEFAULT_LOOP))
    if config["resize"] not in RESIZE_STRATEGIES:
        config["resize"] = "pad"
    return config


def save_config(config: dict[str, Any], config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in config.items() if k in DEFAULT_CONFIG})
    if isinstance(merged["domains"], str):
        merged["domains"] = [d.strip() for d in re.split(r"[,\s]+", merged["domains"]) if d.strip()]
    Path(config_path).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_config(config_path)


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def parse_apng_params(duration_ms, cover_duration_ms, loop, resize, config: dict[str, Any]) -> dict[str, Any]:
    resize_value = str(resize or "").strip() or config["resize"]
    if resize_value not in RESIZE_STRATEGIES:
        raise MangaServiceError("invalid_resize", "尺寸归一化策略必须是 pad/stretch/crop")
    return {
        "duration_ms": _clamp_int(duration_ms, 10, 60000, config["duration_ms"]),
        "cover_duration_ms": _clamp_int(cover_duration_ms, 10, 60000, config["cover_duration_ms"]),
        "loop": _clamp_int(loop, 0, 9999, config["loop"]),
        "resize": resize_value,
    }


def download_album_images(jmid: str, work_dir: Path, config: dict[str, Any]) -> tuple[str, int]:
    """调用 jmcomic 下载整本漫画到 work_dir，返回 (标题, 总页数)。图片按章节子目录落盘。"""
    try:
        import jmcomic
    except ImportError as exc:
        raise MangaServiceError("missing_dependency", "缺少 jmcomic 依赖，请先 pip install jmcomic", 500) from exc

    option_dict: dict[str, Any] = {
        "log": True,
        "dir_rule": {"base_dir": str(work_dir), "rule": "Bd_Pindex"},
        "download": {
            "cache": True,
            "image": {"decode": True, "suffix": ".jpg"},
            "threading": {"image": 10, "photo": 2},
        },
        "client": {"retry_times": 3},
        "plugins": {},
    }
    if config["domains"]:
        option_dict["client"]["domain"] = list(config["domains"])
    if config["proxy"]:
        option_dict["client"]["postman"] = {
            "meta_data": {"proxies": {"http": config["proxy"], "https": config["proxy"]}}
        }
    try:
        option = jmcomic.JmOption.construct(option_dict)
        album, _downloader = jmcomic.download_album(jmid, option)
    except Exception as exc:
        raise MangaServiceError("download_failed", f"漫画下载失败：{exc}", 502) from exc

    image_paths: list[Path] = []
    for photo in album:
        image_paths.extend(list_image_files(Path(option.decide_image_save_dir(photo))))
    if not image_paths:
        raise MangaServiceError("download_empty", "下载完成但没有找到任何页面图片", 502)
    return album.title or f"JM{jmid}", len(image_paths)


def collect_downloaded_images(work_dir: Path) -> list[Path]:
    image_paths: list[Path] = []
    for sub_dir in sorted((p for p in work_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
        image_paths.extend(list_image_files(sub_dir))
    if not image_paths:
        image_paths = list_image_files(work_dir)
    return image_paths


class MangaService:
    def __init__(
        self,
        *,
        storage_root: Path = MANGA_DIR,
        config_path: Path = CONFIG_PATH,
        connect_factory: ConnectFactory = connect,
        downloader: Callable[[str, Path, dict], tuple[str, int]] = download_album_images,
    ) -> None:
        self.storage_root = Path(storage_root)
        self.inbox_dir = self.storage_root / "inbox"
        self.config_path = Path(config_path)
        self.connect_factory = connect_factory
        self.downloader = downloader
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def get_config(self) -> dict[str, Any]:
        return load_config(self.config_path)

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        return save_config(updates, self.config_path)

    def ensure_storage(self) -> None:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        output_root = Path(self.get_config()["output_dir"])
        (output_root / "pdf").mkdir(parents=True, exist_ok=True)
        (output_root / "apng").mkdir(parents=True, exist_ok=True)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="漫画任务")
            return self._executor

    def _resolve_output(self, stored_path: str) -> Path:
        if not stored_path:
            raise MangaServiceError("file_missing", "任务产物路径为空", 404)
        output_root = Path(self.get_config()["output_dir"]).resolve()
        target = Path(stored_path).resolve()
        if target != output_root and output_root not in target.parents:
            raise MangaServiceError("invalid_path", "任务产物路径超出输出目录", 400)
        return target

    def startup(self) -> int:
        self.ensure_storage()
        with self.connect_factory() as conn:
            rows = conn.execute(
                "SELECT id, work_dir FROM manga_jobs WHERE status IN (?, ?)",
                PENDING_STATUSES,
            ).fetchall()
            conn.execute(
                """
                UPDATE manga_jobs
                SET status='interrupted', error_code='interrupted',
                    error_message='应用重启导致任务中断，请重新提交',
                    completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE status IN (?, ?)
                """,
                PENDING_STATUSES,
            )
        for row in rows:
            shutil.rmtree(self.storage_root / row["work_dir"], ignore_errors=True)
        return len(rows)

    def shutdown(self) -> None:
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    async def create_download_job(
        self,
        jmid_raw: str,
        fmt: str,
        duration_ms=None,
        cover_duration_ms=None,
        loop=None,
        resize: str = "",
        cover: UploadFile | None = None,
    ) -> dict[str, Any]:
        jmid = parse_jmid(jmid_raw)
        if fmt not in FORMAT_LABELS:
            raise MangaServiceError("invalid_format", "输出格式必须是 pdf 或 apng")
        config = self.get_config()
        params = parse_apng_params(duration_ms, cover_duration_ms, loop, resize, config)
        if fmt == "apng" and (cover is None or not cover.filename):
            raise MangaServiceError("cover_required", "APNG 格式需要上传一张首图作为动画首帧")
        self.ensure_storage()

        with self.connect_factory() as conn:
            cursor = conn.execute(
                """
                INSERT INTO manga_jobs (kind, jmid, format, params_json, status)
                VALUES ('download', ?, ?, ?, 'queued')
                """,
                (jmid, fmt, json.dumps(params, ensure_ascii=False)),
            )
            job_id = int(cursor.lastrowid)
            conn.execute("UPDATE manga_jobs SET work_dir=? WHERE id=?", (f"inbox/job_{job_id}", job_id))

        work_dir = self.inbox_dir / f"job_{job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            if fmt == "apng":
                cover_path = work_dir / "cover.png"
                await self._save_upload(cover, cover_path)
        finally:
            if cover is not None:
                await cover.close()

        self._ensure_executor().submit(self._run_download_job, job_id)
        return self._require_job(job_id)

    async def create_compose_job(
        self,
        cover: UploadFile,
        frames: list[UploadFile],
        duration_ms=None,
        cover_duration_ms=None,
        loop=None,
        resize: str = "",
    ) -> dict[str, Any]:
        if cover is None or not cover.filename:
            raise MangaServiceError("cover_required", "请上传首帧图片")
        frames = [f for f in (frames or []) if f and f.filename]
        if not frames:
            raise MangaServiceError("empty_frames", "请至少上传一张帧序列图片")
        config = self.get_config()
        params = parse_apng_params(duration_ms, cover_duration_ms, loop, resize, config)
        self.ensure_storage()

        with self.connect_factory() as conn:
            cursor = conn.execute(
                """
                INSERT INTO manga_jobs (kind, jmid, format, params_json, status)
                VALUES ('compose', '', 'apng', ?, 'queued')
                """,
                (json.dumps(params, ensure_ascii=False),),
            )
            job_id = int(cursor.lastrowid)
            conn.execute("UPDATE manga_jobs SET work_dir=? WHERE id=?", (f"inbox/job_{job_id}", job_id))

        work_dir = self.inbox_dir / f"job_{job_id}"
        frames_dir = work_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self._save_upload(cover, work_dir / "cover.png")
            for index, frame in enumerate(frames):
                await self._save_upload(frame, frames_dir / f"{index:04d}.png")
        except MangaServiceError as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            self._mark_failed(job_id, exc.code, exc.message)
            raise
        finally:
            await cover.close()
            for frame in frames:
                await frame.close()

        self._ensure_executor().submit(self._run_compose_job, job_id)
        return self._require_job(job_id)

    async def _save_upload(self, upload: UploadFile, target: Path) -> None:
        size = 0
        uploading = target.with_name(f"{target.name}.uploading")
        try:
            with uploading.open("wb") as f:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
            if size <= 0:
                raise MangaServiceError("empty_file", f"上传文件为空：{upload.filename}")
            uploading.replace(target)
        except OSError as exc:
            uploading.unlink(missing_ok=True)
            raise MangaServiceError("upload_failed", f"保存上传文件失败：{exc}", 500) from exc

    def _require_job(self, job_id: int) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise MangaServiceError("job_missing", "任务创建后未找到", 500)
        return job

    def _claim_job(self, job_id: int):
        with self.connect_factory() as conn:
            cursor = conn.execute(
                """
                UPDATE manga_jobs
                SET status='running', started_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='queued'
                """,
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
            return conn.execute("SELECT * FROM manga_jobs WHERE id=?", (job_id,)).fetchone()

    def _update_progress(self, job_id: int, label: str) -> None:
        with self.connect_factory() as conn:
            conn.execute(
                "UPDATE manga_jobs SET progress_label=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",
                (label, job_id),
            )

    def _run_download_job(self, job_id: int) -> None:
        row = self._claim_job(job_id)
        if row is None:
            return
        work_dir = self.storage_root / row["work_dir"]
        config = self.get_config()
        params = json.loads(row["params_json"] or "{}")
        fmt = row["format"]
        jmid = row["jmid"]
        try:
            self._update_progress(job_id, "正在下载漫画")
            stop_flag = threading.Event()
            monitor = threading.Thread(
                target=self._monitor_download, args=(job_id, work_dir, stop_flag), daemon=True
            )
            monitor.start()
            try:
                title, page_count = self.downloader(jmid, work_dir, config)
            finally:
                stop_flag.set()
                monitor.join(timeout=2)
            image_paths = collect_downloaded_images(work_dir)
            if not image_paths:
                raise MangaServiceError("download_empty", "下载完成但没有找到任何页面图片", 502)
            self._update_progress(job_id, f"正在合成 {FORMAT_LABELS[fmt]}（{len(image_paths)} 页）")
            output_path = self._compose(job_id, fmt, title or f"JM{jmid}", image_paths, work_dir, params, config)
            self._mark_succeeded(job_id, title, output_path)
        except MangaServiceError as exc:
            self._mark_failed(job_id, exc.code, exc.message)
        except MangaComposeError as exc:
            self._mark_failed(job_id, exc.code, exc.message)
        except Exception as exc:
            self._mark_failed(job_id, "unexpected_error", f"任务失败：{exc}")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _run_compose_job(self, job_id: int) -> None:
        row = self._claim_job(job_id)
        if row is None:
            return
        work_dir = self.storage_root / row["work_dir"]
        config = self.get_config()
        params = json.loads(row["params_json"] or "{}")
        try:
            cover_path = work_dir / "cover.png"
            frame_paths = list_image_files(work_dir / "frames")
            if not frame_paths:
                raise MangaServiceError("empty_frames", "没有找到帧序列图片")
            self._update_progress(job_id, f"正在合成 APNG（{len(frame_paths) + 1} 帧）")
            output_path = self._compose(job_id, "apng", f"合成_{job_id}", frame_paths, work_dir, params, config, cover=cover_path)
            self._mark_succeeded(job_id, "手动合成", output_path)
        except (MangaServiceError, MangaComposeError) as exc:
            self._mark_failed(job_id, exc.code, exc.message)
        except Exception as exc:
            self._mark_failed(job_id, "unexpected_error", f"任务失败：{exc}")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _monitor_download(self, job_id: int, work_dir: Path, stop_flag: threading.Event) -> None:
        while not stop_flag.wait(1.0):
            try:
                count = len(collect_downloaded_images(work_dir)) if work_dir.is_dir() else 0
            except OSError:
                continue
            if count:
                self._update_progress(job_id, f"正在下载漫画（已落盘 {count} 页）")

    def _compose(
        self,
        job_id: int,
        fmt: str,
        title: str,
        image_paths: list[Path],
        work_dir: Path,
        params: dict[str, Any],
        config: dict[str, Any],
        cover: Path | None = None,
    ) -> Path:
        output_root = Path(config["output_dir"])
        safe_title = sanitize_filename(title, f"job_{job_id}")
        if fmt == "pdf":
            output_path = output_root / "pdf" / f"{safe_title}.pdf"
            return compose_pdf(image_paths, output_path)
        cover_path = cover or (work_dir / "cover.png")
        output_path = output_root / "apng" / f"{safe_title}.png"
        return compose_apng(
            cover_path,
            image_paths,
            output_path,
            duration_ms=params.get("duration_ms", DEFAULT_DURATION_MS),
            cover_duration_ms=params.get("cover_duration_ms", DEFAULT_COVER_DURATION_MS),
            loop=params.get("loop", DEFAULT_LOOP),
            resize=params.get("resize", "pad"),
        )

    def _mark_succeeded(self, job_id: int, title: str, output_path: Path) -> None:
        with self.connect_factory() as conn:
            conn.execute(
                """
                UPDATE manga_jobs
                SET status='succeeded', title=?, output_path=?, output_size=?, progress_label='',
                    error_code='', error_message='',
                    completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='running'
                """,
                (title, str(output_path), output_path.stat().st_size, job_id),
            )

    def _mark_failed(self, job_id: int, code: str, message: str) -> None:
        with self.connect_factory() as conn:
            conn.execute(
                """
                UPDATE manga_jobs
                SET status='failed', error_code=?, error_message=?, progress_label='',
                    completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status != 'succeeded'
                """,
                (code, message, job_id),
            )

    def _public_job(self, row: sqlite3.Row) -> dict[str, Any]:
        status = str(row["status"])
        fmt = str(row["format"])
        return {
            "id": int(row["id"]),
            "kind": row["kind"],
            "kind_label": KIND_LABELS.get(row["kind"], row["kind"]),
            "jmid": row["jmid"],
            "title": row["title"] or (f"JM{row['jmid']}" if row["jmid"] else f"任务 {row['id']}"),
            "format": fmt,
            "format_label": FORMAT_LABELS.get(fmt, fmt),
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "progress_label": row["progress_label"],
            "output_size": int(row["output_size"] or 0),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "can_download": status == "succeeded",
            "can_delete": status != "running",
        }

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect_factory() as conn:
            row = conn.execute("SELECT * FROM manga_jobs WHERE id=?", (job_id,)).fetchone()
        return self._public_job(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.connect_factory() as conn:
            rows = conn.execute(
                "SELECT * FROM manga_jobs ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [self._public_job(row) for row in rows]

    def get_download(self, job_id: int) -> tuple[Path, str]:
        with self.connect_factory() as conn:
            row = conn.execute(
                "SELECT status, output_path, format, title FROM manga_jobs WHERE id=?", (job_id,)
            ).fetchone()
        if not row:
            raise MangaServiceError("job_missing", "漫画任务不存在", 404)
        if row["status"] != "succeeded":
            raise MangaServiceError("job_not_ready", "漫画任务尚未完成", 409)
        output_path = self._resolve_output(row["output_path"])
        if not output_path.is_file():
            raise MangaServiceError("file_missing", "产物文件不存在", 404)
        return output_path, output_path.name

    def delete_job(self, job_id: int) -> None:
        with self.connect_factory() as conn:
            row = conn.execute(
                "SELECT status, work_dir, output_path FROM manga_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise MangaServiceError("job_missing", "漫画任务不存在", 404)
            if row["status"] == "running":
                raise MangaServiceError("job_busy", "任务正在处理，暂时不能删除", 409)
            conn.execute("DELETE FROM manga_jobs WHERE id=?", (job_id,))
        shutil.rmtree(self.storage_root / row["work_dir"], ignore_errors=True)
        if row["output_path"]:
            try:
                self._resolve_output(row["output_path"]).unlink(missing_ok=True)
            except MangaServiceError:
                pass


manga_service = MangaService()
