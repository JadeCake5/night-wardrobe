import type {
  Action,
  ContextSnapshot,
  CopilotMessage,
  CopilotSession,
  Diagnostic,
  ExecutionStage,
  MessagePart,
  PromptOperation,
  PromptSuggestion,
  ToolSummary,
  Turn,
} from "./types";

const SNAPSHOT_KEYS: Array<keyof ContextSnapshot> = [
  "character",
  "outfit",
  "artist",
  "scene",
  "negative_template",
  "positive_preview",
  "negative_preview",
];

const IDENTITY_KEYS: Array<keyof ContextSnapshot> = [
  "character",
  "outfit",
  "artist",
  "scene",
  "negative_template",
];

export const EMPTY_SNAPSHOT: ContextSnapshot = {
  character: "",
  outfit: "",
  artist: "",
  scene: "",
  negative_template: "",
  positive_preview: "",
  negative_preview: "",
};

export function normalizeSnapshot(raw: unknown): ContextSnapshot {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const snapshot = { ...EMPTY_SNAPSHOT };
  for (const key of SNAPSHOT_KEYS) {
    const value = source[key];
    snapshot[key] = value == null ? "" : String(value);
  }
  return snapshot;
}

export function snapshotDiverged(saved: unknown, current: unknown): boolean {
  const oldSnap = normalizeSnapshot(saved);
  const newSnap = normalizeSnapshot(current);
  for (const key of IDENTITY_KEYS) {
    if ((oldSnap[key] || "").trim() !== (newSnap[key] || "").trim()) return true;
  }
  for (const key of ["positive_preview", "negative_preview"] as const) {
    const a = (oldSnap[key] || "").replace(/\s+/g, "").slice(0, 80);
    const b = (newSnap[key] || "").replace(/\s+/g, "").slice(0, 80);
    if (a && b && a !== b) return true;
  }
  return false;
}

export function parseTimestamp(raw: string): Date {
  if (!raw) return new Date();
  const iso = raw.includes("T") ? raw : raw.replace(" ", "T") + "Z";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatSessionTime(raw: string, now = new Date()): string {
  const date = parseTimestamp(raw);
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export type SessionGroup = { label: string; items: CopilotSession[] };

export function groupSessions(sessions: CopilotSession[], now = new Date()): SessionGroup[] {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const buckets: Record<string, CopilotSession[]> = { 今天: [], 昨天: [], 更早: [] };
  for (const session of sessions) {
    const date = parseTimestamp(session.updated_at);
    const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    if (day.getTime() === today.getTime()) buckets["今天"].push(session);
    else if (day.getTime() === yesterday.getTime()) buckets["昨天"].push(session);
    else buckets["更早"].push(session);
  }
  return (["今天", "昨天", "更早"] as const)
    .filter((label) => buckets[label].length)
    .map((label) => ({ label, items: buckets[label] }));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function partData<T>(part: MessagePart | undefined): T | undefined {
  if (!part || !asRecord(part.data)) return undefined;
  return part.data as T;
}

export function turnsFromMessages(messages: CopilotMessage[]): Turn[] {
  return (messages || []).map((message) => messageToTurn(message));
}

export function messageToTurn(message: CopilotMessage): Turn {
  const content = message.content || {};
  const parts = Array.isArray(content.parts) ? content.parts : [];
  const diagnosisPart = parts.find((part) => part.type === "diagnosis");
  const diffPart = parts.find((part) => part.type === "diff");
  const execPart = parts.find((part) => part.type === "execution");
  const toolParts = parts.filter((part) => part.type === "tool");
  const diagnostics = (partData<{ items?: Diagnostic[] }>(diagnosisPart)?.items || []) as Diagnostic[];
  const operations = (partData<{ operations?: PromptOperation[] }>(diffPart)?.operations || []) as PromptOperation[];
  const stages = (partData<{ stages?: ExecutionStage[] }>(execPart)?.stages || []) as ExecutionStage[];
  const tools: ToolSummary[] = toolParts.map((part) => {
    const data = part.data || {};
    return {
      name: String(data.name || ""),
      status: String(data.status || "ok"),
      summary: String(data.summary || ""),
      result_summary: data.result_summary ? String(data.result_summary) : "",
    };
  });
  const turn: Turn = {
    id: message.id,
    role: message.role,
    text: content.text || "",
    action: content.action,
    contexts: content.contexts,
    applied: !!content.applied,
    discarded: !!content.discarded,
    checked: Array.isArray(content.checked) ? content.checked : operations.map(() => true),
  };
  if (message.role === "assistant") {
    turn.status = "done";
    if (diagnostics.length || operations.length || stages.length || (content.text && message.role === "assistant")) {
      const suggestion: PromptSuggestion = {
        id: content.suggestion_id || message.id,
        action: (content.action || "freeform") as Action,
        summary: content.text || "",
        operations,
        diagnostics,
        stages,
        tools,
      };
      turn.suggestion = suggestion;
    }
    if (tools.length) turn.tools = tools;
  }
  return turn;
}

export function snapshotHasContent(snapshot: ContextSnapshot): boolean {
  return SNAPSHOT_KEYS.some((key) => (snapshot[key] || "").trim());
}
