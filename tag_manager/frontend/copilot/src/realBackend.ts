import type { PromptRequest, PromptSuggestion } from "./types";

/** 前端请求超时（毫秒），覆盖服务端一轮生成窗口 */
const REQUEST_TIMEOUT_MS = 90_000;

/** 把 Island 侧 PromptRequest 映射为本地端点 JSON body */
function toRequestBody(request: PromptRequest) {
  return {
    action: request.action,
    instruction: request.customInstruction ?? "",
    context: {
      positive: request.positive,
      negative: request.negative,
      recipe: request.recipe,
      enabled_contexts: request.contexts ?? [],
    },
    history: request.history ?? [],
  };
}

function httpFail(status: number): Error {
  return new Error("请求失败（HTTP " + status + "）");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export const RealCopilotBackend = {
  async requestSuggestion(request: PromptRequest): Promise<PromptSuggestion> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch("/api/workshop/copilot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toRequestBody(request)),
        signal: controller.signal,
      });
      const raw = await res.text();
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        throw httpFail(res.status);
      }
      const data = asRecord(parsed);
      if (!data) {
        throw httpFail(res.status);
      }
      if (!res.ok || data.error) {
        const text = typeof data.error === "string" && data.error ? data.error : "";
        throw new Error(text || "请求失败（HTTP " + res.status + "）");
      }
      return {
        id: data.id as PromptSuggestion["id"],
        action: request.action,
        summary: (data.summary as string | undefined) ?? "",
        operations: Array.isArray(data.operations) ? (data.operations as PromptSuggestion["operations"]) : [],
        diagnostics: Array.isArray(data.diagnostics)
          ? (data.diagnostics as NonNullable<PromptSuggestion["diagnostics"]>)
          : [],
        stages: Array.isArray(data.stages) ? (data.stages as NonNullable<PromptSuggestion["stages"]>) : [],
      };
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        throw new Error("请求超时，请稍后重试");
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  },
};
