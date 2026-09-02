from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tag_manager import app as app_module
from tag_manager import db, tag_api


class TagApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "tag-api-test.sqlite3"
        db.init_db(self.db_path)
        self.connect_patch = patch.object(tag_api, "connect", lambda: db.connect(self.db_path))
        self.connect_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def create_category(self, name: str = "测试分类") -> dict:
        response = self.client.post(
            "/api/v1/categories",
            json={"name": name, "kind": "tag", "sort_order": 10, "notes": "测试分类备注"},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def create_tag(self, tag: str = "agent_test_tag", category: str = "测试分类", subcategory: str = "测试子类") -> dict:
        response = self.client.post(
            "/api/v1/tags",
            json={
                "tag": tag,
                "zh": "Agent 测试标签",
                "category": category,
                "subcategory": subcategory,
                "source": "自动测试",
                "rating": 3,
                "notes": "测试备注",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()


class TagCrudApiTests(TagApiTestCase):
    def test单项增查改删和分页过滤(self) -> None:
        self.create_category()
        created = self.create_tag()
        self.assertGreater(created["id"], 0)
        self.assertEqual("Agent 测试标签", created["zh"])

        page = self.client.get(
            "/api/v1/tags",
            params={"q": "Agent", "category": "测试分类", "limit": 1, "sort_by": "tag", "order": "asc"},
        )
        self.assertEqual(200, page.status_code)
        self.assertEqual(1, page.json()["total"])
        self.assertEqual("agent_test_tag", page.json()["items"][0]["tag"])
        self.assertFalse(page.json()["has_more"])
        self.assertIsNone(page.json()["next_offset"])

        fetched = self.client.get(f"/api/v1/tags/{created['id']}")
        self.assertEqual(created["id"], fetched.json()["id"])

        patched = self.client.patch(
            f"/api/v1/tags/{created['id']}",
            json={"zh": "更新后的中文", "rating": 9},
        )
        self.assertEqual(200, patched.status_code, patched.text)
        self.assertEqual("更新后的中文", patched.json()["zh"])
        self.assertEqual(9, patched.json()["rating"])
        self.assertEqual("测试备注", patched.json()["notes"])

        replaced = self.client.put(
            f"/api/v1/tags/{created['id']}",
            json={"tag": "replaced_tag", "category": "自动创建分类", "source": "替换测试"},
        )
        self.assertEqual(200, replaced.status_code, replaced.text)
        self.assertEqual("replaced_tag", replaced.json()["tag"])
        self.assertEqual("", replaced.json()["zh"])

        categories = self.client.get("/api/v1/categories").json()["items"]
        self.assertIn("自动创建分类", {item["name"] for item in categories})

        deleted = self.client.delete(f"/api/v1/tags/{created['id']}")
        self.assertEqual({"deleted": 1, "ids": [created["id"]], "tags": ["replaced_tag"]}, deleted.json())
        missing = self.client.get(f"/api/v1/tags/{created['id']}")
        self.assertEqual(404, missing.status_code)
        self.assertEqual("tag_not_found", missing.json()["detail"]["code"])

    def test创建冲突和请求校验错误清晰(self) -> None:
        created = self.create_tag(tag="duplicate_tag", category="自动分类")
        conflict = self.client.post("/api/v1/tags", json={"tag": "duplicate_tag"})
        self.assertEqual(409, conflict.status_code)
        self.assertEqual("tag_conflict", conflict.json()["detail"]["code"])

        empty_patch = self.client.patch(f"/api/v1/tags/{created['id']}", json={})
        self.assertEqual(422, empty_patch.status_code)
        invalid_limit = self.client.get("/api/v1/tags", params={"limit": 501})
        self.assertEqual(422, invalid_limit.status_code)


class TagBulkApiTests(TagApiTestCase):
    def test批量覆盖查询和删除(self) -> None:
        first = self.client.post(
            "/api/v1/tags/bulk-upsert",
            json={
                "items": [
                    {"tag": "bulk_a", "zh": "批量甲", "category": "批量分类", "rating": 1},
                    {"tag": "bulk_b", "zh": "批量乙", "category": "批量分类", "rating": 2},
                ]
            },
        )
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(2, first.json()["created"])
        self.assertEqual(0, first.json()["updated"])

        second = self.client.post(
            "/api/v1/tags/bulk-upsert",
            json={
                "items": [
                    {"tag": "bulk_a", "zh": "覆盖后的甲", "category": "批量分类", "rating": 8},
                    {"tag": "bulk_c", "zh": "批量丙", "category": "批量分类"},
                ]
            },
        )
        self.assertEqual(1, second.json()["created"])
        self.assertEqual(1, second.json()["updated"])

        lookup = self.client.post(
            "/api/v1/tags/lookup",
            json={"tags": ["bulk_c", "不存在", "bulk_a", "bulk_a"]},
        )
        self.assertEqual(["bulk_c", "bulk_a"], [item["tag"] for item in lookup.json()["items"]])
        self.assertEqual(["不存在"], lookup.json()["missing"])

        bulk_a_id = next(item["id"] for item in second.json()["items"] if item["tag"] == "bulk_a")
        deleted = self.client.post(
            "/api/v1/tags/bulk-delete",
            json={"ids": [bulk_a_id], "tags": ["bulk_b", "不存在"]},
        )
        self.assertEqual(2, deleted.json()["deleted"])
        self.assertEqual({"bulk_a", "bulk_b"}, set(deleted.json()["tags"]))

    def test批量重复项被拒绝且不产生部分写入(self) -> None:
        response = self.client.post(
            "/api/v1/tags/bulk-upsert",
            json={"items": [{"tag": "same"}, {"tag": "same", "zh": "重复"}]},
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual("duplicate_tag_in_request", response.json()["detail"]["code"])
        page = self.client.get("/api/v1/tags", params={"tag": "same"}).json()
        self.assertEqual(0, page["total"])


class CategoryAndSubcategoryApiTests(TagApiTestCase):
    def test分类重命名和二级分类操作同步Tag(self) -> None:
        category = self.create_category("原分类")
        tag = self.create_tag("category_tag", "原分类", "原子类")

        renamed_category = self.client.patch(
            f"/api/v1/categories/{category['id']}",
            json={"name": "新分类", "notes": "已重命名"},
        )
        self.assertEqual(200, renamed_category.status_code, renamed_category.text)
        self.assertEqual("新分类", renamed_category.json()["name"])
        self.assertEqual("新分类", self.client.get(f"/api/v1/tags/{tag['id']}").json()["category"])

        renamed_subcategory = self.client.post(
            "/api/v1/subcategories/rename",
            json={"category": "新分类", "name": "原子类", "new_name": "新子类"},
        )
        self.assertEqual(1, renamed_subcategory.json()["affected_tags"])
        subcategories = self.client.get("/api/v1/subcategories", params={"category": "新分类"}).json()
        self.assertEqual([{"category": "新分类", "name": "新子类", "count": 1}], subcategories)

        cleared = self.client.post(
            "/api/v1/subcategories/clear",
            json={"category": "新分类", "name": "新子类"},
        )
        self.assertEqual(1, cleared.json()["affected_tags"])
        self.assertEqual("", self.client.get(f"/api/v1/tags/{tag['id']}").json()["subcategory"])

        guarded = self.client.delete(
            f"/api/v1/categories/{category['id']}",
            params={"detach_tags": "false"},
        )
        self.assertEqual(409, guarded.status_code)
        self.assertEqual("category_not_empty", guarded.json()["detail"]["code"])

        deleted = self.client.delete(f"/api/v1/categories/{category['id']}")
        self.assertEqual({"deleted": 1, "detached_tags": 1}, deleted.json())
        detached_tag = self.client.get(f"/api/v1/tags/{tag['id']}").json()
        self.assertEqual("", detached_tag["category"])
        self.assertEqual("", detached_tag["subcategory"])


class TagLibraryExchangeApiTests(TagApiTestCase):
    def test整库导入导出和摘要(self) -> None:
        imported = self.client.post(
            "/api/v1/tag-library/import",
            json={
                "categories": [
                    {"name": "导入分类", "kind": "tag", "sort_order": 22, "notes": "导入备注"}
                ],
                "tags": [
                    {
                        "tag": "imported_tag",
                        "zh": "导入标签",
                        "category": "导入分类",
                        "subcategory": "导入子类",
                        "source": "导入测试",
                        "rating": 6,
                        "notes": "导入 Tag 备注",
                    }
                ],
            },
        )
        self.assertEqual(200, imported.status_code, imported.text)
        self.assertEqual(
            {"categories_upserted": 1, "tags_created": 1, "tags_updated": 0},
            imported.json(),
        )

        exported = self.client.get("/api/v1/tag-library/export")
        self.assertEqual(200, exported.status_code)
        self.assertEqual("v1", exported.json()["api_version"])
        exported_tag = next(item for item in exported.json()["tags"] if item["tag"] == "imported_tag")
        self.assertEqual(6, exported_tag["rating"])

        summary = self.client.get("/api/v1/tag-library")
        self.assertEqual(200, summary.status_code)
        self.assertEqual(1, summary.json()["tag_count"])
        self.assertGreaterEqual(summary.json()["category_count"], 1)
        self.assertEqual(1, summary.json()["subcategory_count"])
        self.assertEqual(500, summary.json()["max_bulk_items"])
        self.assertEqual(20000, summary.json()["max_import_tags"])

    def test整库导入容量高于常规批量上限(self) -> None:
        tags = [{"tag": f"large_import_{index}"} for index in range(501)]
        response = self.client.post("/api/v1/tag-library/import", json={"tags": tags})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(501, response.json()["tags_created"])
        self.assertEqual(501, self.client.get("/api/v1/tags", params={"q": "large_import_", "limit": 1}).json()["total"])


class TagApiOpenApiTests(TagApiTestCase):
    def test开放接口可由OpenAPI发现并保留旧接口(self) -> None:
        schema = self.client.get("/openapi.json").json()
        paths = schema["paths"]
        expected = {
            "/api/v1/tag-library",
            "/api/v1/tag-library/export",
            "/api/v1/tag-library/import",
            "/api/v1/tags",
            "/api/v1/tags/lookup",
            "/api/v1/tags/bulk-upsert",
            "/api/v1/tags/bulk-delete",
            "/api/v1/tags/{tag_id}",
            "/api/v1/categories",
            "/api/v1/categories/{category_id}",
            "/api/v1/subcategories",
            "/api/v1/subcategories/rename",
            "/api/v1/subcategories/clear",
        }
        self.assertTrue(expected.issubset(paths))
        self.assertIn("TagWrite", schema["components"]["schemas"])
        self.assertIn("TagRecord", schema["components"]["schemas"])
        self.assertIn("ErrorResponse", schema["components"]["schemas"])
        self.assertIn("/api/tags/page", paths)
        self.assertIn("/api/tags/lookup", paths)


if __name__ == "__main__":
    unittest.main()
