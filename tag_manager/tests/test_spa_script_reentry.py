from __future__ import annotations

import re
import unittest
from pathlib import Path

from tag_manager import app as app_module

TEMPLATES_DIR = Path(app_module.BASE_DIR) / "templates"

# SPA 路由会克隆 <script> 重执行：顶层 const/let 进入全局词法环境且跨 script 持久，
# 二次进入时整段内联脚本抛 SyntaxError 一行不执行。顶层声明一律用 var。
SPA_TEMPLATES = [
    "workshop.html",
    "gallery.html",
    "characters.html",
    "recipes.html",
    "loras.html",
]

INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
TOP_LEVEL_CONST_LET_RE = re.compile(r"^(?:const|let)\s", re.M)


def inline_scripts(template_name: str) -> list[str]:
    source = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    return INLINE_SCRIPT_RE.findall(source)


class SpaScriptReentryTests(unittest.TestCase):
    def test模板内联脚本顶层禁用const和let(self) -> None:
        for name in SPA_TEMPLATES:
            scripts = inline_scripts(name)
            self.assertTrue(scripts, f"{name} 应至少含一段内联脚本")
            for body in scripts:
                match = TOP_LEVEL_CONST_LET_RE.search(body)
                self.assertIsNone(
                    match,
                    f"{name} 内联脚本顶层存在 const/let 声明：{match.group(0) if match else ''}",
                )


if __name__ == "__main__":
    unittest.main()
