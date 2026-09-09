from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tag_manager import app as app_module
from tag_manager import db
from tag_manager import lora_routes

CHAR_COUNT = 120
CHAR_PAGE_LIMIT = 60
LORA_COUNT = 120
LORA_PAGE_LIMIT = 60


class CharactersPageTests(unittest.TestCase):
    """角色卡列表分页契约：首屏限量 + /api/characters/page 追加批次。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        db.init_db(self.db_path)
        with db.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO characters (name, lora, lora_weight, trigger_words, appearance, notes) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f"角色{i:04d}", f"lora_{i}.safetensors", 1.0, f"tw_{i}", f"appearance_{i}", f"notes_{i}")
                    for i in range(CHAR_COUNT)
                ],
            )
            conn.executemany(
                "INSERT INTO character_outfits (character_id, name, tags) VALUES (?, ?, ?)",
                [(i + 1, f"套装{i}", f"outfit_tags_{i}") for i in range(5)],
            )
        self.connect_patch = patch.object(app_module, "connect", lambda: db.connect(self.db_path))
        self.connect_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def test首屏只渲染一页角色卡(self) -> None:
        response = self.client.get("/characters")

        self.assertEqual(200, response.status_code)
        # 只数服务端渲染的卡片（JS 模板字面量是 ${id} 占位，不匹配 \d+）
        self.assertEqual(CHAR_PAGE_LIMIT, len(re.findall(r'onclick="editChar\(\d+\)"', response.text)))
        self.assertIn("loadMoreChars", response.text)
        self.assertIn("/api/characters/page", response.text)

    def test分页接口默认批次为一页且用探测行判断后续(self) -> None:
        payload = self.client.get("/api/characters/page").json()

        self.assertEqual(CHAR_PAGE_LIMIT, len(payload["rows"]))
        self.assertEqual(CHAR_PAGE_LIMIT, payload["next_offset"])
        self.assertTrue(payload["has_more"])
        # 探测行只用于 has_more，不得泄漏进 rows
        self.assertTrue(all(int(r["id"]) <= CHAR_COUNT for r in payload["rows"]))

    def test分页接口第二页与末页(self) -> None:
        second = self.client.get("/api/characters/page", params={"offset": CHAR_PAGE_LIMIT}).json()

        self.assertEqual(CHAR_COUNT - CHAR_PAGE_LIMIT, len(second["rows"]))
        self.assertFalse(second["has_more"])
        self.assertEqual(CHAR_COUNT, second["next_offset"])

    def test分页行附带本页服装且与首屏数据路径一致(self) -> None:
        payload = self.client.get("/api/characters/page").json()
        first_ids = [r["id"] for r in payload["rows"]]

        with_outfits = [r for r in payload["rows"] if r["outfits"]]
        self.assertTrue(with_outfits)
        for row in with_outfits:
            self.assertIn(row["id"], first_ids)
            for outfit in row["outfits"]:
                self.assertIn("name", outfit)
                self.assertIn("tags", outfit)
        # 只有前 5 个角色有服装：分页行不得夹带其他角色的套组
        outfit_owner_ids = [r["id"] for r in payload["rows"] if r["outfits"]]
        self.assertEqual([1, 2, 3, 4, 5], outfit_owner_ids)

    def test搜索与页面首屏同一路径(self) -> None:
        page = self.client.get("/characters", params={"q": "角色0007"})
        payload = self.client.get("/api/characters/page", params={"q": "角色0007"}).json()

        self.assertEqual(1, len(payload["rows"]))
        self.assertFalse(payload["has_more"])
        self.assertIn("角色0007", page.text)

    def test加载更多按钮携带查询条件(self) -> None:
        # 满一页时渲染「加载更多」；data-q 供追加批次延续当前搜索
        page = self.client.get("/characters")

        self.assertIn('data-q=""', page.text)
        search_page = self.client.get("/characters", params={"q": "角色"})
        self.assertIn('data-q="角色"', search_page.text)

    def test分页上限被钳制(self) -> None:
        payload = self.client.get("/api/characters/page", params={"limit": 9999}).json()

        self.assertLessEqual(len(payload["rows"]), 200)


class LoraPageTests(unittest.TestCase):
    """LoRA 库分页契约：db 层 LIMIT + /loras 首屏限量 + /api/loras/page 追加批次。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.preview_dir = Path(self.temp_dir.name) / "lora_previews"
        db.init_db(self.db_path)
        factory = lambda: db.connect(self.db_path)  # noqa: E731
        with factory() as conn:
            conn.executemany(
                """
                INSERT INTO lora_cards (name, filename, base_model, net_dim, suggested_weight, trigger_words)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (f"lora-{i:04d}", f"lora_{i}.safetensors", "SDXL", "16", 0.8, f"tw{i}")
                    for i in range(LORA_COUNT)
                ],
            )
        patchers = [
            patch.object(lora_routes, "list_lora_cards", lambda *a, **kw: db.list_lora_cards(connect_factory=factory, **kw)),
            patch.object(lora_routes, "LORA_PREVIEW_DIR", self.preview_dir),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test首屏只渲染一页LoRA卡(self) -> None:
        response = self.client.get("/loras")

        self.assertEqual(200, response.status_code)
        # 只数服务端渲染的卡片（JS 模板字面量是 ${id} 占位，不匹配 \d+）
        self.assertEqual(LORA_PAGE_LIMIT, len(re.findall(r'data-lora-id="\d+"', response.text)))
        self.assertIn("loadMoreLoras", response.text)
        self.assertIn("/api/loras/page", response.text)

    def test分页接口默认批次为一页(self) -> None:
        payload = self.client.get("/api/loras/page").json()

        self.assertEqual(LORA_PAGE_LIMIT, len(payload["rows"]))
        self.assertEqual(LORA_PAGE_LIMIT, payload["next_offset"])
        self.assertTrue(payload["has_more"])

    def test分页接口第二页与末页(self) -> None:
        second = self.client.get("/api/loras/page", params={"offset": LORA_PAGE_LIMIT}).json()

        self.assertEqual(LORA_COUNT - LORA_PAGE_LIMIT, len(second["rows"]))
        self.assertFalse(second["has_more"])

    def test_db层分页查询与全量调用共存(self) -> None:
        factory = lambda: db.connect(self.db_path)  # noqa: E731

        page = db.list_lora_cards(connect_factory=factory, offset=0, limit=10)
        all_cards = db.list_lora_cards(connect_factory=factory)

        self.assertEqual(10, len(page))
        self.assertEqual(LORA_COUNT, len(all_cards))
        self.assertEqual([c["id"] for c in all_cards[:10]], [c["id"] for c in page])


class GalleryDetailApiTests(unittest.TestCase):
    """图库 Lightbox 按需详情接口契约。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        db.init_db(self.db_path)
        with db.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO gallery_images
                    (path, title, category, positive_prompt, negative_prompt, checkpoint, loras,
                     parameters, metadata_json, metadata_source, generation_params)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "样例目录/图 一.png",
                    "样例标题",
                    "人物",
                    "masterpiece, best quality",
                    "lowres, bad anatomy",
                    "sdxl_base.safetensors",
                    "<lora:style:0.8>",
                    "Steps: 30, Seed: 12345",
                    '{"prompt": "meta"}',
                    "PNG info",
                    "",
                ),
            )
        self.connect_patch = patch.object(app_module, "connect", lambda: db.connect(self.db_path))
        self.connect_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def test按id返回单条详情且路径已编码(self) -> None:
        response = self.client.get("/api/gallery/1")

        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual(1, data["id"])
        self.assertEqual("/gallery-files/%E6%A0%B7%E4%BE%8B%E7%9B%AE%E5%BD%95/%E5%9B%BE%20%E4%B8%80.png", data["src"])
        self.assertEqual("样例标题", data["title"])
        self.assertEqual("masterpiece, best quality", data["positive"])
        self.assertEqual("lowres, bad anatomy", data["negative"])
        self.assertEqual("sdxl_base.safetensors", data["checkpoint"])
        self.assertEqual("<lora:style:0.8>", data["loras"])
        self.assertEqual("Steps: 30, Seed: 12345", data["parameters"])
        self.assertEqual('{"prompt": "meta"}', data["metadata"])
        self.assertEqual("PNG info", data["metadataSource"])

    def testgeneration_params优先于parameters(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute("UPDATE gallery_images SET generation_params='Steps: 60' WHERE id=1")

        data = self.client.get("/api/gallery/1").json()

        self.assertEqual("Steps: 60", data["parameters"])

    def test不存在图片返回404(self) -> None:
        response = self.client.get("/api/gallery/9999")

        self.assertEqual(404, response.status_code)
        self.assertIn("error", response.json())


if __name__ == "__main__":
    unittest.main()
