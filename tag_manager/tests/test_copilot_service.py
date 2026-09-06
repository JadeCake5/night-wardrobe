from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from tag_manager import app as app_module
from tag_manager import db
from tag_manager.copilot_service import CopilotError, QUOTA_USER_MESSAGE, SYSTEM_PROMPT, generate_suggestion
from tag_manager.copilot_tools import TOOL_RESULT_MAX_CHARS, execute_tool


def response_json(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


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


class FakeLLM:
    """按预定内容序列返回，或抛出预定异常；记录每次调用参数。"""

    def __init__(self, contents=None, error=None) -> None:
        if isinstance(contents, str):
            contents = [contents]
        self.contents = list(contents or [])
        self.error = error
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        if not self.contents:
            return ""
        index = min(len(self.calls) - 1, len(self.contents) - 1)
        return self.contents[index]


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def ok_suggestion(**overrides) -> dict:
    payload = {
        "summary": "完成",
        "diagnostics": [],
        "operations": [],
        "stages": [],
    }
    payload.update(overrides)
    return payload


def tool_call_message(call_id: str, name: str, arguments) -> dict:
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


class FakeToolLLM:
    """返回完整 message dict 序列并记录调用；耗尽后默认给出无 tool_calls 的助手消息。"""

    def __init__(self, messages=None, error=None, *, repeat_last: bool = False) -> None:
        if isinstance(messages, dict):
            messages = [messages]
        self.messages = list(messages or [])
        self.error = error
        self.repeat_last = repeat_last
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        if not self.messages:
            return {"role": "assistant", "content": ""}
        index = len(self.calls) - 1
        if index >= len(self.messages):
            if self.repeat_last:
                return self.messages[-1]
            return {"role": "assistant", "content": ""}
        return self.messages[index]


def recording_execute(store: list):
    def _execute(name, arguments, **kwargs):
        store.append((name, arguments))
        return dumps({"ok": True, "name": name, "keys": sorted(arguments.keys())})

    return _execute


def run_tools(*, tool_llm, llm=None, request=None, tool_registry=None, **kwargs):
    if llm is None:
        llm = FakeLLM(dumps(ok_suggestion()))
    if tool_registry is None:
        tool_registry = recording_execute([])
    params = {
        "base_url": "https://example.invalid/v1",
        "api_key": "test-key",
        "model": "test-model",
        "llm_call": llm,
        "llm_tool_call": tool_llm,
        "tool_registry": tool_registry,
    }
    params.update(kwargs)
    return generate_suggestion(request or default_request(), **params)


class CopilotServiceTests(unittest.TestCase):
    def run_suggest(self, content, request=None, llm=None, **kwargs):
        if llm is None:
            text = content if isinstance(content, str) else dumps(content)
            llm = FakeLLM(text)
        params = {
            "base_url": "https://example.invalid/v1",
            "api_key": "test-key",
            "model": "test-model",
            "llm_call": llm,
            "tool_registry": {},
        }
        params.update(kwargs)
        return generate_suggestion(request or default_request(), **params)

    def test完整响应解析透出(self) -> None:
        payload = {
            "summary": "建议补强人物主体",
            "diagnostics": [
                {
                    "level": "warning",
                    "message": "缺少主体人数",
                    "relatedTag": "1girl",
                    "target": "positive",
                }
            ],
            "operations": [
                {
                    "kind": "add",
                    "target": "positive",
                    "tag": "looking at viewer",
                    "category": "custom",
                    "reason": "明确视线",
                }
            ],
            "stages": [{"label": "解析当前 Prompt", "detail": "Positive 2 段"}],
        }
        result = self.run_suggest(payload)
        self.assertTrue(result["id"].startswith("llm-"))
        self.assertEqual("diagnose", result["action"])
        self.assertEqual("建议补强人物主体", result["summary"])
        self.assertEqual(1, len(result["diagnostics"]))
        diagnostic = result["diagnostics"][0]
        self.assertEqual("warning", diagnostic["level"])
        self.assertEqual("缺少主体人数", diagnostic["message"])
        self.assertEqual("1girl", diagnostic["relatedTag"])
        self.assertEqual("positive", diagnostic["target"])
        self.assertTrue(diagnostic["id"])
        self.assertEqual(payload["operations"], result["operations"])
        self.assertEqual(payload["stages"], result["stages"])

    def test仅诊断无操作也成功(self) -> None:
        payload = {
            "summary": "未发现问题",
            "diagnostics": [{"level": "success", "message": "基础检查通过"}],
            "operations": [],
            "stages": [{"label": "诊断"}],
        }
        result = self.run_suggest(payload)
        self.assertEqual([], result["operations"])
        self.assertEqual("success", result["diagnostics"][0]["level"])
        self.assertEqual("未发现问题", result["summary"])

    def test_add操作校验透出(self) -> None:
        operation = {
            "kind": "add",
            "target": "negative",
            "tag": "worst quality",
            "category": "quality",
            "reason": "补质量负面词",
        }
        result = self.run_suggest(
            {"summary": "补负面", "diagnostics": [], "operations": [operation], "stages": []}
        )
        self.assertEqual(operation, result["operations"][0])

    def test_remove操作校验透出(self) -> None:
        operation = {"kind": "remove", "target": "positive", "tag": "solo", "reason": "与群像冲突"}
        result = self.run_suggest(
            {"summary": "去冲突", "diagnostics": [], "operations": [operation], "stages": []}
        )
        self.assertEqual(operation, result["operations"][0])

    def test_replace操作含from与to(self) -> None:
        operation = {
            "kind": "replace",
            "target": "positive",
            "from": "standing",
            "to": "sitting",
            "reason": "改坐姿",
        }
        result = self.run_suggest(
            {"summary": "换姿势", "diagnostics": [], "operations": [operation], "stages": []}
        )
        self.assertEqual(operation, result["operations"][0])
        self.assertEqual("standing", result["operations"][0]["from"])
        self.assertEqual("sitting", result["operations"][0]["to"])
        self.assertNotIn("from_", result["operations"][0])

    def test畸形JSON会重试两次后失败(self) -> None:
        llm = FakeLLM(["这不是 JSON", "<<<仍然不是>>>"])
        with self.assertRaises(CopilotError) as ctx:
            self.run_suggest("", llm=llm)
        self.assertIn("无法解析", str(ctx.exception))
        self.assertEqual(2, len(llm.calls))

    def test非法operation_kind被拒(self) -> None:
        payload = {
            "summary": "非法 kind",
            "diagnostics": [],
            "operations": [{"kind": "frobnicate", "target": "positive", "tag": "solo"}],
            "stages": [],
        }
        llm = FakeLLM([dumps(payload), dumps(payload)])
        with self.assertRaises(CopilotError):
            self.run_suggest("", llm=llm)

    def test非法target被拒(self) -> None:
        payload = {
            "summary": "非法 target",
            "diagnostics": [],
            "operations": [{"kind": "add", "target": "prompt", "tag": "solo"}],
            "stages": [],
        }
        llm = FakeLLM([dumps(payload), dumps(payload)])
        with self.assertRaises(CopilotError):
            self.run_suggest("", llm=llm)

    def test空tag被拒(self) -> None:
        payload = {
            "summary": "空 tag",
            "diagnostics": [],
            "operations": [{"kind": "add", "target": "positive", "tag": ""}],
            "stages": [],
        }
        llm = FakeLLM([dumps(payload), dumps(payload)])
        with self.assertRaises(CopilotError):
            self.run_suggest("", llm=llm)

    def test_provider超时包成CopilotError(self) -> None:
        llm = FakeLLM(error=TimeoutError("timed out"))
        with self.assertRaises(CopilotError) as ctx:
            self.run_suggest("", llm=llm)
        self.assertIn("timed out", str(ctx.exception))

        llm_url = FakeLLM(error=URLError("timed out"))
        with self.assertRaises(CopilotError):
            self.run_suggest("", llm=llm_url)

    def test_provider错误脱敏密钥(self) -> None:
        secret = "sk-SECRET-KEY-12345"
        llm = FakeLLM(error=RuntimeError(f"LLM 请求失败: 500 {secret} boom"))
        with self.assertRaises(CopilotError) as ctx:
            self.run_suggest("", llm=llm, api_key=secret)
        message = str(ctx.exception)
        self.assertNotIn(secret, message)
        self.assertIn("***", message)

    def test权重段roundtrip不被拆分(self) -> None:
        payload = {
            "summary": "删除画师权重段",
            "diagnostics": [],
            "operations": [{"kind": "remove", "target": "positive", "tag": "(artist:0.85)"}],
            "stages": [],
        }
        result = self.run_suggest(payload)
        self.assertEqual("(artist:0.85)", result["operations"][0]["tag"])
        dumped = json.dumps(result, ensure_ascii=False)
        self.assertIn("(artist:0.85)", dumped)
        self.assertNotEqual("artist", result["operations"][0]["tag"])
        self.assertNotEqual("0.85", result["operations"][0]["tag"])

    def test未启用的上下文不送入messages(self) -> None:
        unique_negative = "UNIQUE_NEG_TAG_xyz_should_not_appear"
        llm = FakeLLM(dumps({
            "summary": "只看正面",
            "diagnostics": [],
            "operations": [],
            "stages": [],
        }))
        request = default_request()
        request["context"] = {
            "positive": "1girl, sitting",
            "negative": unique_negative,
            "recipe": {"charId": 9},
            "enabled_contexts": ["positive"],
        }
        self.run_suggest("", request=request, llm=llm)
        blob = json.dumps(llm.calls[0][0][3], ensure_ascii=False)
        self.assertNotIn(unique_negative, blob)
        self.assertIn("1girl, sitting", blob)

    def test_recipe上下文序列化进user块(self) -> None:
        llm = FakeLLM(dumps({
            "summary": "读取配方",
            "diagnostics": [],
            "operations": [],
            "stages": [],
        }))
        request = default_request()
        request["context"] = {
            "positive": "should_not_enter",
            "negative": "also_should_not_enter",
            "recipe": {"charId": 1, "outfitId": 2, "artistId": 3, "sceneId": 4, "negativeId": 5},
            "enabled_contexts": ["recipe"],
        }
        self.run_suggest("", request=request, llm=llm)
        user_block = llm.calls[0][0][3][-1]["content"]
        self.assertIn("角色ID=1", user_block)
        self.assertIn("服装ID=2", user_block)
        self.assertIn("画师ID=3", user_block)
        self.assertIn("场景ID=4", user_block)
        self.assertIn("负面ID=5", user_block)
        self.assertNotIn("should_not_enter", user_block)
        self.assertNotIn("also_should_not_enter", user_block)


class CopilotEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "copilot-test.sqlite3"
        db.init_db(self.db_path)
        self.connect_patch = mock.patch.object(app_module, "connect", lambda: db.connect(self.db_path))
        self.connect_patch.start()

    def tearDown(self) -> None:
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def test缺LLM配置端点返回400(self) -> None:
        with mock.patch.object(app_module, "generate_suggestion", side_effect=AssertionError("不应调用 LLM")):
            response = app_module.api_workshop_copilot(default_request())
        self.assertEqual(400, response.status_code)
        payload = response_json(response)
        self.assertEqual("LLM 未配置，请先在工坊助手设置中填写 API", payload["error"])
        self.assertTrue(payload.get("session_id"))

    def test端点use_tools为false时禁用工具(self) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE copilot_llm_settings SET base_url=?, api_key=?, model=? WHERE id=1",
                ("https://example.invalid/v1", "test-key", "test-model"),
            )
        captured = {}

        def fake_generate(request, **kwargs):
            captured.update(kwargs)
            return {
                "id": "llm-test",
                "action": "diagnose",
                "summary": "ok",
                "diagnostics": [],
                "operations": [],
                "stages": [],
            }

        body = default_request()
        body["use_tools"] = False
        with mock.patch.object(app_module, "generate_suggestion", side_effect=fake_generate):
            response = app_module.api_workshop_copilot(body)
        self.assertEqual(200, response.status_code)
        self.assertEqual({}, captured.get("tool_registry"))
        self.assertTrue(response_json(response).get("session_id"))


