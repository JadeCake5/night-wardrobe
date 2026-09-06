from __future__ import annotations

import urllib.error
import urllib.request
import json

# Cloudflare 等网关按 User-Agent 指纹拦截 Python-urllib（403 error code: 1010），
# 统一伪装成桌面浏览器 UA 穿透，同时声明只接受 JSON 响应。
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _post_chat(base_url: str, api_key: str, payload: dict, timeout: int) -> dict:
    """向 OpenAI 兼容的 /chat/completions 发送 POST，返回解析后的 JSON 对象。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
            "User-Agent": BROWSER_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM 请求失败: {exc.code} {detail}") from exc


def chat_completion(base_url: str, api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    base_url = base_url.rstrip("/")
    if not base_url or not model:
        raise ValueError("请先填写 base_url 和 model")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.7,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
            "User-Agent": BROWSER_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM 请求失败: {exc.code} {detail}") from exc

    return result["choices"][0]["message"]["content"]


def chat_completion_messages(
    base_url: str,
    api_key: str,
    model: str,
    messages: list,
    *,
    temperature: float | None = 0.7,
    top_p: float | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    max_tokens: int | None = 8192,
    response_format: dict | None = None,
    timeout: int = 180,
) -> str:
    """直接透传 messages 数组调用 OpenAI 兼容接口。

    供抽卡后端代理使用：由前端组装好完整的 messages（含 system / 历史 / user），
    后端只负责补上 base_url / model / api_key 并转发。采样参数为 None 时不写入
    payload，以兼容部分不支持这些字段的服务商。
    response_format 仅在非 None 时写入，默认不影响既有调用方。
    """
    base_url = base_url.rstrip("/")
    if not base_url or not model:
        raise ValueError("请先填写 base_url 和 model")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages 不能为空")

    payload: dict = {"model": model, "messages": messages}
    optional = {
        "temperature": temperature,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "max_tokens": max_tokens,
    }
    for key, value in optional.items():
        if value is not None:
            payload[key] = value
    if response_format is not None:
        payload["response_format"] = response_format

    result = _post_chat(base_url, api_key, payload, timeout)
    content = result["choices"][0]["message"].get("content")
    return content if content is not None else ""


def chat_completion_with_tools(
    base_url: str,
    api_key: str,
    model: str,
    messages: list,
    *,
    tools=None,
    tool_choice=None,
    temperature: float | None = 0.7,
    max_tokens: int | None = 8192,
    response_format: dict | None = None,
    timeout: int = 180,
) -> dict:
    """返回完整 choices[0].message dict（调用方自取 content / tool_calls）。

    tools / tool_choice / response_format 仅在非 None 时写入 payload。
    """
    base_url = base_url.rstrip("/")
    if not base_url or not model:
        raise ValueError("请先填写 base_url 和 model")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages 不能为空")

    payload: dict = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if response_format is not None:
        payload["response_format"] = response_format

    result = _post_chat(base_url, api_key, payload, timeout)
    message = result["choices"][0]["message"]
    if isinstance(message, dict):
        return message
    return {"content": "" if message is None else str(message)}


def list_models(base_url: str, api_key: str, timeout: int = 30) -> list[str]:
    """获取 OpenAI 兼容服务商的模型列表，供设置面板选择。"""
    base_url = base_url.rstrip("/")
    if not base_url:
        raise ValueError("请先填写 base_url")
    req = urllib.request.Request(
        f"{base_url}/models",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
            "User-Agent": BROWSER_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"获取模型列表失败: {exc.code} {detail}") from exc

    items = result.get("data", result if isinstance(result, list) else [])
    models = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            models.append(item["id"])
        elif isinstance(item, str):
            models.append(item)
    return models
