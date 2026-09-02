# -*- coding: utf-8 -*-
"""v1.10.0 Tag 全量分类：分类器单测 + 整理脚本在临时库上的事务测试。"""
from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tag_manager.organize_tag_library import GOLDEN, organize
from tag_manager.tag_taxonomy import (
    CAT_ACTION,
    CAT_CAMERA,
    CAT_CHARACTER,
    CAT_CLOTHES,
    CAT_EXPRESSION,
    CAT_MANUAL,
    CAT_NSFW,
    CAT_PERSON,
    CAT_SCENE,
    CAT_STYLE,
    CONTROLLED_SUBS,
    PRIMARY_CATEGORIES,
    classify,
)


class ClassifyGoldenTests(unittest.TestCase):
    def test黄金样本(self) -> None:
        cases = [
            ("touhou", "", "", "", CAT_CHARACTER, "东方"),
            ("genshin_impact", "", "", "", CAT_CHARACTER, "原神"),
            ("azur_lane", "", "", "", CAT_CHARACTER, "碧蓝航线"),
            ("hood_(azur_lane)", "胡德", CAT_CHARACTER, "碧蓝航线", CAT_CHARACTER, "碧蓝航线"),
            ("yae_miko", "八重神子", CAT_CHARACTER, "原神", CAT_CHARACTER, "原神"),
            ("sword_art_online", "刀剑神域", CAT_CHARACTER, "刀剑神域", CAT_CHARACTER, "刀剑神域"),
            ("rice_shower_(umamusume)", "米浴", CAT_CHARACTER, "赛马娘", CAT_CHARACTER, "赛马娘"),
            ("mountain_(arknights)", "山", CAT_CHARACTER, "明日方舟", CAT_CHARACTER, "明日方舟"),
            ("doctor_(arknights)", "", CAT_CHARACTER, "明日方舟", CAT_CHARACTER, "明日方舟"),
            ("cardigan_(arknights)", "", CAT_CHARACTER, "明日方舟", CAT_CHARACTER, "明日方舟"),
            ("blonde_hair", "金发", CAT_PERSON, "金发狐娘", CAT_PERSON, "头发颜色"),
            ("red_eyes", "红眼", "", "", CAT_PERSON, "眼睛"),
            ("large_breasts", "巨乳", CAT_NSFW, "身体", CAT_PERSON, "身体"),
            ("cowboy_shot", "牛仔镜头", CAT_CAMERA, "景别", CAT_CAMERA, "景别"),
            ("looking_at_viewer", "看向观众", CAT_ACTION, "视线", CAT_ACTION, "视线"),
            ("masterpiece", "杰作", CAT_MANUAL, "质量与画风", CAT_STYLE, "质量"),
            ("bikini", "比基尼", CAT_CLOTHES, "dougi🥋", CAT_CLOTHES, "内衣泳装"),
            ("school_uniform", "校服", CAT_CLOTHES, "正装", CAT_CLOTHES, "制服套装"),
            ("smile", "笑", CAT_EXPRESSION, "笑", CAT_EXPRESSION, "笑"),
            ("indoors", "室内", CAT_SCENE, "@dropdown", CAT_SCENE, "室内"),
            ("outdoors", "室外", CAT_SCENE, "室外", CAT_SCENE, "室外"),
            ("sword", "剑", CAT_SCENE, "武器", CAT_SCENE, "武器"),
            ("after_sex", "事后", CAT_NSFW, "69", CAT_NSFW, "性行为"),
            ("mosaic_censoring", "马赛克", CAT_NSFW, "马赛克", CAT_NSFW, "马赛克"),
            ("shiratama_(shiratamaco)", "白玉", CAT_STYLE, "画师", CAT_STYLE, "画师"),
            ("unleashed", "带子松开", CAT_CHARACTER, "带子松开", CAT_ACTION, "动作"),
            ("lunar", "月的", CAT_CHARACTER, "月的", CAT_SCENE, "天气时间"),
            ("tenga", "腾加", CAT_CHARACTER, "腾加", CAT_NSFW, "其他"),
            ("lycoris_recoil", "石蒜", CAT_CHARACTER, "石蒜后坐力", CAT_CHARACTER, "莉可丽丝"),
            ("cat_ears", "猫耳", CAT_SCENE, "扶桑花", CAT_PERSON, "兽耳兽尾"),
            ("dog_girl", "犬娘", CAT_SCENE, "扶桑花", CAT_PERSON, "身份"),
            ("arms_up", "举手", CAT_NSFW, "69", CAT_ACTION, "手势"),
            ("bishoujo_senshi_sailor_moon", "美少女战士", CAT_CHARACTER, "美少女战士", CAT_CHARACTER, "美少女战士"),
            ("(solo:1.4)", "单人权重", CAT_PERSON, "金发狐娘", CAT_PERSON, "人数性别"),
            ("(rurudo:0.6)", "画风", CAT_MANUAL, "画师权重", CAT_MANUAL, "画师权重"),
            ("<lora:YZ:1>", "LoRA", CAT_MANUAL, "LoRA调用", CAT_MANUAL, "LoRA调用"),
            ("calamity_queller_(genshin_impact)", "息灾", CAT_SCENE, "武器", CAT_SCENE, "武器"),
            ("holding_hat", "拿着帽子", CAT_ACTION, "手", CAT_ACTION, "手势"),
        ]
        for tag, zh, old_cat, old_sub, expect_cat, expect_sub in cases:
            got = classify(tag, zh, old_cat, old_sub)
            self.assertEqual((expect_cat, expect_sub), got, tag)

    def test非角色二级分类必须受控(self) -> None:
        samples = [
            "blonde_hair",
            "red_eyes",
            "smile",
            "sitting",
            "indoors",
            "masterpiece",
            "bikini",
            "after_sex",
            "cowboy_shot",
            "arms_up",
            "cat_ears",
        ]
        for tag in samples:
            cat, sub = classify(tag)
            self.assertIn(cat, PRIMARY_CATEGORIES, tag)
            if cat != CAT_CHARACTER:
                self.assertIn(sub, CONTROLLED_SUBS[cat], f"{tag} -> {cat}/{sub}")


class OrganizeTempDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "tags.sqlite3"
        self.json_path = Path(self.temp_dir.name) / "tag_library.json"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                kind TEXT DEFAULT 'tag',
                sort_order INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL UNIQUE,
                zh TEXT DEFAULT '',
                category TEXT DEFAULT '',
                subcategory TEXT DEFAULT '',
                source TEXT DEFAULT '',
                rating INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        rows = [
            ("touhou", "东方", "2.人物", "东方"),
            ("blonde_hair", "金发", "2.人物", "金发狐娘"),
            ("arms_up", "举手", "0.可以涩涩", "69"),
            ("cat_ears", "猫耳", "6.场景道具", "扶桑花"),
            ("masterpiece", "杰作", "手工添加", "质量与画风"),
            ("<lora:YZ:1>", "LoRA", "手工添加", "LoRA调用"),
            ("unleashed", "带子松开", "4.角色/作品", "带子松开"),
            ("hood_(azur_lane)", "胡德", "4.角色/作品", "碧蓝航线"),
            ("bikini", "比基尼", "3.服饰", "dougi🥋"),
            ("NSFW leftover", "残留", "NSFW Tags", "69"),
        ]
        conn.executemany(
            "INSERT INTO tags (tag, zh, category, subcategory) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.execute("INSERT INTO categories (name, kind) VALUES ('NSFW Tags', 'tag')")
        conn.execute("INSERT INTO categories (name, kind) VALUES ('2.人物', 'tag')")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test整理临时库不删tag并清掉垃圾分类(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = organize(self.db_path, self.json_path, apply=True)
        self.assertEqual(0, code, buf.getvalue())
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self.assertEqual(10, conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0])
        mapping = {r["tag"]: (r["category"], r["subcategory"]) for r in conn.execute("SELECT tag, category, subcategory FROM tags")}
        self.assertEqual((CAT_CHARACTER, "东方"), mapping["touhou"])
        self.assertEqual((CAT_PERSON, "头发颜色"), mapping["blonde_hair"])
        self.assertEqual((CAT_ACTION, "手势"), mapping["arms_up"])
        self.assertEqual((CAT_PERSON, "兽耳兽尾"), mapping["cat_ears"])
        self.assertEqual((CAT_STYLE, "质量"), mapping["masterpiece"])
        self.assertEqual((CAT_MANUAL, "LoRA调用"), mapping["<lora:YZ:1>"])
        self.assertEqual((CAT_ACTION, "动作"), mapping["unleashed"])
        self.assertEqual((CAT_CHARACTER, "碧蓝航线"), mapping["hood_(azur_lane)"])
        self.assertEqual((CAT_CLOTHES, "内衣泳装"), mapping["bikini"])
        leftover = conn.execute("SELECT COUNT(*) FROM tags WHERE subcategory IN ('未分类', '69', '扶桑花', '金发狐娘', 'dougi🥋')").fetchone()[0]
        self.assertEqual(0, leftover)
        names = {r[0] for r in conn.execute("SELECT name FROM categories")}
        self.assertNotIn("NSFW Tags", names)
        self.assertTrue(self.json_path.exists())
        conn.close()


class GoldenKeysExistTests(unittest.TestCase):
    def test契约键完整(self) -> None:
        self.assertIn("touhou", GOLDEN)
        self.assertEqual(("4.角色/作品", "东方"), GOLDEN["touhou"])


class SemanticMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tag_manager.organize_tag_library import load_semantic_lookup

        cls.lookup = load_semantic_lookup()
        if not cls.lookup:
            raise unittest.SkipTest("本地人工语义映射 tag_review/manual_map.json 不存在（发布版不含此一次性迁移资料）")

    def test映射覆盖全库且无非法二级(self) -> None:
        self.assertGreaterEqual(len(self.lookup), 5954)
        from tag_manager.tag_taxonomy import CONTROLLED_SUBS, PRIMARY_CATEGORIES

        for tag, (cat, sub) in self.lookup.items():
            self.assertIn(cat, PRIMARY_CATEGORIES, tag)
            if cat != "4.角色/作品":
                self.assertIn(sub, CONTROLLED_SUBS[cat], f"{tag} -> {cat}/{sub}")

    def test逐条修正已写入映射(self) -> None:
        self.assertEqual(("4.角色/作品", "我推的孩子"), self.lookup["kitagawa_marin"])
        self.assertEqual(("4.角色/作品", "魔界战记"), self.lookup["fear_kubrick"])
        self.assertEqual(("4.角色/作品", "碧蓝航线"), self.lookup["hood_(azur_lane)"])
        self.assertEqual(("4.角色/作品", "刀剑神域"), self.lookup["sword_art_online"])
        self.assertEqual(("2.人物", "妆容"), self.lookup["makeup"])
        self.assertEqual(("3.服饰", "披风"), self.lookup["cape"])
