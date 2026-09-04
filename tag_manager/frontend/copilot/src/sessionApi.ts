import type { ContextSnapshot, CopilotMessage, CopilotSession } from "./types";

async function readJson(res: Response): Promise<Record<string, unknown>> {
  const raw = await res.text();
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    /* 非 JSON */
  }
  throw new Error(res.ok ? "响应无法解析" : "请求失败（HTTP " + res.status + "）");
}

function fail(data: Record<string, unknown>, status: number): Error {
  const text = typeof data.error === "string" && data.error ? data.error : "请求失败（HTTP " + status + "）";
  return new Error(text);
}

export async function listSessions(q = ""): Promise<CopilotSession[]> {
  const url = q ? "/api/workshop/copilot/sessions?q=" + encodeURIComponent(q) : "/api/workshop/copilot/sessions";
  const res = await fetch(url);
  const data = await readJson(res);
  if (!res.ok) throw fail(data, res.status);
  return Array.isArray(data.sessions) ? (data.sessions as CopilotSession[]) : [];
}

export async function createSession(snapshot?: ContextSnapshot, title?: string): Promise<CopilotSession> {
  const res = await fetch("/api/workshop/copilot/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      context_snapshot: snapshot || {},
      title: title || "",
    }),
  });
  const data = await readJson(res);
  if (!res.ok) throw fail(data, res.status);
  return data as unknown as CopilotSession;
}

export async function getSessionDetail(id: string): Promise<{ session: CopilotSession; messages: CopilotMessage[] }> {
  const res = await fetch("/api/workshop/copilot/sessions/" + encodeURIComponent(id));
  const data = await readJson(res);
  if (!res.ok) throw fail(data, res.status);
  return {
    session: data.session as CopilotSession,
    messages: Array.isArray(data.messages) ? (data.messages as CopilotMessage[]) : [],
  };
}

export async function renameSession(id: string, title: string): Promise<CopilotSession> {
  const res = await fetch("/api/workshop/copilot/sessions/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await readJson(res);
  if (!res.ok) throw fail(data, res.status);
  return data as unknown as CopilotSession;
}

export async function deleteSession(id: string): Promise<{ ok: boolean; id: string; sessions: CopilotSession[] }> {
  const res = await fetch("/api/workshop/copilot/sessions/" + encodeURIComponent(id), { method: "DELETE" });
  const data = await readJson(res);
  if (!res.ok) throw fail(data, res.status);
  return {
    ok: true,
    id: String(data.id || id),
    sessions: Array.isArray(data.sessions) ? (data.sessions as CopilotSession[]) : [],
  };
}

export async function patchMessage(
  sessionId: string,
  messageId: string,
  patch: { applied?: boolean; discarded?: boolean; checked?: boolean[] },
): Promise<CopilotMessage> {
  const res = await fetch(
    "/api/workshop/copilot/sessions/" + encodeURIComponent(sessionId) + "/messages/" + encodeURIComponent(messageId),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  const data = await readJson(res);
  if (!res.ok) throw fail(data, res.status);
  return data as unknown as CopilotMessage;
}
