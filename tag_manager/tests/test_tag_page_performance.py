from __future__ import annotations

import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tag_manager import app as app_module
from tag_manager import db

TAG_COUNT = 150
PAGE_LIMIT = 80


class TagPageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        db.init_db(self.db_path)
        with db.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO tags (tag, zh, category, subcategory, rating, notes) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f"perf_tag_{i:04d}", f"性能标签{i}", f"分类{i % 3}", f"子类{i % 5}", i % 4, f"备注{i}")
                    for i in range(TAG_COUNT)
                ],
            )
        self.queries: list[str] = []

        @contextmanager
        def counting_connect():
            with db.connect(self.db_path) as conn:
                conn.set_trace_callback(self.queries.append)
                yield conn

        self.connect_patcher = patch.object(app_module, "connect", counting_connect)
        self.connect_patcher.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.connect_patcher.stop()
        self.temp_dir.cleanup()

    def select_statements(self) -> list[str]:
        return [q for q in self.queries if q.lstrip().upper().startswith("SELECT")]


class TagPageBatchTests(TagPageTestCase):
    def test首屏最多渲染一页卡片(self) -> None:
        response = self.client.get("/tags")

        self.assertEqual(200, response.status_code)
        # 排除前端 tagTileHTML 模板字符串中的 ${...} 占位片段
        rendered = re.findall(r'<article class="tag-tile" title="(?!\$\{)', response.text)
        self.assertEqual(PAGE_LIMIT, len(rendered))

    def test首屏与分页接口默认批次为一页(self) -> None:
        response = self.client.get("/api/tags/page")

        payload = response.json()
        self.assertEqual(PAGE_LIMIT, len(payload["rows"]))
        self.assertEqual(PAGE_LIMIT, payload["next_offset"])

    def test分页接口默认不执行COUNT且用探测行判断后续(self) -> None:
        self.queries.clear()
        first = self.client.get("/api/tags/page").json()

        self.assertTrue(first["has_more"])
        self.assertNotIn("shown_count", first)
        self.assertEqual(1, len(self.select_statements()))
        self.assertFalse(any("COUNT" in q.upper() for q in self.select_statements()))

        self.queries.clear()
        second = self.client.get("/api/tags/page", params={"offset": PAGE_LIMIT}).json()
        self.assertEqual(TAG_COUNT - PAGE_LIMIT, len(second["rows"]))
        self.assertFalse(second["has_more"])

    def test分页接口按需返回COUNT(self) -> None:
        payload = self.client.get("/api/tags/page", params={"include_count": "true"}).json()

        self.assertEqual(TAG_COUNT, payload["shown_count"])
        self.assertTrue(any("COUNT" in q.upper() for q in self.select_statements()))

    def test筛选接口一次返回行与分类统计且与页面数据一致(self) -> None:
        page = self.client.get("/tags", params={"category": "分类1"})
        payload = self.client.get("/api/tags/filter", params={"category": "分类1"}).json()

        self.assertEqual(TAG_COUNT // 3, payload["shown_count"])
        self.assertEqual(TAG_COUNT, payload["total_count"])
        self.assertEqual(TAG_COUNT // 3, len(payload["rows"]))
        self.assertFalse(payload["has_more"])
        self.assertEqual("分类1", payload["category"])
        # 分类统计来自 categories 表（含默认分类），校验结构与计数类型
        self.assertTrue(payload["categories"])
        for item in payload["categories"]:
            self.assertIsInstance(item["category"], str)
            self.assertIsInstance(item["count"], int)
        self.assertTrue(payload["subcategories"])
        # 与整页渲染的行顺序一致（同一数据装配路径）
        page_tags = [
            tag for tag in re.findall(r'class="tag-button" data-tag="([^"]+)"', page.text)
            if not tag.startswith("${")
        ]
        self.assertEqual([r["tag"] for r in payload["rows"]], page_tags)

    def test搜索筛选走同一数据路径(self) -> None:
        payload = self.client.get("/api/tags/filter", params={"q": "perf_tag_0000"}).json()

        self.assertEqual(1, payload["shown_count"])
        self.assertFalse(payload["has_more"])
        self.assertEqual("perf_tag_0000", payload["rows"][0]["tag"])


class TagPageIndexTests(TagPageTestCase):
    def query_plan(self, sql: str, params: tuple = ()) -> list[str]:
        with db.connect(self.db_path) as conn:
            return [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]

    def test列表查询使用复合索引且不再临时排序(self) -> None:
        order = "ORDER BY rating DESC, category, subcategory, tag LIMIT 81 OFFSET 0"
        cases = [
            "SELECT * FROM tags WHERE 1=1 " + order,
            ("SELECT * FROM tags WHERE 1=1 AND category = ? " + order, ("分类1",)),
        ]
        for case in cases:
            sql, params = (case, ()) if isinstance(case, str) else case
            plan = self.query_plan(sql, params)
            self.assertTrue(any("idx_tags_" in step for step in plan), plan)
            self.assertFalse(any("TEMP B-TREE" in step for step in plan), plan)


class TagPageTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = (Path(app_module.BASE_DIR) / "templates" / "tags.html").read_text(encoding="utf-8")

    def test模板具备性能优化契约(self) -> None:
        self.assertIn("IntersectionObserver", self.template)
        self.assertIn("AbortController", self.template)
        self.assertIn("window.__wardrobePageCleanup", self.template)
        self.assertIn("/api/tags/filter", self.template)
        self.assertIn("tagScrollSentinel", self.template)

    def test模板已移除泄漏与整页解析(self) -> None:
        self.assertNotIn("addEventListener('scroll'", self.template)
        self.assertNotIn("addEventListener('popstate'", self.template)
        self.assertNotIn("DOMParser", self.template)
        self.assertNotIn("bindTabClicks", self.template)

    def test模板状态收进初始化作用域(self) -> None:
        script = self.template.split("<script>", 1)[1]
        self.assertTrue(script.lstrip().startswith("(function()"))
        # 顶层不得再出现全局词法声明，避免局部导航重进时重复声明编译失败
        self.assertNotRegex(script, r"(?m)^let\s")
        self.assertNotRegex(script, r"(?m)^const\s")


if __name__ == "__main__":
    unittest.main()
