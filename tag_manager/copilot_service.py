"""工坊 Copilot 结构化建议服务。

接收工坊上下文与动作指令，经现有 LLM 瘦客户端产出可逐条确认的
诊断与 Prompt 修改建议。LLM 调用通过 llm_call 注入，便于零联网测试。
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .llm import chat_completion_messages

VALID_ACTIONS = (
    "diagnose",
    "reduce_conflicts",
    "dedupe",
    "improve_pose",
    "improve_composition",
    "enrich_environment",
    "optimize_negative",
    "freeform",
)
ENABLED_CONTEXT_KEYS = ("positive", "negative", "recipe")
MSG_NO_CONTEXT = "未选择上下文，请至少开启 Positive / Negative / Recipe 中的一项"
MSG_PARSE_FAILED = "AI 返回的结果无法解析为结构化建议"
FREEFORM_FALLBACK = "请根据当前上下文改写并优化 Prompt，给出结构化修改建议。"
RETRY_USER_MESSAGE = "上次输出无法解析为规定 JSON，请仅返回符合 schema 的 JSON，不要任何多余文本。"

ACTION_PRESETS: dict[str, str] = {
    "diagnose": "分析冲突/冗余/影响生成的问题并给结构化修改建议",
    "reduce_conflicts": "找出并化解语义冲突",
    "dedupe": "移除重复整段",
    "improve_pose": "优化人物动作表现",
    "improve_composition": "优化构图",
    "enrich_environment": "补充环境/背景细节",
    "optimize_negative": "补全常用质量负面词",
}

ACTION_LABELS: dict[str, str] = {
    "diagnose": "诊断 Prompt",
    "reduce_conflicts": "减少冲突",
    "dedupe": "清理重复",
    "improve_pose": "优化动作",
    "improve_composition": "优化构图",
    "enrich_environment": "补充环境细节",
    "optimize_negative": "优化 Negative",
    "freeform": "自定义指令",
}

RECIPE_LABELS = {
    "charId": "角色ID",
    "outfitId": "服装ID",
    "artistId": "画师ID",
    "sceneId": "场景ID",
    "negativeId": "负面ID",
}

SYSTEM_PROMPT = """你是面向 Stable Diffusion / NoobAI 的 Prompt 工程助手，只输出结构化修改建议，绝不直接改写用户的工作区。

