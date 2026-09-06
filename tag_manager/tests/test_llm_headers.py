from __future__ import annotations

import json
import unittest
from unittest import mock

from tag_manager import llm


def fake_chat_response() -> mock.MagicMock:
    """构造一条 /chat/completions 的假响应。"""
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "完成"}}]}
    ).encode("utf-8")
    return response


def fake_models_response() -> mock.MagicMock:
    """构造一条 /models 的假响应。"""
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"data": [{"id": "test-model"}]}
    ).encode("utf-8")
    return response


class LlmHeaderTests(unittest.TestCase):
    """验证对外请求带浏览器 UA，穿透 Cloudflare 对 Python-urllib 的 1010 拦截。"""

    def assert_browser_headers(self, request) -> None:
        ua = request.get_header("User-agent")
        self.assertIsNotNone(ua)
        self.assertTrue(ua.startswith("Mozilla/5.0"))
        self.assertIn("Chrome/", ua)
        self.assertNotIn("Python-urllib", ua)
        self.assertEqual("application/json", request.get_header("Accept"))

    def test_post_chat请求带浏览器UA(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=fake_chat_response()) as urlopen:
            llm.chat_completion_messages(
                "https://example.invalid/v1",
                "密钥",
                "模型",
                [{"role": "user", "content": "你好"}],
            )
        request = urlopen.call_args.args[0]
        self.assert_browser_headers(request)

    def test_chat_completion请求带浏览器UA(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=fake_chat_response()) as urlopen:
            llm.chat_completion("https://example.invalid/v1", "密钥", "模型", "系统", "你好")
        request = urlopen.call_args.args[0]
        self.assert_browser_headers(request)

    def test_list_models请求带浏览器UA(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=fake_models_response()) as urlopen:
            models = llm.list_models("https://example.invalid/v1", "密钥")
        self.assertEqual(["test-model"], models)
        request = urlopen.call_args.args[0]
        self.assert_browser_headers(request)


if __name__ == "__main__":
    unittest.main()
