import type { ContextSnapshot, PromptContextPayload, PromptOperation } from "./types";
import { EMPTY_SNAPSHOT, normalizeSnapshot } from "./session";

export const EVT_CONTEXT = "workshop:context-change";
export const EVT_APPLY = "workshop:apply-prompt-operations";
export const EVT_HIGHLIGHT = "workshop:highlight-tag";
export const EVT_TOAST = "workshop:toast";

declare global {
  interface Window {
    WorkshopAPI?: {
      getPromptPayload: () => {
        positive: string;
        negative: string;
        recipe: Record<string, number>;
      };
      getContextSnapshot?: () => ContextSnapshot;
      applyEdited: (target: string, text: string) => void;
      highlightTag: (target: string, tag: string) => void;
      toast: (message: string) => void;
    };
    WorkshopCopilotIsland?: { mount: (el: HTMLElement) => void; unmount: () => void };
  }
}

export function readHostContext(): { positive: string; negative: string; recipe: Record<string, number> } {
  const api = window.WorkshopAPI;
  if (!api) return { positive: "", negative: "", recipe: {} };
  const p = api.getPromptPayload();
  return { positive: p.positive || "", negative: p.negative || "", recipe: p.recipe || {} };
}

export function payloadFromDetail(detail: PromptContextPayload | undefined) {
  if (!detail) return readHostContext();
  return {
    positive: detail.positivePrompt ?? detail.positive ?? "",
    negative: detail.negativePrompt ?? detail.negative ?? "",
    recipe: detail.recipe || {},
  };
}

export function emitApply(host: HTMLElement, operations: PromptOperation[]) {
  host.dispatchEvent(new CustomEvent(EVT_APPLY, { bubbles: true, detail: { operations } }));
}

export function emitHighlight(host: HTMLElement, target: string, tag: string) {
  host.dispatchEvent(new CustomEvent(EVT_HIGHLIGHT, { bubbles: true, detail: { target, tag } }));
}

export function emitToast(host: HTMLElement, message: string) {
  host.dispatchEvent(new CustomEvent(EVT_TOAST, { bubbles: true, detail: { message } }));
}

export function readHostSnapshot(): ContextSnapshot {
  const api = window.WorkshopAPI;
  if (api?.getContextSnapshot) {
    try {
      return normalizeSnapshot(api.getContextSnapshot());
    } catch {
      /* 回退到 payload 预览 */
    }
  }
  const payload = readHostContext();
  return {
    ...EMPTY_SNAPSHOT,
    positive_preview: (payload.positive || "").replace(/\s+/g, " ").trim().slice(0, 160),
    negative_preview: (payload.negative || "").replace(/\s+/g, " ").trim().slice(0, 120),
  };
}
