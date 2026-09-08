from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tag_manager import app as app_module
from tag_manager import update_routes
from tag_manager.update_service import (
    GithubUpdateError,
    GithubUpdateService,
    _is_protected,
    _safe_target,
    compare_versions,
    parse_remote_version,
)

REMOTE_README = """# night-wardrobe

一些说明文字
当前版本：**v1.25.1**
其他内容
"""


def build_update_zip(zip_path: Path, files: dict[str, str]) -> Path:
    """构造模拟 codeload 下载的 zip：顶层仓库目录 + tag_manager 子树。"""
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"night-wardrobe-master/tag_manager/{name}", content)
    return zip_path


def fake_download(zip_path: Path):
    def _download(url: str, dest: Path, timeout: int) -> Path:
        shutil.copyfile(zip_path, dest)
        return dest

    return _download


class VersionParseTests(unittest.TestCase):
    def test从README解析远程版本(self) -> None:
        self.assertEqual("1.25.1", parse_remote_version(REMOTE_README))

    def test解析容忍v前缀与空白(self) -> None:
        text = "当前版本：** v2.0.0 **\n"
        self.assertEqual("2.0.0", parse_remote_version(text))

    def test找不到版本号时报错(self) -> None:
        with self.assertRaises(GithubUpdateError) as ctx:
            parse_remote_version("# 没有版本号的 README")
        self.assertEqual("version_not_found", ctx.exception.code)


class VersionCompareTests(unittest.TestCase):
    def test落后返回负一(self) -> None:
        self.assertEqual(-1, compare_versions("1.24.14", "1.25.1"))

    def test相等返回零(self) -> None:
        self.assertEqual(0, compare_versions("1.24.14", "1.24.14"))

    def test领先返回正一(self) -> None:
        self.assertEqual(1, compare_versions("1.25.1", "1.24.14"))

    def test跨位比较(self) -> None:
        self.assertEqual(-1, compare_versions("1.9.0", "2.0.0"))
        self.assertEqual(1, compare_versions("1.24.10", "1.24.9"))

    def test格式非法视为相等(self) -> None:
        self.assertEqual(0, compare_versions("", "1.25.1"))
        self.assertEqual(0, compare_versions("abc", "1.25.1"))