class CopilotToolLoopTests(unittest.TestCase):
    def test单轮工具调用后产出终局JSON(self) -> None:
        executed: list = []
        tool_llm = FakeToolLLM([tool_call_message("call_1", "search_tags", {"q": "1girl"})])
        llm = FakeLLM(dumps(ok_suggestion(summary="单轮完成")))
        result = run_tools(tool_llm=tool_llm, llm=llm, tool_registry=recording_execute(executed))
        self.assertEqual("单轮完成", result["summary"])
        self.assertEqual(1, len(executed))
        self.assertEqual("search_tags", executed[0][0])
        final_messages = llm.calls[0][0][3]
        self.assertTrue(any(item.get("role") == "tool" for item in final_messages))
        self.assertEqual({"type": "json_object"}, llm.calls[0][1]["response_format"])
        self.assertNotIn("response_format", tool_llm.calls[0][1])
        blob = json.dumps(final_messages, ensure_ascii=False)
        self.assertNotIn("test-key", blob)

    def test多轮循环messages顺序(self) -> None:
        tool_llm = FakeToolLLM(
            [
                tool_call_message("call_a", "search_tags", {"q": "1girl"}),
                tool_call_message("call_b", "list_characters", {}),
            ]
        )
        llm = FakeLLM(dumps(ok_suggestion()))
        run_tools(tool_llm=tool_llm, llm=llm, tool_registry=recording_execute([]))
        sequence = []
        for item in llm.calls[0][0][3]:
            if item.get("role") == "assistant" and item.get("tool_calls"):
                sequence.append("assistant(tool_calls)")
            elif item.get("role") == "tool":
                sequence.append("tool")
        self.assertEqual(
            ["assistant(tool_calls)", "tool", "assistant(tool_calls)", "tool"],
            sequence,
        )

    def test工具结果回灌内容对应tool_call_id(self) -> None:
        def fake_execute(name, arguments, **kwargs):
            return dumps({"echo": name, "q": arguments.get("q")})

        tool_llm = FakeToolLLM([tool_call_message("call_xyz", "search_tags", {"q": "solo"})])
        llm = FakeLLM(dumps(ok_suggestion()))
        run_tools(tool_llm=tool_llm, llm=llm, tool_registry=fake_execute)
        tool_msgs = [item for item in llm.calls[0][0][3] if item.get("role") == "tool"]
        self.assertEqual(1, len(tool_msgs))
        self.assertEqual("call_xyz", tool_msgs[0]["tool_call_id"])
        payload = json.loads(tool_msgs[0]["content"])
        self.assertEqual("search_tags", payload["echo"])
        self.assertEqual("solo", payload["q"])

    def test未知工具名error回灌后循环继续成功(self) -> None:
        tool_llm = FakeToolLLM(
            [
                tool_call_message("call_bad", "not_a_real_tool", {"q": "x"}),
                tool_call_message("call_ok", "search_tags", {"q": "1girl"}),
            ]
        )
        llm = FakeLLM(dumps(ok_suggestion(summary="未知工具已恢复")))
        result = run_tools(tool_llm=tool_llm, llm=llm, tool_registry=execute_tool)
        self.assertEqual("未知工具已恢复", result["summary"])
        tool_msgs = [item for item in llm.calls[0][0][3] if item.get("role") == "tool"]
        self.assertEqual(2, len(tool_msgs))
        first = json.loads(tool_msgs[0]["content"])
        self.assertIn("error", first)
        self.assertIn("not_a_real_tool", first["error"])

    def test非法JSON参数error回灌不中断(self) -> None:
        tool_llm = FakeToolLLM(
            [
                tool_call_message("call_bad", "search_tags", "{not json"),
                tool_call_message("call_ok", "search_tags", {"q": "1girl"}),
            ]
        )
        llm = FakeLLM(dumps(ok_suggestion(summary="参数已纠正")))
        result = run_tools(tool_llm=tool_llm, llm=llm, tool_registry=recording_execute([]))
        self.assertEqual("参数已纠正", result["summary"])
        first = [item for item in llm.calls[0][0][3] if item.get("role") == "tool"][0]
        payload = json.loads(first["content"])
        self.assertIn("error", payload)
        self.assertIn("search_tags", payload["error"])
        self.assertNotIn("{not json", payload["error"])

    def test额度用尽后追加提示并走终局(self) -> None:
        tool_llm = FakeToolLLM(
            [tool_call_message("call_loop", "search_tags", {"q": "loop"})],
            repeat_last=True,
        )
        llm = FakeLLM(dumps(ok_suggestion(summary="额度后终局")))
        result = run_tools(
            tool_llm=tool_llm,
            llm=llm,
            tool_registry=recording_execute([]),
            max_tool_rounds=2,
        )
        self.assertEqual("额度后终局", result["summary"])
        self.assertEqual(2, len(tool_llm.calls))
        self.assertEqual(1, len(llm.calls))
        contents = [item.get("content") for item in llm.calls[0][0][3] if item.get("role") == "user"]
        self.assertIn(QUOTA_USER_MESSAGE, contents)

    def test服务商不支持tools时静态降级成功(self) -> None:
        tool_llm = FakeToolLLM(
            error=RuntimeError("LLM 请求失败: 400 ...tools not supported..."),
        )
        llm = FakeLLM(dumps(ok_suggestion(summary="已降级")))
        result = run_tools(tool_llm=tool_llm, llm=llm, tool_registry=recording_execute([]))
        self.assertEqual("已降级", result["summary"])
        self.assertEqual(1, len(tool_llm.calls))
        self.assertEqual(1, len(llm.calls))
        messages = llm.calls[0][0][3]
        self.assertEqual(SYSTEM_PROMPT, messages[0]["content"])
        self.assertTrue(any("静态资料目录" in str(item.get("content") or "") for item in messages))

    def test不支持tools的400含密钥且终局失败仍脱敏(self) -> None:
        secret = "sk-SECRET-KEY-12345"
        tool_llm = FakeToolLLM(
            error=RuntimeError(f"LLM 请求失败: 400 {secret} tools not supported"),
        )
        llm = FakeLLM(error=RuntimeError(f"LLM 请求失败: 500 {secret} boom"))
        with self.assertRaises(CopilotError) as ctx:
            run_tools(tool_llm=tool_llm, llm=llm, api_key=secret, tool_registry=recording_execute([]))
        message = str(ctx.exception)
        self.assertNotIn(secret, message)
        self.assertIn("***", message)

    def test工具循环后终局畸形会纠正重试(self) -> None:
        tool_llm = FakeToolLLM([tool_call_message("call_1", "search_tags", {"q": "1girl"})])
        llm = FakeLLM(["这不是 JSON", dumps(ok_suggestion(summary="重试成功"))])
        result = run_tools(tool_llm=tool_llm, llm=llm, tool_registry=recording_execute([]))
        self.assertEqual("重试成功", result["summary"])
        self.assertEqual(2, len(llm.calls))

    def test真execute_tool对临时sqlite只读查询(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "copilot-tools.sqlite3"
        db.init_db(db_path)

        def factory():
            return db.connect(db_path)

        with db.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO tags (tag, zh, category, subcategory, rating) VALUES (?, ?, ?, ?, ?)",
                ("1girl", "1个女孩", "2.人物", "人数", 5),
            )
            conn.execute(
                "INSERT INTO tags (tag, zh, category, subcategory, rating) VALUES (?, ?, ?, ?, ?)",
                ("school uniform", "校服", "3.服饰", "制服", 3),
            )
            char_id = conn.execute(
                "INSERT INTO characters (name, lora, trigger_words, appearance) VALUES (?, ?, ?, ?)",
                ("测试角色", "test.safetensors", "trigger", "不应出现在摘要"),
            ).lastrowid
            conn.execute(
                "INSERT INTO character_outfits (character_id, name, tags) VALUES (?, ?, ?)",
                (char_id, "校服", "school uniform"),
            )
            conn.execute(
                "INSERT INTO recipes (name, type, positive_prompt, negative_prompt, notes) VALUES (?, ?, ?, ?, ?)",
                ("森林场景", "scene", "forest, trees", "lowres", "备注"),
            )
            for index in range(40):
                conn.execute(
                    "INSERT INTO tags (tag, zh, category, subcategory, rating) VALUES (?, ?, ?, ?, ?)",
                    (f"longtag_{index}_" + ("x" * 200), "长标签", "手工添加", "", 1),
                )

        filtered = json.loads(
            execute_tool(
                "search_tags",
                {"q": "1girl", "category": "2.人物", "limit": 10},
                connect_factory=factory,
            )
        )
        self.assertEqual(["1girl"], [item["tag"] for item in filtered])

        card = json.loads(execute_tool("get_character", {"name": "测试角色"}, connect_factory=factory))
        self.assertEqual("测试角色", card["name"])
        self.assertEqual(1, len(card["outfits"]))
        self.assertEqual("校服", card["outfits"][0]["name"])
        self.assertIn("appearance", card)

        recipe = json.loads(execute_tool("get_recipe", {"name": "森林场景"}, connect_factory=factory))
        self.assertIn("forest", recipe["positive_prompt"])

        lookup = json.loads(
            execute_tool("lookup_tags", {"tags": ["1girl", "not_exist"]}, connect_factory=factory)
        )
        self.assertEqual(["not_exist"], lookup["missing"])
        self.assertEqual("1girl", lookup["items"][0]["tag"])

        chars = json.loads(execute_tool("list_characters", {}, connect_factory=factory))
        self.assertNotIn("appearance", chars[0])

        truncated = execute_tool(
            "search_tags",
            {"q": "longtag", "limit": 30},
            connect_factory=factory,
        )
        self.assertIn("已截断", truncated)
        self.assertIn("共", truncated)
        self.assertLessEqual(len(truncated) - 40, TOOL_RESULT_MAX_CHARS + 40)


if __name__ == "__main__":
    unittest.main()
