from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tag_manager import app as app_module
from tag_manager import db
from tag_manager.folder_ops import (
    FolderInventory,
    FolderOperationError,
    FolderOperationResult,
    build_folder_inventory_map,
    delete_gallery_images,
    delete_managed_folder,
    list_folder_options,
    move_gallery_images,
    move_managed_folder,
    resolve_folder,
)


class FolderManagementTests(unittest.TestCase):
    """所有破坏性分支只在临时文件系统和临时数据库中执行。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.gallery_root = self.base / "gallery"
        self.workflow_root = self.base / "workflows"
        self.gallery_root.mkdir()
        self.workflow_root.mkdir()
        self.db_path = self.base / "test.sqlite3"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def connect(self):
        return db.connect(self.db_path)

    def insert_workflow(self, path: str, *, title: str = "人工标题", category: str = "人工分类", notes: str = "人工备注") -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO workflows (path, title, category, notes) VALUES (?, ?, ?, ?)",
                (path, title, category, notes),
            )
            return int(cursor.lastrowid)

    def insert_gallery(self, path: str, *, title: str = "人工标题", category: str = "人工分类", notes: str = "人工备注", rating: int = 4) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO gallery_images (path, title, category, notes, rating) VALUES (?, ?, ?, ?, ?)",
                (path, title, category, notes, rating),
            )
            return int(cursor.lastrowid)

    def test目录统计一次覆盖嵌套文件和其他文件(self) -> None:
        (self.gallery_root / "角色" / "子目录").mkdir(parents=True)
        (self.gallery_root / "角色" / "a.png").write_bytes(b"png")
        (self.gallery_root / "角色" / "子目录" / "b.webp").write_bytes(b"webp")
        (self.gallery_root / "角色" / "说明.txt").write_text("说明", encoding="utf-8")

        stats = build_folder_inventory_map(self.gallery_root, {".png", ".webp"})

        self.assertEqual(1, stats["角色"].folder_count)
        self.assertEqual(2, stats["角色"].tracked_file_count)
        self.assertEqual(1, stats["角色"].other_file_count)

    def test移动嵌套工作流保留数据库记录和人工字段(self) -> None:
        source = self.workflow_root / "来源%_" / "子目录"
        source.mkdir(parents=True)
        (self.workflow_root / "目标").mkdir()
        (source / "流程.json").write_text("{}", encoding="utf-8")
        row_id = self.insert_workflow("来源%_/子目录/流程.json")

        result = move_managed_folder(
            self.workflow_root,
            "workflows",
            "来源%_",
            "目标",
            tracked_extensions={".json"},
            connect_factory=self.connect,
        )

        self.assertEqual("目标/来源%_", result.target)
        self.assertTrue((self.workflow_root / "目标" / "来源%_" / "子目录" / "流程.json").exists())
        self.assertFalse((self.workflow_root / "来源%_").exists())
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id=?", (row_id,)).fetchone()
        self.assertEqual("目标/来源%_/子目录/流程.json", row["path"])
        self.assertEqual("人工标题", row["title"])
        self.assertEqual("人工分类", row["category"])
        self.assertEqual("人工备注", row["notes"])

    def test移动图库保留评分并支持移回根目录(self) -> None:
        source = self.gallery_root / "父级" / "图片组"
        source.mkdir(parents=True)
        (source / "a.png").write_bytes(b"png")
        row_id = self.insert_gallery("父级/图片组/a.png")

        result = move_managed_folder(
            self.gallery_root,
            "gallery_images",
            "父级/图片组",
            "",
            tracked_extensions={".png"},
            connect_factory=self.connect,
        )

        self.assertEqual("图片组", result.target)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM gallery_images WHERE id=?", (row_id,)).fetchone()
        self.assertEqual("图片组/a.png", row["path"])
        self.assertEqual(4, row["rating"])
        self.assertEqual("人工备注", row["notes"])

    def test移动拒绝同名目标自身和后代(self) -> None:
        (self.workflow_root / "A" / "B").mkdir(parents=True)
        (self.workflow_root / "目标" / "A").mkdir(parents=True)
        cases = [("A", "目标"), ("A", "A"), ("A", "A/B")]
        for source, destination in cases:
            with self.subTest(source=source, destination=destination):
                with self.assertRaises(FolderOperationError):
                    move_managed_folder(
                        self.workflow_root,
                        "workflows",
                        source,
                        destination,
                        tracked_extensions={".json"},
                        connect_factory=self.connect,
                    )
        self.assertTrue((self.workflow_root / "A").exists())

    def test路径解析拒绝符号链接目录(self) -> None:
        (self.gallery_root / "链接目录").mkdir()
        original = Path.is_symlink

        def simulated_link(path: Path) -> bool:
            return path.name == "链接目录" or original(path)

        with patch.object(Path, "is_symlink", simulated_link):
            with self.assertRaises(FolderOperationError):
                resolve_folder(self.gallery_root, "链接目录")

    def test目标选项排除源目录及后代(self) -> None:
        (self.gallery_root / "A" / "B").mkdir(parents=True)
        (self.gallery_root / "C").mkdir()

        paths = [item["path"] for item in list_folder_options(self.gallery_root, "A")]

        self.assertEqual(["", "C"], paths)

    def test非空目录必须确认后才删除(self) -> None:
        source = self.workflow_root / "待删除" / "子目录"
        source.mkdir(parents=True)
        (source / "流程.json").write_text("{}", encoding="utf-8")
        row_id = self.insert_workflow("待删除/子目录/流程.json")

        with self.assertRaises(FolderOperationError) as error:
            delete_managed_folder(
                self.workflow_root,
                "workflows",
                "待删除",
                recursive=False,
                tracked_extensions={".json"},
                connect_factory=self.connect,
            )
        self.assertEqual("not_empty", error.exception.code)
        self.assertTrue((self.workflow_root / "待删除").exists())

        result = delete_managed_folder(
            self.workflow_root,
            "workflows",
            "待删除",
            recursive=True,
            tracked_extensions={".json"},
            connect_factory=self.connect,
        )
        self.assertEqual(1, result.inventory.tracked_file_count)
        self.assertFalse((self.workflow_root / "待删除").exists())
        with self.connect() as conn:
            self.assertIsNone(conn.execute("SELECT id FROM workflows WHERE id=?", (row_id,)).fetchone())

    def test空目录可以直接删除(self) -> None:
        (self.gallery_root / "空目录").mkdir()

        result = delete_managed_folder(
            self.gallery_root,
            "gallery_images",
            "空目录",
            recursive=False,
            tracked_extensions={".png"},
            connect_factory=self.connect,
        )

        self.assertTrue(result.inventory.is_empty)
        self.assertFalse((self.gallery_root / "空目录").exists())

    def test移动提交失败会恢复文件系统和数据库(self) -> None:
        source = self.workflow_root / "来源"
        source.mkdir()
        (self.workflow_root / "目标").mkdir()
        (source / "流程.json").write_text("{}", encoding="utf-8")
        row_id = self.insert_workflow("来源/流程.json")

        @contextmanager
        def failing_connect():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.rollback()
                raise RuntimeError("模拟提交失败")
            finally:
                conn.close()

        with self.assertRaises(FolderOperationError):
            move_managed_folder(
                self.workflow_root,
                "workflows",
                "来源",
                "目标",
                tracked_extensions={".json"},
                connect_factory=failing_connect,
            )

        self.assertTrue((self.workflow_root / "来源" / "流程.json").exists())
        self.assertFalse((self.workflow_root / "目标" / "来源").exists())
        with self.connect() as conn:
            row = conn.execute("SELECT path FROM workflows WHERE id=?", (row_id,)).fetchone()
        self.assertEqual("来源/流程.json", row["path"])

    def test删除提交失败会恢复暂存目录(self) -> None:
        source = self.gallery_root / "待删除"
        source.mkdir()
        (source / "a.png").write_bytes(b"png")
        row_id = self.insert_gallery("待删除/a.png")

        @contextmanager
        def failing_connect():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.rollback()
                raise RuntimeError("模拟提交失败")
            finally:
                conn.close()

        with self.assertRaises(FolderOperationError):
            delete_managed_folder(
                self.gallery_root,
                "gallery_images",
                "待删除",
                recursive=True,
                tracked_extensions={".png"},
                connect_factory=failing_connect,
            )

        self.assertTrue((source / "a.png").exists())
        with self.connect() as conn:
            row = conn.execute("SELECT path FROM gallery_images WHERE id=?", (row_id,)).fetchone()
        self.assertEqual("待删除/a.png", row["path"])


class FolderManagementIntegrationTests(unittest.TestCase):
    def test图库和工作流页面接入统一文件夹管理界面(self) -> None:
        client = TestClient(app_module.app)

        for path in ("/gallery", "/workflows"):
            response = client.get(path)
            self.assertEqual(200, response.status_code)
            self.assertIn('data-folder-manager', response.text)
            self.assertIn('data-folder-move-dialog', response.text)
            self.assertIn('data-folder-delete-dialog', response.text)
            self.assertIn('/static/folder-management.js?v=1', response.text)

    def test移动和删除路由在两个页面均已注册(self) -> None:
        post_routes = {
            route.path
            for route in app_module.app.routes
            if "POST" in getattr(route, "methods", set())
        }
        self.assertTrue(
            {
                "/gallery/folders/move",
                "/gallery/folders/delete",
                "/workflows/folders/move",
                "/workflows/folders/delete",
            }.issubset(post_routes)
        )

    def test共享脚本包含二次确认和目标目录过滤(self) -> None:
        script = (Path(app_module.BASE_DIR) / "static" / "folder-management.js").read_text(encoding="utf-8")
        self.assertIn("option.path !== source", script)
        self.assertIn("option.path !== parent", script)
        self.assertIn("data-folder-recursive", script)
        self.assertIn("showModal", script)

    def test文件夹菜单使用低对比竖排三点图标(self) -> None:
        base_dir = Path(app_module.BASE_DIR)
        gallery_html = (base_dir / "templates" / "gallery.html").read_text(encoding="utf-8")
        workflows_html = (base_dir / "templates" / "workflows.html").read_text(encoding="utf-8")
        style = (base_dir / "static" / "style.css").read_text(encoding="utf-8")

        self.assertNotIn(">•••</button>", gallery_html)
        self.assertNotIn(">•••</button>", workflows_html)
        self.assertIn(".folder-menu-toggle::before", style)
        self.assertIn("box-shadow: 0 -5px currentColor, 0 5px currentColor", style)
        self.assertIn("width: 28px", style)

    def test移动提交使用服务结果定位到新目录(self) -> None:
        client = TestClient(app_module.app)
        result = FolderOperationResult(
            source="来源",
            target="目标/来源",
            parent="目标",
            inventory=FolderInventory(tracked_file_count=1),
        )
        with patch.object(app_module, "move_managed_folder", return_value=result) as operation:
            response = client.post(
                "/gallery/folders/move",
                data={"source": "来源", "destination": "目标", "current": "来源"},
                follow_redirects=False,
            )

        self.assertEqual(303, response.status_code)
        self.assertIn("folder=%E7%9B%AE%E6%A0%87%2F%E6%9D%A5%E6%BA%90", response.headers["location"])
        self.assertEqual("来源", operation.call_args.args[2])
        self.assertEqual("目标", operation.call_args.args[3])

    def test递归删除提交传递确认并返回父目录(self) -> None:
        client = TestClient(app_module.app)
        result = FolderOperationResult(
            source="父级/待删除",
            target="",
            parent="父级",
            inventory=FolderInventory(tracked_file_count=2),
        )
        with patch.object(app_module, "delete_managed_folder", return_value=result) as operation:
            response = client.post(
                "/workflows/folders/delete",
                data={"folder": "父级/待删除", "current": "父级/待删除", "recursive": "true"},
                follow_redirects=False,
            )

        self.assertEqual(303, response.status_code)
        self.assertIn("folder=%E7%88%B6%E7%BA%A7", response.headers["location"])
        self.assertTrue(operation.call_args.kwargs["recursive"])


class GalleryImageOperationTests(unittest.TestCase):
    """v1.6.0 图片移动/删除：破坏性分支只在临时文件系统和临时数据库中执行。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.gallery_root = self.base / "gallery"
        (self.gallery_root / "来源").mkdir(parents=True)
        (self.gallery_root / "目标").mkdir()
        self.db_path = self.base / "test.sqlite3"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def connect(self):
        return db.connect(self.db_path)

    def add_image(self, folder: str, name: str, *, title: str = "人工标题", notes: str = "人工备注", rating: int = 4) -> int:
        (self.gallery_root / folder / name).write_bytes(b"png")
        path = f"{folder}/{name}" if folder else name
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO gallery_images (path, title, category, notes, rating) VALUES (?, ?, ?, ?, ?)",
                (path, title, Path(folder).name if folder else "", notes, rating),
            )
            return int(cursor.lastrowid)

    def gallery_row(self, row_id: int):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM gallery_images WHERE id=?", (row_id,)).fetchone()

    def test移动图片保留人工字段且分类跟随目标文件夹(self) -> None:
        row_id = self.add_image("来源", "a.png")

        result = move_gallery_images(self.gallery_root, [row_id], "目标", connect_factory=self.connect)

        self.assertEqual(1, result["moved"])
        self.assertTrue((self.gallery_root / "目标" / "a.png").exists())
        self.assertFalse((self.gallery_root / "来源" / "a.png").exists())
        row = self.gallery_row(row_id)
        self.assertEqual("目标/a.png", row["path"])
        self.assertEqual("目标", row["category"])
        self.assertEqual("人工标题", row["title"])
        self.assertEqual("人工备注", row["notes"])
        self.assertEqual(4, row["rating"])

    def test移动到根目录分类置空(self) -> None:
        row_id = self.add_image("来源", "a.png")

        move_gallery_images(self.gallery_root, [row_id], "", connect_factory=self.connect)

        row = self.gallery_row(row_id)
        self.assertEqual("a.png", row["path"])
        self.assertEqual("", row["category"])
        self.assertTrue((self.gallery_root / "a.png").exists())

    def test目标存在同名磁盘文件整体拒绝(self) -> None:
        row_id = self.add_image("来源", "a.png")
        (self.gallery_root / "目标" / "a.png").write_bytes(b"other")

        with self.assertRaisesRegex(FolderOperationError, "同名"):
            move_gallery_images(self.gallery_root, [row_id], "目标", connect_factory=self.connect)

        self.assertTrue((self.gallery_root / "来源" / "a.png").exists())
        self.assertEqual(b"other", (self.gallery_root / "目标" / "a.png").read_bytes())
        self.assertEqual("来源/a.png", self.gallery_row(row_id)["path"])

    def test目标路径被其他数据库记录占用整体拒绝(self) -> None:
        row_id = self.add_image("来源", "a.png")
        other_id = self.add_image("来源", "b.png")
        with self.connect() as conn:
            conn.execute("UPDATE gallery_images SET path='目标/a.png' WHERE id=?", (other_id,))

        with self.assertRaisesRegex(FolderOperationError, "冲突"):
            move_gallery_images(self.gallery_root, [row_id], "目标", connect_factory=self.connect)

        self.assertTrue((self.gallery_root / "来源" / "a.png").exists())
        self.assertEqual("来源/a.png", self.gallery_row(row_id)["path"])

    def test批量移动任一冲突则全部不动(self) -> None:
        first = self.add_image("来源", "a.png")
        second = self.add_image("来源", "b.png")
        (self.gallery_root / "目标" / "b.png").write_bytes(b"other")

        with self.assertRaises(FolderOperationError):
            move_gallery_images(self.gallery_root, [first, second], "目标", connect_factory=self.connect)

        self.assertTrue((self.gallery_root / "来源" / "a.png").exists())
        self.assertTrue((self.gallery_root / "来源" / "b.png").exists())
        self.assertEqual("来源/a.png", self.gallery_row(first)["path"])
        self.assertEqual("来源/b.png", self.gallery_row(second)["path"])

    def test选中图片同名无法移入同一文件夹(self) -> None:
        first = self.add_image("来源", "a.png")
        (self.gallery_root / "来源2").mkdir()
        second = self.add_image("来源2", "a.png")

        with self.assertRaisesRegex(FolderOperationError, "同名"):
            move_gallery_images(self.gallery_root, [first, second], "目标", connect_factory=self.connect)

        self.assertTrue((self.gallery_root / "来源" / "a.png").exists())
        self.assertTrue((self.gallery_root / "来源2" / "a.png").exists())

    def test移动无效编号与缺失文件报错(self) -> None:
        with self.assertRaisesRegex(FolderOperationError, "没有可操作的图片"):
            move_gallery_images(self.gallery_root, [999], "目标", connect_factory=self.connect)
        row_id = self.add_image("来源", "a.png")
        (self.gallery_root / "来源" / "a.png").unlink()
        with self.assertRaisesRegex(FolderOperationError, "不存在"):
            move_gallery_images(self.gallery_root, [row_id], "目标", connect_factory=self.connect)

    def test移动到不存在的目标文件夹报错(self) -> None:
        row_id = self.add_image("来源", "a.png")
        with self.assertRaisesRegex(FolderOperationError, "不存在"):
            move_gallery_images(self.gallery_root, [row_id], "不存在", connect_factory=self.connect)

    def test删除图片清理记录与磁盘且暂存清空(self) -> None:
        first = self.add_image("来源", "a.png")
        second = self.add_image("来源", "b.png")

        result = delete_gallery_images(self.gallery_root, [first, second], connect_factory=self.connect)

        self.assertEqual(2, result["deleted"])
        self.assertEqual("", result["warning"])
        self.assertFalse((self.gallery_root / "来源" / "a.png").exists())
        self.assertFalse((self.gallery_root / "来源" / "b.png").exists())
        self.assertIsNone(self.gallery_row(first))
        self.assertIsNone(self.gallery_row(second))
        self.assertFalse((self.base / ".folder-trash").exists())

    def test删除时文件已不在磁盘仍清理记录(self) -> None:
        row_id = self.add_image("来源", "a.png")
        (self.gallery_root / "来源" / "a.png").unlink()

        result = delete_gallery_images(self.gallery_root, [row_id], connect_factory=self.connect)

        self.assertEqual(1, result["deleted"])
        self.assertIsNone(self.gallery_row(row_id))

    def test删除无效编号报错(self) -> None:
        with self.assertRaisesRegex(FolderOperationError, "没有可操作的图片"):
            delete_gallery_images(self.gallery_root, [999], connect_factory=self.connect)


class GalleryImageTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = Path(app_module.BASE_DIR)
        cls.template = (base / "templates" / "gallery.html").read_text(encoding="utf-8")
        cls.dialogs = (base / "templates" / "_gallery_image_dialogs.html").read_text(encoding="utf-8")
        cls.script = (base / "static" / "gallery-images.js").read_text(encoding="utf-8")
        cls.style = (base / "static" / "style.css").read_text(encoding="utf-8")

    def test图片卡片具备操作与选择入口(self) -> None:
        self.assertIn("data-image-card", self.template)
        self.assertIn("data-image-select", self.template)
        self.assertIn("data-image-menu-toggle", self.template)
        self.assertIn("data-image-move", self.template)
        self.assertIn("data-image-delete", self.template)
        self.assertIn("data-image-selection-bar", self.template)
        self.assertIn("_gallery_image_dialogs.html", self.template)

    def test拖拽目标与脚本契约(self) -> None:
        self.assertIn("data-drop-folder", self.template)
        self.assertIn("application/x-gallery-ids", self.script)
        self.assertIn("__galleryImagesBound", self.script)
        self.assertIn("postImageAction", self.script)
        self.assertIn(".drop-target", self.style)
        self.assertIn(".image-selection-bar", self.style)

    def test图片弹窗提交到图片路由(self) -> None:
        self.assertIn('action="/gallery/images/move"', self.dialogs)
        self.assertIn('action="/gallery/images/delete"', self.dialogs)
        self.assertIn("/static/gallery-images.js", self.dialogs)


