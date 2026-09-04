"""Copilot UI 历史 → LLM 语义历史适配层。

UI 可展示完整 Session；发送给模型的只是裁剪后的语义 turns。
当前 Workshop Context 由 copilot_service 另行注入，不走本模块删除。
"""

from __future__ import annotations

import json
from typing import Any

from .copilot_sessions import normalize_snapshot

SEMANTIC_TURN_LIMIT = 8
SEMANTIC_HISTORY_MAX_CHARS = 8000
TOOL_SUMMARY_MAX_CHARS = 160
DIAGNOSIS_LIMIT = 4
OPERATION_LIMIT = 6
PREVIEW_POSITIVE_LEN = 160
PREVIEW_NEGATIVE_LEN = 120
IDENTITY_KEYS = ("character", "outfit", "artist", "scene", "negative_template")


def preview_text(text: Any, limit: int) -> str:
    cleaned = re_sub_ws("" if text is None else str(text))
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit]


def re_sub_ws(text: str) -> str:
    return " ".join((text or "").split())


def snapshot_from_context(context: dict | None, extra: dict | None = None) -> dict:
    ctx = context if isinstance(context, dict) else {}
    extra = extra if isinstance(extra, dict) else {}
    recipe = ctx.get("recipe") if isinstance(ctx.get("recipe"), dict) else {}
    built = {
        "character": extra.get("character") or _recipe_label(recipe, "charId"),
        "outfit": extra.get("outfit") or _recipe_label(recipe, "outfitId"),
        "artist": extra.get("artist") or _recipe_label(recipe, "artistId"),
        "scene": extra.get("scene") or _recipe_label(recipe, "sceneId"),
        "negative_template": extra.get("negative_template") or _recipe_label(recipe, "negativeId"),
        "positive_preview": extra.get("positive_preview")
        or preview_text(ctx.get("positive"), PREVIEW_POSITIVE_LEN),
        "negative_preview": extra.get("negative_preview")
        or preview_text(ctx.get("negative"), PREVIEW_NEGATIVE_LEN),
    }
    return normalize_snapshot(built)


def _recipe_label(recipe: dict, key: str) -> str:
    value = recipe.get(key)
    if value is None or value == "":
        return ""
    return str(value)


def snapshot_diverged(saved: Any, current: Any) -> bool:
    """当前工作区与会话创建快照是否明显不同。"""
    old = normalize_snapshot(saved)
    new = normalize_snapshot(current)
    for key in IDENTITY_KEYS:
        if (old.get(key) or "").strip() != (new.get(key) or "").strip():
            return True
    for key in ("positive_preview", "negative_preview"):
        a = re_sub_ws(old.get(key) or "").replace(" ", "")[:80]
        b = re_sub_ws(new.get(key) or "").replace(" ", "")[:80]
        if a and b and a != b:
            return True
    return False


def build_user_content(
    *,
    text: str,
    action: str = "",
    contexts: list[str] | None = None,
    created_at: str = "",
    message_id: str = "",
) -> dict:
    body = text or ""
    return {
        "id": message_id,
        "role": "user",
        "text": body,
        "created_at": created_at,
        "action": action,
        "contexts": list(contexts or []),
        "parts": [{"type": "text", "data": {"text": body}}],
    }