规则：
1. Prompt 是「逗号分隔的 tag」结构。权重段如 (artist:0.85)、((tag))、<lora:name:1> 是原子结构，不可拆分；不得把 (artist:0.85) 拆成 artist 和 0.85。
2. Recipe 中的角色 / 画师 / 场景有来源意义：不可随意改角色身份，不可随意删除 artist tag。
3. 只提建议，绝不自动改。operations 必须精确、可被「整段精确匹配」执行：add 的 tag 是完整段；remove / replace 的 tag / from 必须与现有某个完整段逐字相同。
4. 输出必须是严格 JSON，不带 markdown 围栏（不要使用 ```json），不输出思维过程、chain-of-thought 或任何解释性前后文。

JSON 形状（字段名必须一致，不要多余字段）：
{
  "summary": "一句话总结",
  "diagnostics": [{"level":"success|info|warning|error","message":"...","relatedTag":"可选","target":"positive|negative"}],
  "operations": [
    {"kind":"add","target":"positive|negative","tag":"...","category":"可选","reason":"可选"},
    {"kind":"remove","target":"positive|negative","tag":"...","reason":"可选"},
    {"kind":"replace","target":"positive|negative","from":"...","to":"...","reason":"可选"}
  ],
  "stages": [{"label":"...","detail":"可选"}]
}
只允许 kind=add|remove|replace，target=positive|negative，level=success|info|warning|error。
"""

TOOLS_ADDENDUM = """
你可以使用工具查询本应用的 tag 库、角色卡与配方。
add / remove / replace 所涉及的 tag 优先采用库中真实存在的条目。
工具额度有限，查完所需资料后立即产出最终 JSON，不要继续空转工具。
不要输出思维过程、chain-of-thought 或任何解释性前后文。
"""

QUOTA_USER_MESSAGE = "工具额度已用完，请直接给出最终 JSON"
_UNSUPPORT_STATUSES = ("400", "404", "422")
_UNSUPPORT_HINTS = ("tool", "function", "does not support")


class CopilotError(Exception):
    """工坊 Copilot 可展示错误；message 已脱敏，status_code 供端点映射 HTTP 状态。"""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _reject_blank(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} 不能为空")
    return value


class AddOperation(_StrictModel):
    kind: Literal["add"]
    target: Literal["positive", "negative"]
    tag: str = Field(min_length=1)
    category: str | None = None
    reason: str | None = None

    @field_validator("tag")
    @classmethod
    def tag_not_blank(cls, value: str) -> str:
        return _reject_blank(value, "tag")


class RemoveOperation(_StrictModel):
    kind: Literal["remove"]
    target: Literal["positive", "negative"]
    tag: str = Field(min_length=1)
    reason: str | None = None

    @field_validator("tag")
    @classmethod
    def tag_not_blank(cls, value: str) -> str:
        return _reject_blank(value, "tag")


class ReplaceOperation(_StrictModel):
    kind: Literal["replace"]
    target: Literal["positive", "negative"]
    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)
    reason: str | None = None

    @field_validator("from_", "to")
    @classmethod
    def ends_not_blank(cls, value: str) -> str:
        return _reject_blank(value, "from/to")


Operation = Annotated[
    AddOperation | RemoveOperation | ReplaceOperation,
    Field(discriminator="kind"),
]


class Diagnostic(_StrictModel):
    level: Literal["success", "info", "warning", "error"]
    message: str = Field(min_length=1)
    relatedTag: str | None = None
    target: Literal["positive", "negative"] | None = None
    id: str | None = None


class Stage(_StrictModel):
    label: str = Field(min_length=1)
    detail: str | None = None


class Suggestion(_StrictModel):
    summary: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    stages: list[Stage] = Field(default_factory=list)


def generate_suggestion(
    request: dict,
    *,
    base_url: str,
    api_key: str,
    model: str,
    llm_call=chat_completion_messages,
    llm_tool_call=None,
    tool_registry=None,
    max_tool_rounds: int = 5,
) -> dict:
    """根据工坊上下文生成结构化建议。失败抛 CopilotError（message 已脱敏）。

    llm_tool_call 为 None 时延迟绑定 chat_completion_with_tools。
    tool_registry 为 None 时使用 copilot_tools.execute_tool；传 {} 则禁用工具循环。
    """
    action, context, enabled, instruction, history = _validate_request(request)
    user_content = _build_user_content(action, instruction, context, enabled)
    tools_enabled = tool_registry != {}
    system_prompt = SYSTEM_PROMPT + TOOLS_ADDENDUM if tools_enabled else SYSTEM_PROMPT
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    tool_summaries: list[dict] = []

    if tools_enabled:
        if llm_tool_call is None:
            from .llm import chat_completion_with_tools as llm_tool_call
        executor = _resolve_executor(tool_registry)
        try:
            tool_summaries = _tool_loop(
                messages,
                llm_tool_call=llm_tool_call,
                executor=executor,
                base_url=base_url,
                api_key=api_key,
                model=model,
                max_tool_rounds=max_tool_rounds,
            )
        except CopilotError:
            raise
        except Exception as exc:
            if _is_tools_unsupported(exc):
                messages[:] = _fallback_messages(history, user_content)
                tool_summaries = []
            else:
                raise CopilotError(_redact_secret(str(exc), api_key)) from exc

    content = _invoke_llm(llm_call, base_url, api_key, model, messages)
    try:
        payload = _parse_and_validate(content)
        return _finalize(payload, action, tool_summaries)
    except (ValueError, TypeError, json.JSONDecodeError):
        retry_messages = list(messages) + [{"role": "user", "content": RETRY_USER_MESSAGE}]
        content = _invoke_llm(llm_call, base_url, api_key, model, retry_messages)
        try:
            payload = _parse_and_validate(content)
            return _finalize(payload, action, tool_summaries)
        except (ValueError, TypeError, json.JSONDecodeError):
            raise CopilotError(MSG_PARSE_FAILED) from None


def user_visible_text(action: str, instruction: str = "") -> str:
    """落库与 UI 展示用的用户可见文本，不包含完整 Workshop Prompt。"""
    if action == "freeform":
        text = (instruction or "").strip()
        return text or ACTION_LABELS["freeform"]
    return ACTION_LABELS.get(action, action or ACTION_LABELS["freeform"])


def _validate_request(request: dict) -> tuple[str, dict, list[str], str, list[dict]]:
    if not isinstance(request, dict):
        raise CopilotError("请求格式无效", status_code=400)
    action = str(request.get("action") or "").strip()
    if action not in VALID_ACTIONS:
        raise CopilotError("未知的 Copilot 动作", status_code=400)
    context = request.get("context") if isinstance(request.get("context"), dict) else {}
    raw_enabled = context.get("enabled_contexts")
    if not isinstance(raw_enabled, list):
        raw_enabled = []
    enabled = [item for item in raw_enabled if item in ENABLED_CONTEXT_KEYS]
    if not enabled:
        raise CopilotError(MSG_NO_CONTEXT, status_code=400)
    instruction = request.get("instruction")
    instruction = "" if instruction is None else str(instruction)
    history = _history_messages(request.get("history"))
    return action, context, enabled, instruction, history


def _history_messages(history) -> list[dict]:
    if not isinstance(history, list):
        return []
    messages: list[dict] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text")
        if role not in ("user", "assistant") or text is None:
            continue
        text = str(text)
        if not text.strip():
            continue
        messages.append({"role": role, "content": text})
    return messages


def _build_user_content(action: str, instruction: str, context: dict, enabled: list[str]) -> str:
    if action == "freeform":
        task = instruction.strip() or FREEFORM_FALLBACK
    else:
        task = ACTION_PRESETS[action]
    lines = [f"任务：{task}"]
    chunks: list[str] = []
    if "positive" in enabled:
        positive = context.get("positive")
        if isinstance(positive, str) and positive.strip():
            chunks.append("Positive：" + positive)
    if "negative" in enabled:
        negative = context.get("negative")
        if isinstance(negative, str) and negative.strip():
            chunks.append("Negative：" + negative)
    if "recipe" in enabled:
        recipe_text = _serialize_recipe(context.get("recipe"))
        if recipe_text:
            chunks.append("Recipe：" + recipe_text)
    if chunks:
        lines.append("当前上下文：")
        lines.extend(chunks)
    return "\n".join(lines)


def _serialize_recipe(recipe) -> str:
    if not isinstance(recipe, dict) or not recipe:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for key, label in RECIPE_LABELS.items():
        if key not in recipe:
            continue
        value = recipe[key]
        if value is None or value == "":
            continue
        parts.append(f"{label}={value}")
        seen.add(key)
    for key, value in recipe.items():
        if key in seen or value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


def _resolve_executor(tool_registry):
    if callable(tool_registry):
        return tool_registry
    if isinstance(tool_registry, dict) and tool_registry:
        def _dispatch(name: str, arguments: dict) -> str:
            fn = tool_registry.get(name)
            if fn is None:
                return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
            result = fn(arguments)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            return result

        return _dispatch
    from .copilot_tools import execute_tool

    return execute_tool


def _is_tools_unsupported(exc: BaseException) -> bool:
    """HTTP 400/404/422 且错误正文含 tool / function / does not support 时视为不支持工具。"""
    text = str(exc)
    lower = text.lower()
    has_status = any(re.search(rf"(?:^|[\s:]){code}(?:[\s:]|$)", text) for code in _UNSUPPORT_STATUSES)
    if not has_status:
        return False
    return any(hint in lower for hint in _UNSUPPORT_HINTS)


def _fallback_messages(history: list[dict], user_content: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    messages.append({"role": "user", "content": _static_catalog_summary()})
    return messages


def _static_catalog_summary() -> str:
    """服务商不支持 tools 时的静态目录，控制在 3KB 以内。"""
    try:
        from .copilot_tools import execute_tool

        cats = _load_tool_json(execute_tool("list_tag_categories", {}))
        chars = _load_tool_json(execute_tool("list_characters", {}))
        recipes = _load_tool_json(execute_tool("list_recipes", {}))
        cat_parts = []
        if isinstance(cats, list):
            for item in cats:
                if isinstance(item, dict):
                    cat_parts.append(f"{item.get('name', '')}({item.get('tag_count', 0)})")
        char_names = []
        if isinstance(chars, list):
            char_names = [item.get("name", "") for item in chars if isinstance(item, dict)]
        recipe_names = []
        if isinstance(recipes, list):
            recipe_names = [
                f"{item.get('name', '')}[{item.get('type', '')}]"
                for item in recipes
                if isinstance(item, dict)
            ]
        text = (
            "静态资料目录（当前服务商不支持工具调用）：\n"
            f"分类：{', '.join(part for part in cat_parts if part)}\n"
            f"角色：{', '.join(name for name in char_names if name)}\n"
            f"配方：{', '.join(name for name in recipe_names if name)}"
        )
    except Exception:
        text = "静态资料目录获取失败，请仅根据当前上下文给出最终 JSON。"
    encoded = text.encode("utf-8")
    if len(encoded) > 3000:
        text = encoded[:3000].decode("utf-8", errors="ignore")
    return text


def _load_tool_json(raw: str):
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _normalize_tool_message(raw) -> dict:
    """兼容 message dict、完整 chat.completion 响应，以及旧版 function_call。"""
    if isinstance(raw, str):
        return {"role": "assistant", "content": raw}
    if not isinstance(raw, dict):
        return {"role": "assistant", "content": "" if raw is None else str(raw)}
    if any(key in raw for key in ("tool_calls", "content", "role", "function_call")):
        message = dict(raw)
        if not message.get("tool_calls") and isinstance(message.get("function_call"), dict):
            message["tool_calls"] = [
                {
                    "id": message.get("id") or "call_legacy",
                    "type": "function",
                    "function": message["function_call"],
                }
            ]
        return message
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        inner = choice0.get("message")
        if isinstance(inner, dict):
            return _normalize_tool_message(inner)
    return raw


def _run_one_tool(call, executor) -> tuple[dict, dict]:
    from .copilot_history import summarize_tool

    call = call if isinstance(call, dict) else {}
    call_id = call.get("id") or ""
    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(fn.get("name") or "")
    raw_args = fn.get("arguments")
    keys: list[str] = []
    arguments: dict = {}
    try:
        if raw_args is None or raw_args == "":
            arguments = {}
        elif isinstance(raw_args, dict):
            arguments = raw_args
        elif isinstance(raw_args, str):
            arguments = json.loads(raw_args)
        else:
            raise ValueError("arguments 类型无效")
        if not isinstance(arguments, dict):
            raise ValueError("arguments 不是对象")
        keys = [str(key) for key in arguments.keys()]
    except (json.JSONDecodeError, ValueError, TypeError):
        content = json.dumps(
            {"error": f"工具 {name} 参数不是合法 JSON，键: {', '.join(keys) or '(无法解析)'}"},
            ensure_ascii=False,
        )
        summary = summarize_tool(name, {}, content)
        return {"role": "tool", "tool_call_id": call_id, "content": content}, summary
    try:
        result = executor(name, arguments)
    except Exception:
        result = json.dumps(
            {"error": f"工具 {name} 执行失败，键: {', '.join(keys)}"},
            ensure_ascii=False,
        )
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)
    summary = summarize_tool(name, arguments, result)
    return {"role": "tool", "tool_call_id": call_id, "content": result}, summary


def _tool_loop(
    messages: list,
    *,
    llm_tool_call,
    executor,
    base_url: str,
    api_key: str,
    model: str,
    max_tool_rounds: int,
) -> list[dict]:
    from .copilot_tools import TOOL_SCHEMAS

    summaries: list[dict] = []
    for _round in range(max(0, max_tool_rounds)):
        raw = llm_tool_call(
            base_url,
            api_key,
            model,
            messages,
            tools=TOOL_SCHEMAS,
            temperature=0.4,
            max_tokens=2048,
        )
        message = _normalize_tool_message(raw)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return summaries
        assistant_content = message.get("content")
        messages.append(
            {
                "role": "assistant",
                "content": "" if assistant_content is None else assistant_content,
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            tool_message, summary = _run_one_tool(call, executor)
            messages.append(tool_message)
            summaries.append(summary)
    messages.append({"role": "user", "content": QUOTA_USER_MESSAGE})
    return summaries


def _invoke_llm(llm_call, base_url: str, api_key: str, model: str, messages: list) -> str:
    try:
        content = llm_call(
            base_url,
            api_key,
            model,
            messages,
            temperature=0.4,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
    except CopilotError:
        raise
    except Exception as exc:
        raise CopilotError(_redact_secret(str(exc), api_key)) from exc
    if content is None:
        return ""
    return content if isinstance(content, str) else str(content)


def _redact_secret(message: str, api_key: str) -> str:
    return message.replace(api_key, "***") if api_key else message


def _strip_markdown_fence(text: str) -> str:
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _json_candidates(content: str) -> list[str]:
    text = (content or "").strip()
    candidates: list[str] = []
    if text:
        candidates.append(text)
    stripped = _strip_markdown_fence(text)
    if stripped and stripped not in candidates:
        candidates.append(stripped)
    extracted = _extract_balanced_object(stripped or text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)
    return candidates


def _parse_and_validate(content: str) -> dict:
    data = None
    for candidate in _json_candidates(content):
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            data = loaded
            break
    if data is None:
        raise ValueError("无法解析 JSON")
    return Suggestion.model_validate(data).model_dump(exclude_none=True, by_alias=True)


def _finalize(payload: dict, action: str, tool_summaries: list[dict] | None = None) -> dict:
    payload["id"] = "llm-" + secrets.token_hex(4)
    payload["action"] = action
    payload.setdefault("diagnostics", [])
    payload.setdefault("operations", [])
    payload.setdefault("stages", [])
    for index, diagnostic in enumerate(payload["diagnostics"]):
        if not diagnostic.get("id"):
            diagnostic["id"] = f"d-{index + 1}"
    if tool_summaries:
        payload["tools"] = list(tool_summaries)
    return payload