class GalleryLightboxZoomContractTests(unittest.TestCase):
    """v1.6.5 Lightbox 缩放：视口容器、工具条、滚轮/双击/指针平移、draggable 两态互斥。"""

    @classmethod
    def setUpClass(cls) -> None:
        base = Path(app_module.BASE_DIR)
        cls.template = (base / "templates" / "gallery.html").read_text(encoding="utf-8")
        cls.style = (base / "static" / "style.css").read_text(encoding="utf-8")

    def test视口与工具条结构(self) -> None:
        self.assertIn('class="lb-viewport" id="lb-viewport"', self.template)
        self.assertIn('class="lb-zoom-bar"', self.template)
        self.assertIn('id="lb-zoom-label"', self.template)
        self.assertIn('id="lb-img"', self.template)

    def test缩放交互脚本(self) -> None:
        self.assertIn("lbZoomTo", self.template)
        self.assertIn("lbZoomFit", self.template)
        self.assertIn("lbZoomActual", self.template)
        self.assertIn("lbResetZoom", self.template)
        self.assertIn("'wheel'", self.template)
        self.assertIn("passive: false", self.template)
        self.assertIn("'dblclick'", self.template)
        self.assertIn("'pointerdown'", self.template)
        self.assertIn("setPointerCapture", self.template)

    def test拖出与平移两态互斥(self) -> None:
        self.assertIn("lbImg.draggable = !zoomed", self.template)
        self.assertIn("lbResetZoom", self.template)

    def test缩放样式契约(self) -> None:
        self.assertIn(".lb-viewport {", self.style)
        self.assertIn(".lb-viewport.zoomed", self.style)
        self.assertIn(".lb-viewport.panning", self.style)
        self.assertIn(".lb-zoom-bar", self.style)
        self.assertIn("transform-origin: 0 0", self.style)
        self.assertNotIn(".lightbox-content > img", self.style)


if __name__ == "__main__":
    unittest.main()
