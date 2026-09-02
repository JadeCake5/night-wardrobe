from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from tag_manager import app as app_module
from tag_manager import db
from tag_manager import video_decrypt_routes as routes
from tag_manager.video_decrypt_adapter import (
    VideoDecryptAdapter,
    VideoDecryptError,
    VideoDecryptRuntimeInfo,
    load_upstream_module,
    map_upstream_error,
    resolve_upstream_root,
)
from tag_manager.video_decrypt_service import (
    UPLOAD_CHUNK_SIZE,
    VideoDecryptService,
    VideoDecryptServiceError,
    safe_output_name,
    safe_source_name,
)

def _upstream_root() -> Path:
    raw = os.environ.get("WARDROBE_VIDEO_DECRYPTOR_ROOT", "").strip()
    if not raw:
        raise unittest.SkipTest("未设置 WARDROBE_VIDEO_DECRYPTOR_ROOT，跳过依赖上游仓库的测试")
    root = Path(raw)
    if not root.is_dir() or not (root / "video_crypto.py").is_file():
        raise unittest.SkipTest("WARDROBE_VIDEO_DECRYPTOR_ROOT 不是有效的上游仓库目录")
    return root


class FakeAdapter:
    def inspect_runtime(self) -> VideoDecryptRuntimeInfo:
        return VideoDecryptRuntimeInfo(
            True,
            upstream_version="测试版",
            av_version="测试版",
            cryptography_version="测试版",
            algorithm="测试协议",
            file_extension=".evideo",
        )

    def decrypt(self, input_path: Path, output_path: Path, password: str) -> Path:
        output_path.write_bytes(b"fake-mp4")
        return output_path


class RecordingUpload:
    def __init__(self, data: bytes, filename: str = "encrypted.evideo") -> None:
        self.filename = filename
        self._stream = io.BytesIO(data)
        self.read_sizes: list[int] = []
        self.closed = False

    async def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self._stream.read(size)

    async def close(self) -> None:
        self.closed = True


def wait_for_status(service: VideoDecryptService, job_id: int, expected: set[str], timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get_job(job_id)
        if job and job["status"] in expected:
            return job
        time.sleep(0.02)
    raise AssertionError(f"任务 {job_id} 未在限定时间进入状态：{sorted(expected)}")


class VideoDecryptAdapterTests(unittest.TestCase):
    def test运行时解析上游版本与密码学环境(self) -> None:
        adapter = VideoDecryptAdapter(_upstream_root())
        runtime = adapter.inspect_runtime()

        self.assertTrue(runtime.available, runtime.message)
        self.assertEqual("2.0.3", runtime.upstream_version)
        self.assertEqual("AES-256-GCM / Scrypt", runtime.algorithm)
        self.assertEqual(".evideo", runtime.file_extension)
        self.assertTrue(runtime.av_version)
        self.assertTrue(runtime.cryptography_version)

    def test配置文件可定位上游且业务代码不依赖绝对路径(self) -> None:
        upstream_root = _upstream_root()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps({"upstream_root": str(upstream_root)}), encoding="utf-8")
            resolved = resolve_upstream_root(config_path=config_path)
        self.assertEqual(upstream_root.resolve(), resolved)

    def test上游错误转换为稳定错误代码(self) -> None:
        cases = [
            ("密码错误或密文文件已经损坏", "authentication_failed"),
            ("输入文件不是本插件生成的 .evideo 密文", "unsupported_protocol"),
            ("输入文件的密文协议版本不受支持", "unsupported_version"),
            ("密文文件头损坏", "corrupted_file"),
            ("MP4 播放索引整理失败：测试错误", "remux_failed"),
        ]
        for message, code in cases:
            with self.subTest(code=code):
                self.assertEqual(code, map_upstream_error(RuntimeError(message)).code)

    def test文件名只允许EVIDEO输入与MP4输出(self) -> None:
        self.assertEqual("input.evideo", safe_source_name(r"C:\videos\input.evideo"))
        self.assertEqual("input_restored.mp4", safe_output_name("", "input.evideo"))
        with self.assertRaisesRegex(VideoDecryptServiceError, "只能上传"):
            safe_source_name("input.mp4")
        with self.assertRaisesRegex(VideoDecryptServiceError, "不能包含路径"):
            safe_output_name("../output.mp4", "input.evideo")


class VideoDecryptServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "test.sqlite3"
        db.init_db(self.db_path)
        self.service = VideoDecryptService(
            storage_root=self.root / "storage",
            connect_factory=lambda: db.connect(self.db_path),
            adapter=FakeAdapter(),
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self.temp_dir.cleanup()

    def create_job(self, data: bytes = b"encrypted", password: str = "秘密", output_name: str = "") -> dict:
        upload = UploadFile(file=io.BytesIO(data), filename="encrypted.evideo")
        return asyncio.run(self.service.create_job(upload, password, output_name))

    def test上传按固定块读取且密码不持久化(self) -> None:
        secret = "不得落盘的秘密"
        upload = RecordingUpload(b"x" * (UPLOAD_CHUNK_SIZE + 23))
        job = asyncio.run(self.service.create_job(upload, secret, "result.mp4"))
        completed = wait_for_status(self.service, job["id"], {"succeeded"})

        self.assertTrue(upload.closed)
        self.assertTrue(upload.read_sizes)
        self.assertEqual({UPLOAD_CHUNK_SIZE}, set(upload.read_sizes))
        self.assertNotIn(secret, json.dumps(completed, ensure_ascii=False))
        self.assertNotIn("input_path", completed)
        self.assertNotIn("output_path", completed)
        with db.connect(self.db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(video_decrypt_jobs)")}
            values = conn.execute("SELECT * FROM video_decrypt_jobs WHERE id=?", (job["id"],)).fetchone()
        self.assertNotIn("password", columns)
        self.assertNotIn(secret, "|".join(str(value) for value in values))

    def test单工作线程保证任务串行(self) -> None:
        class TrackingAdapter(FakeAdapter):
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def decrypt(self, input_path: Path, output_path: Path, password: str) -> Path:
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.12)
                output_path.write_bytes(b"done")
                with self.lock:
                    self.active -= 1
                return output_path

        adapter = TrackingAdapter()
        service = VideoDecryptService(
            storage_root=self.root / "serial-storage",
            connect_factory=lambda: db.connect(self.db_path),
            adapter=adapter,
        )
        try:
            first = asyncio.run(service.create_job(UploadFile(file=io.BytesIO(b"a"), filename="a.evideo"), "密码"))
            second = asyncio.run(service.create_job(UploadFile(file=io.BytesIO(b"b"), filename="b.evideo"), "密码"))
            wait_for_status(service, first["id"], {"succeeded"})
            wait_for_status(service, second["id"], {"succeeded"})
        finally:
            service.shutdown()
        self.assertEqual(1, adapter.max_active)

    def test启动恢复把遗留任务标为中断并清理文件(self) -> None:
        self.service.ensure_storage()
        input_path = self.service.inbox_dir / "7.evideo"
        output_path = self.service.output_dir / "7_output.mp4"
        input_path.write_bytes(b"input")
        output_path.with_name(f"{output_path.name}.partial").write_bytes(b"partial")
        output_path.with_name(f"{output_path.name}.fragmented.partial").write_bytes(b"fragmented")
        with db.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO video_decrypt_jobs
                    (source_name, input_path, output_name, output_path, status)
                VALUES (?, ?, ?, ?, 'running')
                """,
                ("input.evideo", "inbox/7.evideo", "output.mp4", "outputs/7_output.mp4"),
            )
            job_id = int(cursor.lastrowid)

        recovered = self.service.startup()
        job = self.service.get_job(job_id)

        self.assertEqual(1, recovered)
        self.assertEqual("interrupted", job["status"])
        self.assertFalse(input_path.exists())
        self.assertFalse(output_path.with_name(f"{output_path.name}.partial").exists())
        self.assertFalse(output_path.with_name(f"{output_path.name}.fragmented.partial").exists())

    def test失败任务清理输入输出和临时文件(self) -> None:
        class FailingAdapter(FakeAdapter):
            def decrypt(self, input_path: Path, output_path: Path, password: str) -> Path:
                output_path.with_name(f"{output_path.name}.partial").write_bytes(b"partial")
                output_path.with_name(f"{output_path.name}.fragmented.partial").write_bytes(b"fragmented")
                raise VideoDecryptError("authentication_failed", "密码错误或密文文件已损坏")

        service = VideoDecryptService(
            storage_root=self.root / "failed-storage",
            connect_factory=lambda: db.connect(self.db_path),
            adapter=FailingAdapter(),
        )
        try:
            job = asyncio.run(service.create_job(UploadFile(file=io.BytesIO(b"bad"), filename="bad.evideo"), "错误"))
            failed = wait_for_status(service, job["id"], {"failed"})
            with db.connect(self.db_path) as conn:
                row = conn.execute("SELECT input_path, output_path FROM video_decrypt_jobs WHERE id=?", (job["id"],)).fetchone()
            input_path = service._resolve_relative(row["input_path"])
            output_path = service._resolve_relative(row["output_path"])
        finally:
            service.shutdown()

        self.assertEqual("authentication_failed", failed["error_code"])
        self.assertFalse(input_path.exists())
        self.assertFalse(output_path.exists())
        self.assertFalse(output_path.with_name(f"{output_path.name}.partial").exists())
        self.assertFalse(output_path.with_name(f"{output_path.name}.fragmented.partial").exists())

    def test完成任务可以下载并删除全部受管数据(self) -> None:
        job = self.create_job(output_name="结果.mp4")
        wait_for_status(self.service, job["id"], {"succeeded"})
        path, filename = self.service.get_download(job["id"])
        self.assertEqual("结果.mp4", filename)
        self.assertTrue(path.is_file())

        self.service.delete_job(job["id"])

        self.assertFalse(path.exists())
        self.assertIsNone(self.service.get_job(job["id"]))

    def test同名输出不会覆盖且未完成任务禁止下载和删除(self) -> None:
        with db.connect(self.db_path) as conn:
            first_id = int(conn.execute(
                """
                INSERT INTO video_decrypt_jobs
                    (source_name, input_path, output_name, output_path, status)
                VALUES ('a.evideo', 'inbox/a.evideo', 'same.mp4', 'outputs/1_same.mp4', 'queued')
                """
            ).lastrowid)
            second_id = int(conn.execute(
                """
                INSERT INTO video_decrypt_jobs
                    (source_name, input_path, output_name, output_path, status)
                VALUES ('b.evideo', 'inbox/b.evideo', 'same.mp4', 'outputs/2_same.mp4', 'running')
                """
            ).lastrowid)
            paths = [row[0] for row in conn.execute(
                "SELECT output_path FROM video_decrypt_jobs WHERE id IN (?, ?) ORDER BY id",
                (first_id, second_id),
            )]

        self.assertEqual(2, len(set(paths)))
        with self.assertRaisesRegex(VideoDecryptServiceError, "尚未完成"):
            self.service.get_download(first_id)
        with self.assertRaisesRegex(VideoDecryptServiceError, "正在处理"):
            self.service.delete_job(second_id)


class VideoDecryptHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "test.sqlite3"
        db.init_db(self.db_path)
        self.service = VideoDecryptService(
            storage_root=self.root / "storage",
            connect_factory=lambda: db.connect(self.db_path),
            adapter=FakeAdapter(),
        )
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.service.shutdown()
        self.temp_dir.cleanup()

    def test页面创建状态下载删除完整流程(self) -> None:
        with patch.object(routes, "video_decrypt_service", self.service):
            page = self.client.get("/video-decrypt")
            created = self.client.post(
                "/video-decrypt/jobs",
                files={"file": ("encrypted.evideo", b"encrypted", "video/x-comfy-encrypted")},
                data={"password": "秘密", "output_name": "http-result.mp4"},
            )

            self.assertEqual(200, page.status_code)
            self.assertIn("上传并解密", page.text)
            self.assertEqual(202, created.status_code)
            payload = created.json()
            self.assertNotIn("password", json.dumps(payload))
            self.assertNotIn("input_path", payload)
            job = wait_for_status(self.service, payload["id"], {"succeeded"})

            status = self.client.get(f"/api/video-decrypt/jobs/{job['id']}")
            download = self.client.get(f"/video-decrypt/jobs/{job['id']}/download")
            deleted = self.client.post(
                f"/video-decrypt/jobs/{job['id']}/delete",
                follow_redirects=False,
            )

        self.assertEqual(200, status.status_code)
        self.assertEqual("succeeded", status.json()["status"])
        self.assertEqual(200, download.status_code)
        self.assertEqual(b"fake-mp4", download.content)
        self.assertEqual(303, deleted.status_code)

    def test非法扩展名和运行时不可用返回结构化错误(self) -> None:
        with patch.object(routes, "video_decrypt_service", self.service):
            invalid = self.client.post(
                "/video-decrypt/jobs",
                files={"file": ("plain.mp4", b"plain", "video/mp4")},
                data={"password": "秘密", "output_name": "result.mp4"},
            )
        self.assertEqual(400, invalid.status_code)
        self.assertEqual("invalid_extension", invalid.json()["error"]["code"])

        class UnavailableAdapter(FakeAdapter):
            def inspect_runtime(self) -> VideoDecryptRuntimeInfo:
                return VideoDecryptRuntimeInfo(False, message="测试环境缺少编码器")

        unavailable_service = VideoDecryptService(
            storage_root=self.root / "unavailable",
            connect_factory=lambda: db.connect(self.db_path),
            adapter=UnavailableAdapter(),
        )
        try:
            with patch.object(routes, "video_decrypt_service", unavailable_service):
                unavailable_page = self.client.get("/video-decrypt")
                unavailable_create = self.client.post(
                    "/video-decrypt/jobs",
                    files={"file": ("encrypted.evideo", b"data", "video/x-comfy-encrypted")},
                    data={"password": "秘密", "output_name": "result.mp4"},
                )
        finally:
            unavailable_service.shutdown()

        self.assertEqual(200, unavailable_page.status_code)
        self.assertIn("运行环境不可用", unavailable_page.text)
        self.assertIn("disabled", unavailable_page.text)
        self.assertEqual(503, unavailable_create.status_code)
        self.assertEqual("runtime_unavailable", unavailable_create.json()["error"]["code"])


class RealVideoDecryptIntegrationTests(unittest.TestCase):
    def test真实EVIDEO恢复MP4且认证失败无残留(self) -> None:
        import av

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            db.init_db(db_path)
            adapter = VideoDecryptAdapter(_upstream_root())
            upstream = load_upstream_module(_upstream_root())
            frames = np.random.default_rng(7).random((3, 12, 18, 3), dtype=np.float32)
            encrypted = root / "encrypted.evideo"
            sample_rate = 8000
            samples = np.arange(sample_rate, dtype=np.float32)
            audio = {
                "waveform": np.sin(2 * np.pi * 220 * samples / sample_rate)[np.newaxis, np.newaxis, :],
                "sample_rate": sample_rate,
            }
            upstream.encode_encrypted_video(frames, encrypted, 24.0, "正确密码", audio=audio)
            service = VideoDecryptService(
                storage_root=root / "storage",
                connect_factory=lambda: db.connect(db_path),
                adapter=adapter,
            )
            try:
                correct = asyncio.run(
                    service.create_job(
                        UploadFile(file=encrypted.open("rb"), filename="encrypted.evideo"),
                        "正确密码",
                        "restored.mp4",
                    )
                )
                correct_job = wait_for_status(service, correct["id"], {"succeeded"}, timeout=10)
                output_path, _ = service.get_download(correct_job["id"])
                with av.open(str(output_path)) as container:
                    video = container.streams.video[0]
                    decoded = list(container.decode(video=0))
                    self.assertIn("mp4", container.format.name)
                    self.assertEqual("h264", video.codec_context.name)
                    self.assertEqual("yuv420p", video.codec_context.format.name)
                    self.assertEqual(3, video.frames)
                    self.assertIsNotNone(container.duration)
                    self.assertEqual(3, len(decoded))
                restored_bytes = output_path.read_bytes()
                self.assertIn(b"moov", restored_bytes)
                self.assertNotIn(b"moof", restored_bytes)
                with av.open(str(output_path)) as container:
                    self.assertEqual("aac", container.streams.audio[0].codec_context.name)
                    self.assertGreater(sum(frame.samples for frame in container.decode(audio=0)), 0)

                wrong = asyncio.run(
                    service.create_job(
                        UploadFile(file=encrypted.open("rb"), filename="encrypted.evideo"),
                        "错误密码",
                        "wrong.mp4",
                    )
                )
                wrong_job = wait_for_status(service, wrong["id"], {"failed"}, timeout=10)
                self.assertEqual("authentication_failed", wrong_job["error_code"])
                with db.connect(db_path) as conn:
                    row = conn.execute("SELECT input_path, output_path FROM video_decrypt_jobs WHERE id=?", (wrong["id"],)).fetchone()
                self.assertFalse(service._resolve_relative(row["input_path"]).exists())
                wrong_output = service._resolve_relative(row["output_path"])
                self.assertFalse(wrong_output.exists())
                self.assertFalse(wrong_output.with_name(f"{wrong_output.name}.partial").exists())
                self.assertFalse(wrong_output.with_name(f"{wrong_output.name}.fragmented.partial").exists())

                tampered = root / "tampered.evideo"
                damaged = bytearray(encrypted.read_bytes())
                damaged[len(damaged) // 2] ^= 0x01
                tampered.write_bytes(damaged)
                with self.assertRaises(VideoDecryptError) as tampered_error:
                    adapter.decrypt(tampered, root / "tampered.mp4", "正确密码")
                self.assertEqual("authentication_failed", tampered_error.exception.code)
                self.assertFalse((root / "tampered.mp4").exists())
                self.assertFalse((root / "tampered.mp4.partial").exists())
                self.assertFalse((root / "tampered.mp4.fragmented.partial").exists())

                plain = root / "plain.evideo"
                plain.write_bytes(b"not-an-evideo-file" * 4)
                with self.assertRaises(VideoDecryptError) as protocol_error:
                    adapter.decrypt(plain, root / "plain.mp4", "正确密码")
                self.assertEqual("unsupported_protocol", protocol_error.exception.code)
            finally:
                service.shutdown()


class VideoDecryptStaticIntegrationTests(unittest.TestCase):
    def test导航模板样式和流式上传契约完整(self) -> None:
        base_dir = Path(app_module.BASE_DIR)
        base_html = (base_dir / "templates" / "base.html").read_text(encoding="utf-8")
        template = (base_dir / "templates" / "video_decrypt.html").read_text(encoding="utf-8")
        service_source = (base_dir / "video_decrypt_service.py").read_text(encoding="utf-8")
        style = (base_dir / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('href="/video-decrypt"', base_html)
        self.assertIn("v1.20.1", base_html)
        self.assertIn("style.css?v=79", base_html)
        self.assertIn("window.__wardrobePageCleanup", base_html)
        self.assertIn('name="password" type="password" autocomplete="off"', template)
        self.assertNotIn('id="videoPassword"', template)
        self.assertIn("XMLHttpRequest", template)
        self.assertIn("xhr.upload.addEventListener('progress'", template)
        self.assertIn("await upload.read(UPLOAD_CHUNK_SIZE)", service_source)
        self.assertNotIn("await upload.read()", service_source)
        self.assertIn(".video-decrypt-page", style)
        self.assertIn('.video-file-drop input[type="file"]', style)
        self.assertIn("clip-path: inset(50%)", style)
        self.assertIn(".video-file-drop:focus-within", style)
        self.assertIn(".evideo,video/x-comfy-encrypted,application/octet-stream", template)
        self.assertIn("AES-256-GCM", template)
        self.assertIn("PyAV", template)
        self.assertIn("Windows 播放器可识别总时长和拖动进度", template)


if __name__ == "__main__":
    unittest.main()