class PathGuardTests(unittest.TestCase):
    def test黑名单路径全部受保护(self) -> None:
        for raw in (
            "tag_wardrobe.sqlite3",
            "gallery/a.jpg",
            "workflows/w.json",
            "manga/x",
            "manga_downloads/y",
            "manga_config.json",
            "tag_library.json",
            ".venv/lib/site.py",
            "__pycache__/app.cpython-311.pyc",
            "video_decrypt/outputs/1.mp4",
        ):
            self.assertTrue(_is_protected(Path(raw)), raw)

    def test代码文件不受保护(self) -> None:
        for raw in ("app.py", "update_service.py", "templates/base.html", "static/style.css"):
            self.assertFalse(_is_protected(Path(raw)), raw)

    def testzip路径穿越被拒绝(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertIsNone(_safe_target(root, Path("../evil.py")))
            self.assertIsNone(_safe_target(root, Path("a/../../evil.py")))
            self.assertIsNone(_safe_target(root, Path("")))
            inside = _safe_target(root, Path("templates/base.html"))
            self.assertIsNotNone(inside)
            self.assertEqual((root / "templates/base.html").resolve(), inside)


class CheckUpdateTests(unittest.TestCase):
    def test发现新版本(self) -> None:
        service = GithubUpdateService(
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
        )
        result = service.check()
        self.assertEqual("behind", result["status"])
        self.assertEqual("1.25.1", result["remote_version"])
        self.assertIn("1.24.14", result["current_version"])

    def test已是最新版本(self) -> None:
        service = GithubUpdateService(
            current_version="1.25.1",
            fetch_text=lambda url, timeout: REMOTE_README,
        )
        result = service.check()
        self.assertEqual("latest", result["status"])

    def test本地领先远程(self) -> None:
        service = GithubUpdateService(
            current_version="1.26.0",
            fetch_text=lambda url, timeout: REMOTE_README,
        )
        result = service.check()
        self.assertEqual("ahead", result["status"])

    def test网络失败返回未知状态与中文错误(self) -> None:
        def broken(url: str, timeout: int) -> str:
            raise GithubUpdateError("network_error", "访问远程仓库失败，请检查网络或代理设置：超时", 502)

        service = GithubUpdateService(current_version="1.24.14", fetch_text=broken)
        result = service.check()
        self.assertEqual("unknown", result["status"])
        self.assertEqual("", result["remote_version"])
        self.assertIn("网络", result["message"])


class ApplyUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.base_dir = self.root / "install"
        self.base_dir.mkdir()
        (self.base_dir / "app.py").write_text("旧版 app", encoding="utf-8")
        (self.base_dir / "keep_only_local.txt").write_text("本地独有", encoding="utf-8")
        (self.base_dir / "tag_library.json").write_text('{"tags": []}', encoding="utf-8")
        gallery = self.base_dir / "gallery"
        gallery.mkdir()
        (gallery / "photo.jpg").write_bytes(b"jpg-bytes")

        self.zip_path = build_update_zip(
            self.root / "update.zip",
            {
                "app.py": "新版 app",
                "update_service.py": "新模块",
                "tag_library.json": '{"tags": ["远程"]}',
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _service(self) -> GithubUpdateService:
        return GithubUpdateService(
            base_dir=self.base_dir,
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
            download_zip=fake_download(self.zip_path),
        )

    def test成功覆盖白名单且保留本地数据(self) -> None:
        result = self._service().apply()
        self.assertEqual("新版 app", (self.base_dir / "app.py").read_text(encoding="utf-8"))
        self.assertEqual("新模块", (self.base_dir / "update_service.py").read_text(encoding="utf-8"))
        # 本地多余文件不删除
        self.assertEqual("本地独有", (self.base_dir / "keep_only_local.txt").read_text(encoding="utf-8"))
        # 黑名单文件绝不触碰
        self.assertEqual('{"tags": []}', (self.base_dir / "tag_library.json").read_text(encoding="utf-8"))
        self.assertEqual(b"jpg-bytes", (self.base_dir / "gallery/photo.jpg").read_bytes())
        self.assertEqual(2, result["updated_count"])
        self.assertIn("app.py", result["updated_files"])
        self.assertIn("手动重启", result["message"])

    def test更新包含中文内容往返无损(self) -> None:
        chinese_zip = build_update_zip(
            self.root / "chinese.zip",
            {"copilot.py": "# 中文注释：提示词助手\nprint('你好')\n"},
        )
        service = GithubUpdateService(
            base_dir=self.base_dir,
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
            download_zip=fake_download(chinese_zip),
        )
        service.apply()
        self.assertEqual(
            "# 中文注释：提示词助手\nprint('你好')\n",
            (self.base_dir / "copilot.py").read_text(encoding="utf-8"),
        )

    def test写入失败自动回滚(self) -> None:
        service = self._service()
        original_write_bytes = Path.write_bytes

        def flaky_write(path: Path, data: bytes):
            if path.name == "update_service.py":
                raise OSError("模拟磁盘写入失败")
            return original_write_bytes(path, data)

        with patch.object(Path, "write_bytes", flaky_write):
            with self.assertRaises(GithubUpdateError) as ctx:
                service.apply()
        self.assertEqual("write_failed", ctx.exception.code)
        self.assertIn("回滚", ctx.exception.message)
        # 已覆盖的文件恢复原内容，新增文件被移除
        self.assertEqual("旧版 app", (self.base_dir / "app.py").read_text(encoding="utf-8"))
        self.assertFalse((self.base_dir / "update_service.py").exists())
        self.assertEqual("本地独有", (self.base_dir / "keep_only_local.txt").read_text(encoding="utf-8"))

    def test非OSError异常同样触发回滚(self) -> None:
        service = self._service()
        original_write_bytes = Path.write_bytes

        def unicode_failure(path: Path, data: bytes):
            if path.name == "update_service.py":
                # 模拟旧实现的 UnicodeEncodeError：非 OSError，绝不能绕过回滚
                raise UnicodeEncodeError("utf-8", "x", 0, 1, "模拟编码失败")
            return original_write_bytes(path, data)

        with patch.object(Path, "write_bytes", unicode_failure):
            with self.assertRaises(GithubUpdateError) as ctx:
                service.apply()
        self.assertEqual("write_failed", ctx.exception.code)
        self.assertIn("UnicodeEncodeError", ctx.exception.message)
        self.assertEqual("旧版 app", (self.base_dir / "app.py").read_text(encoding="utf-8"))
        self.assertFalse((self.base_dir / "update_service.py").exists())

    def test二进制文件覆盖字节一致(self) -> None:
        # 模拟 tests/fixtures/sample.evideo 这类非 UTF-8 字节固件：必须原样落盘
        binary_content = b"\x89EV\x00\xff\xfe\x80binary\x00\x01"
        binary_zip = self.root / "binary.zip"
        with zipfile.ZipFile(binary_zip, "w") as archive:
            archive.writestr("night-wardrobe-master/tag_manager/app.py", "新版 app")
            archive.writestr("night-wardrobe-master/tag_manager/tests/fixtures/sample.evideo", binary_content)

        service = GithubUpdateService(
            base_dir=self.base_dir,
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
            download_zip=fake_download(binary_zip),
        )
        service.apply()
        self.assertEqual(binary_content, (self.base_dir / "tests/fixtures/sample.evideo").read_bytes())
        self.assertEqual("新版 app", (self.base_dir / "app.py").read_text(encoding="utf-8"))

    def test损坏的zip报清晰错误(self) -> None:
        bad_zip = self.root / "bad.zip"
        bad_zip.write_bytes(b"not a zip")

        def download(url: str, dest: Path, timeout: int) -> Path:
            shutil.copyfile(bad_zip, dest)
            return dest

        service = GithubUpdateService(
            base_dir=self.base_dir,
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
            download_zip=download,
        )
        with self.assertRaises(GithubUpdateError) as ctx:
            service.apply()
        self.assertEqual("bad_zip", ctx.exception.code)
        self.assertEqual("旧版 app", (self.base_dir / "app.py").read_text(encoding="utf-8"))


class UpdateRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app_module.app)

    def test更新页面可访问且展示当前版本(self) -> None:
        response = self.client.get("/update")
        self.assertEqual(200, response.status_code)
        self.assertIn("检查更新", response.text)
        self.assertIn("v" + app_module.app.version, response.text)

    def test检查接口返回状态结构(self) -> None:
        service = GithubUpdateService(
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
        )
        with patch.object(update_routes, "_build_service", return_value=service):
            response = self.client.get("/api/update/check")
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("behind", data["status"])
        self.assertEqual("1.25.1", data["remote_version"])
        self.assertEqual("1.24.14", data["current_version"])

    def test更新接口成功返回文件摘要(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_dir = root / "install"
            base_dir.mkdir()
            (base_dir / "app.py").write_text("旧", encoding="utf-8")
            zip_path = build_update_zip(root / "u.zip", {"app.py": "新"})
            service = GithubUpdateService(
                base_dir=base_dir,
                current_version="1.24.14",
                fetch_text=lambda url, timeout: REMOTE_README,
                download_zip=fake_download(zip_path),
            )
            with patch.object(update_routes, "_build_service", return_value=service):
                response = self.client.post("/api/update/apply")
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual(1, data["updated_count"])
        self.assertIn("app.py", data["updated_files"])
        self.assertIn("手动重启", data["message"])

    def test更新接口失败返回错误结构与状态码(self) -> None:
        def broken_download(url: str, dest: Path, timeout: int) -> Path:
            raise GithubUpdateError("network_error", "下载更新包失败，请检查网络或代理设置：超时", 502)

        service = GithubUpdateService(
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
            download_zip=broken_download,
        )
        with patch.object(update_routes, "_build_service", return_value=service):
            response = self.client.post("/api/update/apply")
        self.assertEqual(502, response.status_code)
        data = response.json()
        self.assertEqual("network_error", data["error"]["code"])
        self.assertIn("网络", data["error"]["message"])

    def test侧边栏包含检查更新入口(self) -> None:
        response = self.client.get("/tags")
        self.assertEqual(200, response.status_code)
        self.assertIn('href="/update"', response.text)

    def test检查接口短缓存(self) -> None:
        service = GithubUpdateService(
            current_version="1.24.14",
            fetch_text=lambda url, timeout: REMOTE_README,
        )
        update_routes._update_cache = {"result": None, "timestamp": 0.0}
        with patch.object(update_routes, "_build_service", return_value=service) as mock_build:
            res1 = self.client.get("/api/update/check")
            self.assertEqual(200, res1.status_code)
            self.assertEqual(1, mock_build.call_count)
            
            res2 = self.client.get("/api/update/check")
            self.assertEqual(200, res2.status_code)
            self.assertEqual(1, mock_build.call_count)
            
            update_routes._update_cache["timestamp"] -= 61
            res3 = self.client.get("/api/update/check")
            self.assertEqual(200, res3.status_code)
            self.assertEqual(2, mock_build.call_count)

    def test前端启动时更新检查与弹框渲染(self) -> None:
        base_html = (Path(app_module.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("fetch('/api/update/check')", base_html)
        self.assertIn("sessionStorage.getItem('update_checked_once')", base_html)
        self.assertIn('id="sys-update-toast"', base_html)
        self.assertIn('class="update-toast-progress"', base_html)

if __name__ == "__main__":
    unittest.main()