def build_assistant_content(
    suggestion: dict,
    *,
    tools: list[dict] | None = None,
    created_at: str = "",
    message_id: str = "",
) -> dict:
    suggestion = suggestion if isinstance(suggestion, dict) else {}
    text = str(suggestion.get("summary") or "")
    parts: list[dict] = []
    if text:
        parts.append({"type": "text", "data": {"text": text}})
    stages = suggestion.get("stages") if isinstance(suggestion.get("stages"), list) else []
    if stages:
        parts.append({"type": "execution", "data": {"stages": stages}})
    diagnostics = suggestion.get("diagnostics") if isinstance(suggestion.get("diagnostics"), list) else []
    if diagnostics:
        parts.append({"type": "diagnosis", "data": {"items": diagnostics}})
    operations = suggestion.get("operations") if isinstance(suggestion.get("operations"), list) else []
    if operations:
        parts.append({"type": "diff", "data": {"operations": operations}})
    tool_items = tools if isinstance(tools, list) else suggestion.get("tools")
    if isinstance(tool_items, list):
        for item in tool_items:
            if not isinstance(item, dict):
                continue
            parts.append(
                {
                    "type": "tool",
                    "data": {
                        "name": str(item.get("name") or ""),
                        "status": str(item.get("status") or "ok"),
                        "summary": str(item.get("summary") or ""),
                        "result_summary": str(item.get("result_summary") or "")[:TOOL_SUMMARY_MAX_CHARS],
                    },
                }
            )
    checked = [True] * len(operations) if operations else []
    return {
        "id": message_id or str(suggestion.get("id") or ""),
        "role": "assistant",
        "text": text,
        "created_at": created_at,
        "action": suggestion.get("action") or "",
        "suggestion_id": suggestion.get("id") or "",
        "applied": False,
        "discarded": False,
        "checked": checked,
        "parts": parts,
    }


def build_error_content(*, message: str, created_at: str = "", message_id: str = "") -> dict:
    text = message or "请求失败"
    return {
        "id": message_id,
        "role": "error",
        "text": text,
        "created_at": created_at,
        "parts": [{"type": "error", "data": {"message": text}}],
    }


def summarize_tool(name: str, arguments: dict | None, result: str) -> dict:
    """只保留可展示摘要，禁止完整查询结果 / hidden reasoning。"""
    name = name or ""
    status = "ok"
    summary = name
    result_summary = ""
    data = _parse_json(result)
    if isinstance(data, dict) and data.get("error"):
        status = "error"
        summary = f"{name} 失败" if name else "工具失败"
        result_summary = str(data.get("error"))[:TOOL_SUMMARY_MAX_CHARS]
    elif name == "search_tags":
        items = data if isinstance(data, list) else []
        summary = f"找到 {len(items)} 个相关 Tag"
        tags = [str(item.get("tag") or "") for item in items[:5] if isinstance(item, dict)]
        result_summary = "、".join(tag for tag in tags if tag)[:TOOL_SUMMARY_MAX_CHARS]
    elif name == "lookup_tags":
        payload = data if isinstance(data, dict) else {}
        hit = len(payload.get("items") or [])
        missing = len(payload.get("missing") or [])
        summary = f"命中 {hit} 个，缺失 {missing} 个"
    elif name == "list_tag_categories":
        items = data if isinstance(data, list) else []
        summary = f"列出 {len(items)} 个分类"
    elif name == "list_characters":
        items = data if isinstance(data, list) else []
        summary = f"列出 {len(items)} 个角色"
    elif name == "list_recipes":
        items = data if isinstance(data, list) else []
        summary = f"列出 {len(items)} 个配方"
    elif name == "get_character":
        payload = data if isinstance(data, dict) else {}
        label = payload.get("name") or ""
        summary = f"读取角色 {label}".strip()
        result_summary = str(payload.get("trigger_words") or "")[:TOOL_SUMMARY_MAX_CHARS]
    elif name == "get_recipe":
        payload = data if isinstance(data, dict) else {}
        label = payload.get("name") or ""
        summary = f"读取配方 {label}".strip()
        result_summary = str(payload.get("type") or "")[:TOOL_SUMMARY_MAX_CHARS]
    else:
        summary = f"已调用 {name}" if name else "已调用工具"
        if isinstance(data, dict):
            result_summary = str(data.get("summary") or data.get("message") or "")[:TOOL_SUMMARY_MAX_CHARS]
        elif isinstance(result, str):
            result_summary = result[:TOOL_SUMMARY_MAX_CHARS]
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "result_summary": result_summary,
    }


