import type { Action, Diagnostic, ExecutionStage, PromptRequest, PromptOperation, PromptSuggestion } from "./types";
import { RealCopilotBackend } from "./realBackend";

const MOCK_DELAY_MS = 600;
const CONTEXT_LABELS: Record<string, string> = {
  positive: "Positive",
  negative: "Negative",
  recipe: "Recipe",
};

function splitSegments(text: string): string[] {
  if (!text) return [];
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}

let suggestionSeq = 0;

function diagnoseBasic(pos: string[], neg: string[]): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  if (!pos.length) {
    diagnostics.push({
      id: "d-empty-pos",
      level: "error",
      message: "Positive 为空：请先在左侧选择配方，或点击预览区直接书写。",
      target: "positive",
    });
  }
  if (pos.length && !neg.length) {
    diagnostics.push({
      id: "d-empty-neg",
      level: "info",
      message: "Negative 为空：可选择负面模板，或用「优化 Negative」补充。",
      target: "negative",
    });
  }
  const seen: Record<string, boolean> = {};
  let dup: string | null = null;
  pos.forEach((tag) => {
    if (seen[tag] && !dup) dup = tag;
    seen[tag] = true;
  });
  if (dup) {
    diagnostics.push({
      id: "d-dup",
      level: "warning",
      message: "Positive 存在重复整段：" + dup,
      relatedTag: dup,
      target: "positive",
    });
  }
  if (!diagnostics.length) {
    diagnostics.push({
      id: "d-ok",
      level: "success",
      message: "基础检查未发现问题（语义级诊断待后端接入）。",
    });
  }
  return diagnostics;
}

// ExecutionStage = { label, detail? }：只描述做了什么，禁止承载 chain-of-thought / hidden reasoning
export function buildMockStages(
  request: PromptRequest,
  pos: string[],
  neg: string[],
  opCount: number,
): ExecutionStage[] {
  const stages: ExecutionStage[] = [
    { label: "解析当前 Prompt", detail: "Positive " + pos.length + " 段 · Negative " + neg.length + " 段" },
  ];
  const ctx =
    request.contexts && request.contexts.length
      ? request.contexts.map((k) => CONTEXT_LABELS[k] || k).join(" / ")
      : "未选择上下文";
  stages.push({ label: "读取上下文", detail: ctx });
  if (request.history && request.history.length) {
    stages.push({ label: "接续会话", detail: "携带 " + request.history.length + " 条历史消息" });
  }
  stages.push({ label: "生成建议", detail: opCount ? opCount + " 项待确认修改" : "无修改建议" });
  return stages;
}

export function buildMockSuggestion(request: PromptRequest): PromptSuggestion {
  const pos = splitSegments(request.positive);
  const neg = splitSegments(request.negative);
  const base: PromptSuggestion = {
    id: "mock-" + ++suggestionSeq,
    action: request.action,
    operations: [],
    diagnostics: [],
    summary: "",
  };
  switch (request.action) {
    case "diagnose":
      base.summary = "基础检查：仅做空态与整段重复等确定性检查，语义级诊断待后端接入。";
      base.diagnostics = diagnoseBasic(pos, neg);
      break;
    case "dedupe": {
      const seen: Record<string, boolean> = {};
      pos.forEach((tag) => {
        if (seen[tag]) {
          base.operations.push({ kind: "remove", target: "positive", tag, reason: "重复出现的整段 tag" });
        }
        seen[tag] = true;
      });
      base.summary = base.operations.length
        ? "发现 " + base.operations.length + " 个重复整段，可移除。"
        : "未发现重复整段 tag。";
      break;
    }
    case "reduce_conflicts":
      base.summary = "演示数据：真实冲突检测待后端接入，以下为演示操作。";
      if (pos.includes("simple background") && pos.includes("detailed background")) {
        base.operations.push({
          kind: "remove",
          target: "positive",
          tag: "simple background",
          reason: "与 detailed background 语义冲突",
        });
      } else {
        base.operations.push({
          kind: "add",
          target: "positive",
          tag: "coherent lighting",
          category: "custom",
          reason: "演示：统一光照取向",
        });
      }
      break;
    case "improve_pose":
      base.summary = "演示数据：人物动作向补充，真实建议待后端接入。";
      base.operations.push({
        kind: "add",
        target: "positive",
        tag: "dynamic pose",
        category: "custom",
        reason: "演示：增强动作表现",
      });
      break;
    case "improve_composition":
      base.summary = "演示数据：构图向补充，真实建议待后端接入。";
      base.operations.push({
        kind: "add",
        target: "positive",
        tag: "rule of thirds",
        category: "custom",
        reason: "演示：构图参考",
      });
      break;
    case "enrich_environment":
      base.summary = "演示数据：环境细节向补充，真实建议待后端接入。";
      base.operations.push({
        kind: "add",
        target: "positive",
        tag: "detailed background",
        category: "scene",
        reason: "演示：环境细节",
      });
      break;
    case "optimize_negative":
      base.summary = "演示数据：常用质量负面词补充，真实建议待后端接入。";
      ["lowres", "bad anatomy", "worst quality"].forEach((tag) => {
        if (!neg.includes(tag)) {
          base.operations.push({
            kind: "add",
            target: "negative",
            tag,
            category: "neg",
            reason: "演示：常用质量负面词",
          });
        }
      });
      break;
    case "freeform":
    default:
      base.summary =
        "演示数据：收到自然语言指令「" + (request.customInstruction || "") + "」，真实改写待后端接入。";
      base.operations.push({
        kind: "add",
        target: "positive",
        tag: "masterpiece",
        category: "custom",
        reason: "演示占位操作",
      });
      break;
  }
  base.stages = buildMockStages(request, pos, neg, base.operations.length);
  return base;
}

export const MockCopilotBackend = {
  requestSuggestion(request: PromptRequest): Promise<PromptSuggestion> {
    return new Promise((resolve) => {
      setTimeout(() => resolve(buildMockSuggestion(request)), MOCK_DELAY_MS);
    });
  },
};

export const CopilotService = {
  backend: RealCopilotBackend,
  requestSuggestion(request: PromptRequest) {
    return this.backend.requestSuggestion(request);
  },
};

export const ACTION_LABELS: Record<Action, string> = {
  diagnose: "诊断 Prompt",
  reduce_conflicts: "减少冲突",
  dedupe: "清理重复",
  improve_pose: "优化动作",
  improve_composition: "优化构图",
  enrich_environment: "补充环境细节",
  optimize_negative: "优化 Negative",
  freeform: "自定义指令",
};
