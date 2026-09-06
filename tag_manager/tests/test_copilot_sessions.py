from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from tag_manager import app as app_module
from tag_manager import copilot_history as history
from tag_manager import copilot_sessions as sessions
from tag_manager import db
from tag_manager.copilot_service import generate_suggestion


class FakeLLM:
    def __init__(self, contents=None) -> None:
        if isinstance(contents, str):
            contents = [contents]
        self.contents = list(contents or [])
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.contents:
            return ""
        index = min(len(self.calls) - 1, len(self.contents) - 1)
        return self.contents[index]


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def ok_suggestion(**overrides) -> dict:
    payload = {"summary": "完成", "diagnostics": [], "operations": [], "stages": []}
    payload.update(overrides)
    return payload


def default_request(**overrides) -> dict:
    request = {
        "action": "diagnose",
        "instruction": "",
        "context": {
            "positive": "1girl, solo",
            "negative": "lowres, worst quality",
            "recipe": {"charId": 1, "outfitId": 2, "artistId": 3, "sceneId": 4, "negativeId": 5},
            "enabled_contexts": ["positive", "negative", "recipe"],
        },
        "history": [],
    }
    request.update(overrides)
    return request


def factory_for(db_path: Path):
    def _factory():
        return db.connect(db_path)

    return _factory


class CopilotSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "sessions.sqlite3"
        db.init_db(self.db_path)
        self.cf = factory_for(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test创建会话与默认标题(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        self.assertEqual("新会话", session["title"])
        self.assertTrue(session["id"])
        self.assertEqual("", session["context_snapshot"]["character"])
        self.assertIsNone(session["parent_session_id"])

    def test默认标题来自第一条用户消息截取(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        text = "纸箱场景动作优化并且还要补充花园构图细节abcdefghijklmnopqrstuvwxyz"
        sessions.append_message(
            session["id"],
            "user",
            history.build_user_content(text=text, action="freeform"),
            connect_factory=self.cf,
        )
        stored = sessions.get_session(session["id"], connect_factory=self.cf)
        self.assertEqual(sessions.default_title_from_text(text), stored["title"])
        self.assertLessEqual(len(stored["title"]), 20)
        self.assertNotIn("\n", stored["title"])

    def test标题清理换行(self) -> None:
        title = sessions.default_title_from_text("第一行\n第二行\t空格")
        self.assertEqual("第一行 第二行 空格", title)

    def test重命名(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        renamed = sessions.rename_session(session["id"], "  花园构图  ", connect_factory=self.cf)
        self.assertEqual("花园构图", renamed["title"])

    def test删除级联消息(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        sessions.append_message(
            session["id"],
            "user",
            history.build_user_content(text="你好"),
            connect_factory=self.cf,
        )
        sessions.delete_session(session["id"], connect_factory=self.cf)
        self.assertIsNone(sessions.get_session(session["id"], connect_factory=self.cf))
        self.assertEqual([], sessions.list_messages(session["id"], connect_factory=self.cf))
        with db.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM copilot_messages").fetchone()["n"]
        self.assertEqual(0, count)

    def test列表按updated_at降序(self) -> None:
        first = sessions.create_session(title="旧", connect_factory=self.cf)
        second = sessions.create_session(title="新", connect_factory=self.cf)
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE copilot_sessions SET updated_at=? WHERE id=?",
                ("2026-01-01 00:00:00", first["id"]),
            )
            conn.execute(
                "UPDATE copilot_sessions SET updated_at=? WHERE id=?",
                ("2026-01-02 00:00:00", second["id"]),
            )
        listed = sessions.list_sessions(connect_factory=self.cf)
        self.assertEqual(second["id"], listed[0]["id"])
        sessions.append_message(
            first["id"],
            "user",
            history.build_user_content(text="让旧会话更新"),
            connect_factory=self.cf,
        )
        listed = sessions.list_sessions(connect_factory=self.cf)
        self.assertEqual(first["id"], listed[0]["id"])
        self.assertEqual(second["id"], listed[1]["id"])

    def test搜索标题(self) -> None:
        sessions.create_session(title="纸箱场景", connect_factory=self.cf)
        sessions.create_session(title="花园构图", connect_factory=self.cf)
        found = sessions.list_sessions(q="纸箱", connect_factory=self.cf)
        self.assertEqual(["纸箱场景"], [item["title"] for item in found])

    def test详情与消息顺序(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        sessions.append_message(session["id"], "user", history.build_user_content(text="一"), connect_factory=self.cf)
        sessions.append_message(session["id"], "assistant", history.build_assistant_content({"summary": "二", "operations": []}), connect_factory=self.cf)
        sessions.append_message(session["id"], "error", history.build_error_content(message="三"), connect_factory=self.cf)
        detail = sessions.get_session_detail(session["id"], connect_factory=self.cf)
        texts = [item["content"]["text"] for item in detail["messages"]]
        seqs = [item["seq"] for item in detail["messages"]]
        self.assertEqual(["一", "二", "三"], texts)
        self.assertEqual([1, 2, 3], seqs)

    def test_json_parts_roundtrip(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        payload = history.build_assistant_content(
            {
                "id": "llm-test",
                "action": "diagnose",
                "summary": "建议",
                "diagnostics": [{"id": "d-1", "level": "warning", "message": "缺动作"}],
                "operations": [{"kind": "add", "target": "positive", "tag": "dynamic pose"}],
                "stages": [{"label": "解析"}],
            },
            tools=[{"name": "search_tags", "status": "ok", "summary": "找到 2 个相关 Tag", "result_summary": "1girl"}],
        )
        stored = sessions.append_message(session["id"], "assistant", payload, connect_factory=self.cf)
        parts = stored["content"]["parts"]
        types = [part["type"] for part in parts]
        self.assertIn("text", types)
        self.assertIn("execution", types)
        self.assertIn("diagnosis", types)
        self.assertIn("diff", types)
        self.assertIn("tool", types)
        tool = next(part for part in parts if part["type"] == "tool")
        self.assertEqual("search_tags", tool["data"]["name"])
        self.assertNotIn("appearance", json.dumps(stored["content"], ensure_ascii=False))
        err = sessions.append_message(
            session["id"],
            "error",
            history.build_error_content(message="模型超时"),
            connect_factory=self.cf,
        )
        err_types = [part["type"] for part in err["content"]["parts"]]
        self.assertEqual(["error"], err_types)
        self.assertEqual("模型超时", err["content"]["parts"][0]["data"]["message"])

    def test_context_snapshot_roundtrip(self) -> None:
        snap = {
            "character": "小怡",
            "outfit": "花园",
            "artist": "画师串",
            "scene": "纸箱",
            "negative_template": "质量负面",
            "positive_preview": "1girl, garden",
            "negative_preview": "lowres",
            "secret": "should-drop",
        }
        session = sessions.create_session(context_snapshot=snap, connect_factory=self.cf)
        loaded = sessions.get_session(session["id"], connect_factory=self.cf)
        self.assertEqual("小怡", loaded["context_snapshot"]["character"])
        self.assertEqual("1girl, garden", loaded["context_snapshot"]["positive_preview"])
        self.assertNotIn("secret", loaded["context_snapshot"])

    def test_apply与reject状态可恢复(self) -> None:
        session = sessions.create_session(connect_factory=self.cf)
        stored = sessions.append_message(
            session["id"],
            "assistant",
            history.build_assistant_content(
                {
                    "summary": "可应用",
                    "operations": [
                        {"kind": "add", "target": "positive", "tag": "dynamic pose"},
                        {"kind": "add", "target": "positive", "tag": "looking at viewer"},
                    ],
                }
            ),
            connect_factory=self.cf,
        )
        patched = sessions.patch_message_content(
            session["id"],
            stored["id"],
            {"applied": True, "discarded": False, "checked": [True, False]},
            connect_factory=self.cf,
        )
        self.assertTrue(patched["content"]["applied"])
        self.assertFalse(patched["content"]["discarded"])
        self.assertEqual([True, False], patched["content"]["checked"])
        reloaded = sessions.get_session_detail(session["id"], connect_factory=self.cf)
        content = reloaded["messages"][0]["content"]
        self.assertTrue(content["applied"])
        self.assertFalse(content["discarded"])
        self.assertEqual([True, False], content["checked"])
        rejected = sessions.patch_message_content(
            session["id"],
            stored["id"],
            {"applied": False, "discarded": True},
            connect_factory=self.cf,
        )
        self.assertTrue(rejected["content"]["discarded"])
        self.assertFalse(rejected["content"]["applied"])

    def test不存在会话(self) -> None:
        with self.assertRaises(sessions.SessionNotFound):
            sessions.get_session_detail("missing", connect_factory=self.cf)

    def test初始化不破坏既有表(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute("INSERT INTO tags (tag, zh, category) VALUES (?, ?, ?)", ("1girl", "女孩", "2.人物"))
        db.init_db(self.db_path)
        with db.connect(self.db_path) as conn:
            tag = conn.execute("SELECT tag FROM tags WHERE tag='1girl'").fetchone()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertEqual("1girl", tag["tag"])
        self.assertIn("copilot_sessions", tables)
        self.assertIn("copilot_messages", tables)
        self.assertIn("recipes", tables)
        self.assertIn("llm_settings", tables)


class CopilotHistoryAdapterTests(unittest.TestCase):
    def test当前工作区优先于历史(self) -> None:
        stored = [
            {
                "role": "user",
                "content": {
                    "text": "旧指令",
                    "parts": [{"type": "text", "data": {"text": "旧指令"}}],
                },
            },
            {
                "role": "assistant",
                "content": {
                    "text": "旧建议",
                    "parts": [
                        {
                            "type": "diff",
                            "data": {"operations": [{"kind": "add", "target": "positive", "tag": "old tag"}]},
                        }
                    ],
                    "checked": [True],
                    "applied": False,
                },
            },
        ]
        adapted = history.adapt_history_for_llm(stored)
        llm = FakeLLM(dumps(ok_suggestion(summary="新上下文")))
        request = default_request()
        request["history"] = adapted
        request["context"] = {
            "positive": "CURRENT_POS_UNIQUE",
            "negative": "CURRENT_NEG_UNIQUE",
            "recipe": {"charId": 99},
            "enabled_contexts": ["positive", "negative", "recipe"],
        }
        generate_suggestion(
            request,
            base_url="https://example.invalid/v1",
            api_key="test-key",
            model="test-model",
            llm_call=llm,
            tool_registry={},
        )
        messages = llm.calls[0][0][3]
        blob = json.dumps(messages, ensure_ascii=False)
        self.assertIn("CURRENT_POS_UNIQUE", blob)
        self.assertIn("CURRENT_NEG_UNIQUE", blob)
        self.assertIn("旧指令", blob)
        self.assertNotIn("checked", blob)
        self.assertNotIn("content_json", blob)
        last_user = [item for item in messages if item.get("role") == "user"][-1]["content"]
        self.assertIn("CURRENT_POS_UNIQUE", last_user)
        self.assertNotIn("old tag", last_user)

    def test超预算删除最旧(self) -> None:
        stored = []
        for index in range(12):
            stored.append({"role": "user", "content": {"text": f"用户{index}", "parts": []}})
            stored.append({"role": "assistant", "content": {"text": f"助手{index}", "parts": []}})
        adapted = history.adapt_history_for_llm(stored)
        texts = [item["text"] for item in adapted]
        self.assertNotIn("用户0", texts)
        self.assertIn("用户11", texts)
        self.assertEqual(history.SEMANTIC_TURN_LIMIT * 2, len(adapted))

    def test字符预算删除最旧(self) -> None:
        original = history.SEMANTIC_HISTORY_MAX_CHARS
        history.SEMANTIC_HISTORY_MAX_CHARS = 30
        try:
            stored = [
                {"role": "user", "content": {"text": "AAAAAAAAAA", "parts": []}},
                {"role": "assistant", "content": {"text": "BBBBBBBBBB", "parts": []}},
                {"role": "user", "content": {"text": "CCCCCCCCCC", "parts": []}},
                {"role": "assistant", "content": {"text": "DDDDDDDDDD", "parts": []}},
            ]
            adapted = history.adapt_history_for_llm(stored)
            blob = "".join(item["text"] for item in adapted)
            self.assertNotIn("AAAAAAAAAA", blob)
            self.assertTrue(len(blob) <= 30 or "CCCCCCCCCC" in blob)
        finally:
            history.SEMANTIC_HISTORY_MAX_CHARS = original

    def test工具结果只留摘要(self) -> None:
        summary = history.summarize_tool(
            "search_tags",
            {"q": "1girl"},
            json.dumps([{"tag": "1girl", "zh": "女孩"}, {"tag": "solo", "zh": "单人"}], ensure_ascii=False),
        )
        self.assertEqual("ok", summary["status"])
        self.assertIn("2", summary["summary"])
        self.assertNotIn("zh", summary["result_summary"] or "")
        huge = history.summarize_tool(
            "get_character",
            {"name": "测试"},
            json.dumps({"name": "测试", "appearance": "超长外观" * 80, "trigger_words": "tw"}, ensure_ascii=False),
        )
        self.assertNotIn("超长外观", huge["result_summary"])
        self.assertIn("测试", huge["summary"])

    def test禁用上下文仍然生效(self) -> None:
        adapted = history.adapt_history_for_llm([])
        llm = FakeLLM(dumps(ok_suggestion()))
        request = default_request()
        request["history"] = adapted
        request["context"] = {
            "positive": "KEEP_POS",
            "negative": "DROP_NEG",
            "recipe": {"charId": 1},
            "enabled_contexts": ["positive"],
        }
        generate_suggestion(
            request,
            base_url="https://example.invalid/v1",
            api_key="test-key",
            model="test-model",
            llm_call=llm,
            tool_registry={},
        )
        blob = json.dumps(llm.calls[0][0][3], ensure_ascii=False)
        self.assertIn("KEEP_POS", blob)
        self.assertNotIn("DROP_NEG", blob)

    def test不把UI_JSON原样发送(self) -> None:
        stored = [
            {
                "role": "assistant",
                "content": {
                    "text": "摘要",
                    "checked": [True, False],
                    "applied": False,
                    "discarded": False,
                    "suggestion_id": "llm-x",
                    "parts": [
                        {"type": "diagnosis", "data": {"items": [{"level": "info", "message": "可补充动作"}]}},
                        {"type": "diff", "data": {"operations": [{"kind": "add", "tag": "dynamic pose"}]}},
                    ],
                },
            }
        ]
        adapted = history.adapt_history_for_llm(stored)
        blob = json.dumps(adapted, ensure_ascii=False)
        for key in history.UI_ONLY_KEYS:
            self.assertNotIn(key, blob)
        self.assertIn("诊断：", adapted[0]["text"])
        self.assertIn("dynamic pose", adapted[0]["text"])

    def test快照明显不同(self) -> None:
        saved = history.snapshot_from_context({}, {"character": "小怡", "positive_preview": "1girl, garden"})
        current = history.snapshot_from_context({}, {"character": "独角兽", "positive_preview": "1girl, garden"})
        self.assertTrue(history.snapshot_diverged(saved, current))
        self.assertFalse(history.snapshot_diverged(saved, saved))


class CopilotSessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "session-api.sqlite3"
        db.init_db(self.db_path)
        self.connect_patch = mock.patch.object(app_module, "connect", lambda: db.connect(self.db_path))
        self.connect_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def test_crud与无效id(self) -> None:
        created = self.client.post("/api/workshop/copilot/sessions", json={"context_snapshot": {"character": "小怡"}}).json()
        self.assertEqual("新会话", created["title"])
        self.assertEqual("小怡", created["context_snapshot"]["character"])
        listed = self.client.get("/api/workshop/copilot/sessions").json()["sessions"]
        self.assertEqual(1, len(listed))
        detail = self.client.get(f"/api/workshop/copilot/sessions/{created['id']}").json()
        self.assertEqual([], detail["messages"])
        renamed = self.client.patch(
            f"/api/workshop/copilot/sessions/{created['id']}",
            json={"title": "纸箱优化"},
        ).json()
        self.assertEqual("纸箱优化", renamed["title"])
        searched = self.client.get("/api/workshop/copilot/sessions", params={"q": "纸箱"}).json()["sessions"]
        self.assertEqual(1, len(searched))
        missing = self.client.get("/api/workshop/copilot/sessions/not-a-session")
        self.assertEqual(404, missing.status_code)
        self.assertEqual("会话不存在", missing.json()["error"])
        deleted = self.client.delete(f"/api/workshop/copilot/sessions/{created['id']}")
        self.assertEqual(200, deleted.status_code)
        self.assertEqual([], deleted.json()["sessions"])
        again = self.client.delete(f"/api/workshop/copilot/sessions/{created['id']}")
        self.assertEqual(404, again.status_code)

    def test_copilot请求带session_id并落库成功(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE copilot_llm_settings SET base_url=?, api_key=?, model=? WHERE id=1",
                ("https://example.invalid/v1", "test-key", "test-model"),
            )
        created = self.client.post("/api/workshop/copilot/sessions", json={}).json()

        def fake_generate(request, **kwargs):
            self.assertEqual([], request.get("history"))
            return {
                "id": "llm-ok",
                "action": "diagnose",
                "summary": "完成诊断",
                "diagnostics": [{"id": "d-1", "level": "info", "message": "可补充动作", "target": "positive"}],
                "operations": [{"kind": "add", "target": "positive", "tag": "dynamic pose", "reason": "动作"}],
                "stages": [{"label": "解析当前 Prompt"}],
                "tools": [{"name": "search_tags", "status": "ok", "summary": "找到 1 个相关 Tag", "result_summary": "1girl"}],
            }

        body = default_request()
        body["session_id"] = created["id"]
        with mock.patch.object(app_module, "generate_suggestion", side_effect=fake_generate):
            response = self.client.post("/api/workshop/copilot", json=body)
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(created["id"], payload["session_id"])
        detail = self.client.get(f"/api/workshop/copilot/sessions/{created['id']}").json()
        roles = [item["role"] for item in detail["messages"]]
        self.assertEqual(["user", "assistant"], roles)
        assistant = detail["messages"][1]["content"]
        types = [part["type"] for part in assistant["parts"]]
        self.assertIn("diagnosis", types)
        self.assertIn("diff", types)
        self.assertIn("tool", types)
        patched = self.client.patch(
            f"/api/workshop/copilot/sessions/{created['id']}/messages/{detail['messages'][1]['id']}",
            json={"applied": True, "discarded": False, "checked": [True]},
        ).json()
        self.assertTrue(patched["content"]["applied"])
        self.assertEqual([True], patched["content"]["checked"])
        missing_msg = self.client.patch(
            f"/api/workshop/copilot/sessions/{created['id']}/messages/not-a-message",
            json={"applied": True},
        )
        self.assertEqual(404, missing_msg.status_code)
        self.assertEqual("会话不存在", missing_msg.json()["error"])

    def test_ai错误也落库error消息(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE copilot_llm_settings SET base_url=?, api_key=?, model=? WHERE id=1",
                ("https://example.invalid/v1", "test-key", "test-model"),
            )
        created = self.client.post("/api/workshop/copilot/sessions", json={}).json()
        body = default_request()
        body["session_id"] = created["id"]
        with mock.patch.object(
            app_module,
            "generate_suggestion",
            side_effect=app_module.CopilotError("模型超时", status_code=502),
        ):
            response = self.client.post("/api/workshop/copilot", json=body)
        self.assertEqual(502, response.status_code)
        self.assertEqual(created["id"], response.json()["session_id"])
        detail = self.client.get(f"/api/workshop/copilot/sessions/{created['id']}").json()
        self.assertEqual(["user", "error"], [item["role"] for item in detail["messages"]])
        self.assertIn("模型超时", detail["messages"][1]["content"]["text"])

    def test无效session_id不破坏(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE copilot_llm_settings SET base_url=?, api_key=?, model=? WHERE id=1",
                ("https://example.invalid/v1", "test-key", "test-model"),
            )
        body = default_request()
        body["session_id"] = "missing-id"
        with mock.patch.object(app_module, "generate_suggestion", side_effect=AssertionError("不应调用")):
            response = self.client.post("/api/workshop/copilot", json=body)
        self.assertEqual(404, response.status_code)
        self.assertEqual("会话不存在", response.json()["error"])

    def test删除后可列出剩余并作为fallback(self) -> None:
        a = self.client.post("/api/workshop/copilot/sessions", json={"title": "A"}).json()
        b = self.client.post("/api/workshop/copilot/sessions", json={"title": "B"}).json()
        deleted = self.client.delete(f"/api/workshop/copilot/sessions/{b['id']}").json()
        ids = [item["id"] for item in deleted["sessions"]]
        self.assertIn(a["id"], ids)
        self.assertNotIn(b["id"], ids)
        self.assertEqual(a["id"], deleted["sessions"][0]["id"])


if __name__ == "__main__":
    unittest.main()