def adapt_history_for_llm(messages: list[dict] | None) -> list[dict]:
    """把持久化 UI 消息裁成 {role, text} 语义历史。超预算删最旧 turn。"""
    turns = _semantic_turns(messages or [])
    turns = turns[-SEMANTIC_TURN_LIMIT:]
    while len(turns) > 1 and _turns_chars(turns) > SEMANTIC_HISTORY_MAX_CHARS:
        turns = turns[1:]
    if turns and _turns_chars(turns) > SEMANTIC_HISTORY_MAX_CHARS:
        turns = turns[-1:]
        if _turns_chars(turns) > SEMANTIC_HISTORY_MAX_CHARS:
            turns = [_trim_turn(turns[0], SEMANTIC_HISTORY_MAX_CHARS)]
    out: list[dict] = []
    for turn in turns:
        out.extend(turn)
    return out


def _semantic_turns(messages: list[dict]) -> list[list[dict]]:
    turns: list[list[dict]] = []
    current: list[dict] = []
    for item in messages:
        mapped = _map_message(item)
        if mapped is None:
            continue
        if mapped["role"] == "user":
            if current:
                turns.append(current)
            current = [mapped]
        else:
            if not current:
                current = [mapped]
            else:
                current.append(mapped)
    if current:
        turns.append(current)
    return turns


def _map_message(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    role = item.get("role")
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    text = _semantic_text(role, content)
    if not text.strip():
        return None
    llm_role = "user" if role == "user" else "assistant"
    return {"role": llm_role, "text": text}


def _semantic_text(role: Any, content: dict) -> str:
    if role == "user":
        return str(content.get("text") or "").strip()
    if role == "error":
        message = str(content.get("text") or "").strip()
        return f"上次请求失败：{message}" if message else "上次请求失败"
    chunks: list[str] = []
    summary = str(content.get("text") or "").strip()
    if summary:
        chunks.append(summary)
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        data = part.get("data") if isinstance(part.get("data"), dict) else {}
        if kind == "diagnosis":
            items = data.get("items") if isinstance(data.get("items"), list) else []
            notes = [
                str(item.get("message") or "").strip()
                for item in items[:DIAGNOSIS_LIMIT]
                if isinstance(item, dict)
            ]
            notes = [note for note in notes if note]
            if notes:
                chunks.append("诊断：" + "；".join(notes))
        elif kind == "diff":
            ops = data.get("operations") if isinstance(data.get("operations"), list) else []
            descs = [_op_desc(op) for op in ops[:OPERATION_LIMIT] if isinstance(op, dict)]
            descs = [item for item in descs if item]
            if descs:
                chunks.append("建议修改：" + "，".join(descs))
        elif kind == "tool":
            label = str(data.get("summary") or data.get("name") or "").strip()
            if label:
                chunks.append("工具：" + label)
        elif kind == "error":
            message = str(data.get("message") or "").strip()
            if message and message not in summary:
                chunks.append("错误：" + message)
    if not chunks:
        return ""
    # 去重相邻相同摘要（text part 与 summary 重复）
    unique: list[str] = []
    for chunk in chunks:
        if not unique or unique[-1] != chunk:
            unique.append(chunk)
    return "\n".join(unique)


def _op_desc(op: dict) -> str:
    kind = op.get("kind")
    if kind == "add":
        tag = str(op.get("tag") or "").strip()
        return f"+{tag}" if tag else ""
    if kind == "remove":
        tag = str(op.get("tag") or "").strip()
        return f"-{tag}" if tag else ""
    if kind == "replace":
        src = str(op.get("from") or "").strip()
        dst = str(op.get("to") or "").strip()
        if src or dst:
            return f"{src}→{dst}"
    return ""


def _turns_chars(turns: list[list[dict]]) -> int:
    total = 0
    for turn in turns:
        for item in turn:
            total += len(item.get("text") or "")
    return total


def _trim_turn(turn: list[dict], limit: int) -> list[dict]:
    trimmed: list[dict] = []
    used = 0
    for item in turn:
        text = item.get("text") or ""
        remain = limit - used
        if remain <= 0:
            break
        if len(text) > remain:
            text = text[:remain]
        trimmed.append({"role": item["role"], "text": text})
        used += len(text)
    return trimmed


def _parse_json(raw: Any):
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# 供测试断言：这些键不得出现在送给 LLM 的语义文本中
UI_ONLY_KEYS = (
    "parts",
    "checked",
    "applied",
    "discarded",
    "content_json",
    "suggestion_id",
    "context_snapshot_json",
)
