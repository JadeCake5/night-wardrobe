"""v1.27.0 首页布局契约测试：模块导航卡片、最近配方、最近角色卡。"""

from __future__ import annotations

import unittest
from pathlib import Path

from tag_manager import app as app_module

class IndexTemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = Path(app_module.BASE_DIR)
        cls.template = (base / "templates" / "index.html").read_text(encoding="utf-8")

    def test包含模块导览卡片区(self) -> None:
        # 应包含所有卡片的链接
        modules = ["/tags", "/characters", "/recipes", "/workshop", "/gallery", "/workflows", "/video-decrypt", "/manga", "/loras", "/gacha", "/update"]
        for mod in modules:
            self.assertIn(f'href="{mod}"', self.template)
        
        self.assertIn("module-card", self.template)

    def test包含最近活动区(self) -> None:
        self.assertIn("最近图库", self.template)
        self.assertIn("最近更新的配方", self.template)
        self.assertIn("最近更新的角色卡", self.template)
        self.assertIn("recent_images", self.template)
        self.assertIn("recent_recipes", self.template)
        self.assertIn("recent_characters", self.template)

if __name__ == "__main__":
    unittest.main()
