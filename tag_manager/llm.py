from __future__ import annotations

import urllib.error
import urllib.request
import json


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
            "Authorization": f"Bearer {api_key}" if api_key else "",
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
