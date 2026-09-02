"""v1.9.0 紧凑工具栏化布局的模板与样式契约测试。"""

import unittest
from pathlib import Path

from tag_manager import app as app_module

BASE = Path(app_module.BASE_DIR)


class CompactToolbarContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.style = (BASE / "static" / "style.css").read_text(encoding="utf-8")
        cls.templates = {
            name: (BASE / "templates" / f"{name}.html").read_text(encoding="utf-8")
            for name in ("tags", "loras", "workshop", "characters", "recipes", "index", "gallery", "workflows")
        }

    def test工具栏样式体系存在(self) -> None:
        self.assertIn(".page-head {", self.style)
        self.assertIn(".page-head-actions", self.style)
        self.assertIn(".toolbar {", self.style)
        self.assertIn(".toolbar .spacer", self.style)
        self.assertIn(".search-box {", self.style)

    def test全局控件不再默认通栏(self) -> None:
        base_rule = self.style.split("input, select, textarea {", 1)[1].split("}", 1)[0]
        self.assertNotIn("width: 100%", base_rule)
        # 表单上下文内仍然占满整行
        self.assertIn(".vertical input", self.style)
        self.assertIn(".labeled-form input", self.style)

    def test各页面接入page_head(self) -> None:
        for name in ("tags", "loras", "characters", "recipes", "gallery"):
            self.assertIn('class="page-head"', self.templates[name], name)
        # v1.15.0：工坊页改用专属紧凑页头 ws-header（标题 + 一句话说明 + 右侧操作区）
        self.assertIn('class="ws-header"', self.templates["workshop"])

    def test搜索框统一为胶囊组件(self) -> None:
        for name in ("characters", "recipes", "gallery", "workflows"):
            self.assertIn('class="search-box"', self.templates[name], name)
        # 半宽长条搜索框只剩 groups 旧页使用，主页面不再出现
        for name in ("characters", "recipes", "index", "gallery", "workflows"):
            self.assertNotIn('class="search"', self.templates[name], name)

    def test图库与工作流三合一工具栏(self) -> None:
        for name in ("gallery", "workflows"):
            tpl = self.templates[name]
            self.assertNotIn("gallery-toolbar", tpl, name)
            self.assertNotIn("folder-actions", tpl.replace("current-folder-actions", ""), name)
            # 面包屑收进工具栏且位于搜索框之前
            toolbar_start = tpl.index('class="toolbar"')
            toolbar_end = tpl.index("</div>\n\n", toolbar_start) if "</div>\n\n" in tpl[toolbar_start:] else len(tpl)
            crumb = tpl.index("gallery-breadcrumbs", toolbar_start)
            search = tpl.index("search-box", toolbar_start)
            self.assertLess(crumb, search, name)
        # 图片拖入面包屑的投放钩子只在图库存在
        self.assertIn("data-drop-folder", self.templates["gallery"])

    def testLoRA上传区改为折叠面板(self) -> None:
        tpl = self.templates["loras"]
        self.assertIn('id="loraUploadToggle"', tpl)
        self.assertIn("uploadBox.hidden = !uploadBox.hidden", tpl)
        self.assertIn(".lora-upload[hidden]", self.style)
        # 有卡片时默认收起
        self.assertIn("{% if cards %} hidden{% endif %}", tpl)

    def test工坊配方面板不被长选项撑破(self) -> None:
        # v1.15.0：图例行收编为可点击过滤 chips，下拉框容器由 ws-select-row 改为 ws-select-wrap
        tpl = self.templates["workshop"]
        self.assertIn('class="ws-filter-chips"', tpl)
        self.assertNotIn("ws-legend-row", tpl)
        self.assertNotIn("ws-select-row", tpl)
        # select 占满容器宽度且允许收缩，避免长角色名撑破配方面板
        self.assertIn(".ws-select-wrap select { width: 100%;", self.style)
        self.assertIn(".ws-field select { width: 100%;", self.style)
        self.assertIn("updateClearButtons", tpl)

    def test首页操作区收进工具栏(self) -> None:
        tpl = self.templates["index"]
        self.assertIn('class="toolbar"', tpl)
        self.assertNotIn('class="actions"', tpl)
        self.assertIn("exportTagsJSON", tpl)

    def testTag页筛选坞保持单行紧凑且契约不变(self) -> None:
        tpl = self.templates["tags"]
        self.assertIn('<div class="filter-dock">', tpl)
        self.assertIn('id="tagSearchInput"', tpl)
        # 旧 tag-toolbar 已并入 page-head，JS 引用同步更新
        self.assertNotIn("tag-toolbar", tpl)
        self.assertIn(".page-head p", tpl)


if __name__ == "__main__":
    unittest.main()
