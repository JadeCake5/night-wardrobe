import { CopilotRequestError } from "./types";
import type { PromptRequest, PromptSuggestion } from "./types";

/** 前端请求超时（毫秒），覆盖服务端一轮生成窗口 */
const REQUEST_TIMEOUT_MS = 90_000;

/** 把 Island 侧 PromptRequest 映射为本地端点 JSON body。有 session_id 时不回传 UI history。 */
function toRequestBody(request: PromptRequest) {
  const body: Record<string, unknown> = {
    action: request.action,
    instruction: request.customInstruction ?? "",
    context: {
      positive: request.positive,
      negative: request.negative,
      recipe: request.recipe,
      enabled_contexts: request.contexts ?? [],
    },
  };
  if (request.session_id) {
    body.session_id = request.session_id;
  } else {
    body.history = request.history ?? [];
  }
  return body;
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

function attachSession(error: CopilotRequestError, data: Record<string, unknown>, status: number) {
  error.session_id = typeof data.session_id === "string" ? data.session_id : undefined;
  error.user_message_id = typeof data.user_message_id === "string" ? data.user_message_id : undefined;
  error.assistant_message_id =
    typeof data.assistant_message_id === "string" ? data.assistant_message_id : undefined;
  error.status = status;
  return error;
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
        throw attachSession(
          new CopilotRequestError(text || "请求失败（HTTP " + res.status + "）"),
          data,
          res.status,
        );
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
        tools: Array.isArray(data.tools) ? (data.tools as NonNullable<PromptSuggestion["tools"]>) : [],
        session_id: typeof data.session_id === "string" ? data.session_id : request.session_id,
        user_message_id: typeof data.user_message_id === "string" ? data.user_message_id : undefined,
        assistant_message_id:
          typeof data.assistant_message_id === "string" ? data.assistant_message_id : undefined,
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
