import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Loader } from "@/components/ai-elements/loader";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";
import { DiagnosisCard } from "@/components/workshop/DiagnosisCard";
import { DiffCard } from "@/components/workshop/DiffCard";
import { OldContextNotice } from "@/components/workshop/OldContextNotice";
import { PromptContext } from "@/components/workshop/PromptContext";
import { SessionBar } from "@/components/workshop/SessionBar";
import { SessionHistoryView } from "@/components/workshop/SessionSwitcher";
import { EVT_CONTEXT, emitApply, emitToast, payloadFromDetail, readHostContext, readHostSnapshot } from "./bridge";
import { ACTION_LABELS, CopilotService } from "./mock";
import { snapshotDiverged, turnsFromMessages } from "./session";
import {
  createSession,
  deleteSession,
  getSessionDetail,
  listSessions,
  patchMessage,
  renameSession,
} from "./sessionApi";
import type { Action, CopilotSession, PromptContextPayload, PromptRequest, Turn } from "./types";

const PRIMARY: Action[] = ["diagnose", "improve_pose", "reduce_conflicts", "improve_composition"];
const EXTRA: Action[] = ["dedupe", "enrich_environment", "optimize_negative"];

export function App({ host }: { host: HTMLElement }) {
  const [prompt, setPrompt] = useState(readHostContext);
  const [snapshot, setSnapshot] = useState(readHostSnapshot);
  const [ctxOn, setCtxOn] = useState({ positive: true, negative: true, recipe: true });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [more, setMore] = useState(false);
  const [sessions, setSessions] = useState<CopilotSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [sessionLoading, setSessionLoading] = useState(true);
  const [historyMode, setHistoryMode] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const activeSessionIdRef = useRef("");
  const pendingSessionsRef = useRef(new Set<string>());
  const searchGenRef = useRef(0);
  const remoteSearchArmedRef = useRef(false);
  const [pendingTick, setPendingTick] = useState(0);

  const activeSession = useMemo(
    () => sessions.find((item) => item.id === activeSessionId) || null,
    [sessions, activeSessionId],
  );
  const busy = useMemo(
    () => pendingSessionsRef.current.has(activeSessionId) || turns.some((t) => t.role === "assistant" && t.status === "pending"),
    [turns, activeSessionId, pendingTick],
  );
  const showOldContext = !!(activeSession && snapshotDiverged(activeSession.context_snapshot, snapshot));

  const setActive = useCallback((id: string) => {
    activeSessionIdRef.current = id;
    setActiveSessionId(id);
  }, []);

  const markPending = useCallback((id: string, on: boolean) => {
    if (on) pendingSessionsRef.current.add(id);
    else pendingSessionsRef.current.delete(id);
    setPendingTick((value) => value + 1);
  }, []);

  useEffect(() => {
    function onCtx(e: Event) {
      setPrompt(payloadFromDetail((e as CustomEvent<PromptContextPayload>).detail));
      setSnapshot(readHostSnapshot());
    }
    host.addEventListener(EVT_CONTEXT, onCtx);
    window.addEventListener(EVT_CONTEXT, onCtx);
    return () => {
      host.removeEventListener(EVT_CONTEXT, onCtx);
      window.removeEventListener(EVT_CONTEXT, onCtx);
    };
  }, [host]);

  const applyTurnsFromDetail = useCallback(
    (id: string, messages: Parameters<typeof turnsFromMessages>[0]) => {
      let next = turnsFromMessages(messages);
      if (pendingSessionsRef.current.has(id)) {
        const last = next[next.length - 1];
        if (!last || last.role === "user") {
          next = [...next, { id: "pending-" + id, role: "assistant", status: "pending" }];
        }
      }
      setTurns(next);
    },
    [],
  );

  const loadSession = useCallback(
    async (id: string) => {
      const detail = await getSessionDetail(id);
      setSessions((prev) => {
        const others = prev.filter((item) => item.id !== detail.session.id);
        return [detail.session, ...others].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
      });
      setActive(id);
      applyTurnsFromDetail(id, detail.messages);
      setHistoryMode(false);
      setSwitcherOpen(false);
    },
    [applyTurnsFromDetail, setActive],
  );

  const refreshSessions = useCallback(async () => {
    const list = await listSessions();
    setSessions(list);
    return list;
  }, []);

  const bootstrap = useCallback(async () => {
    setSessionLoading(true);
    try {
      let list = await listSessions();
      if (!list.length) {
        const created = await createSession(readHostSnapshot());
        list = [created];
      }
      setSessions(list);
      await loadSession(list[0].id);
    } catch (err) {
      emitToast(host, err instanceof Error ? err.message : "无法加载会话");
    } finally {
      setSessionLoading(false);
    }
  }, [host, loadSession]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    // 搜索框即时本地过滤；防抖后再带 q= 打 list API，以便命中尚未加载的旧会话。
    if (sessionLoading) return;
    const q = sessionSearch.trim();
    if (!q && !remoteSearchArmedRef.current) return;
    remoteSearchArmedRef.current = true;
    const gen = ++searchGenRef.current;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const list = await listSessions(q);
          if (gen !== searchGenRef.current) return;
          if (q) {
            setSessions((prev) => {
              const seen = new Map<string, CopilotSession>();
              for (const item of list) seen.set(item.id, item);
              for (const item of prev) {
                if (!seen.has(item.id)) seen.set(item.id, item);
              }
              return Array.from(seen.values()).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
            });
          } else {
            setSessions(list);
          }
        } catch {
          /* 本地过滤仍可用 */
        }
      })();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [sessionSearch, sessionLoading]);

  useEffect(() => {
    if (!activeSessionId || sessionLoading) return;
    if (sessions.length === 0) return;
    if (sessions.some((item) => item.id === activeSessionId)) return;
    void loadSession(sessions[0].id);
  }, [sessions, activeSessionId, sessionLoading, loadSession]);

  async function handleNewSession() {
    try {
      const created = await createSession(readHostSnapshot());
      const list = await refreshSessions();
      setSessions(list.length ? list : [created]);
      setActive(created.id);
      setTurns([]);
      setHistoryMode(false);
      setSwitcherOpen(false);
      setInput("");
    } catch (err) {
      emitToast(host, err instanceof Error ? err.message : "无法新建会话");
    }
  }

  async function handleSelectSession(id: string) {
    if (id === activeSessionIdRef.current) {
      setSwitcherOpen(false);
      setHistoryMode(false);
      return;
    }
    try {
      await loadSession(id);
    } catch (err) {
      emitToast(host, err instanceof Error ? err.message : "无法打开会话");
    }
  }

  async function handleCommitRename() {
    if (!renamingId) return;
    const title = renameValue.trim();
    if (!title) {
      emitToast(host, "标题不能为空");
      return;
    }
    try {
      const updated = await renameSession(renamingId, title);
      setSessions((prev) => prev.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)));
      setRenamingId(null);
    } catch (err) {
      emitToast(host, err instanceof Error ? err.message : "重命名失败");
    }
  }

  async function handleConfirmDelete(sessionId?: string) {
    const deleting = sessionId || confirmDeleteId;
    if (!deleting) return;
    try {
      const result = await deleteSession(deleting);
      const remaining = (result.sessions || []).filter((item) => item.id !== deleting);
      setSessions(remaining);
      setConfirmDeleteId(null);
      setRenamingId(null);
      setSwitcherOpen(false);
      // 删除非当前会话：只更新列表，停留在当前视图（含 History View）。
      if (deleting !== activeSessionIdRef.current) return;
      const nextId = remaining[0]?.id;
      if (nextId) {
        await loadSession(nextId);
      } else {
        const created = await createSession(readHostSnapshot());
        setSessions([created]);
        setActive(created.id);
        setTurns([]);
        setHistoryMode(false);
      }
    } catch (err) {
      emitToast(host, err instanceof Error ? err.message : "删除失败");
    }
  }

  function activeContexts() {
    return (["positive", "negative", "recipe"] as const).filter((k) => ctxOn[k]);
  }

  async function runAction(action: Action, customInstruction?: string) {
    const active = activeContexts();
    if (!active.length) {
      setTurns((prev) => [
        ...prev,
        {
          id: "err-" + Date.now(),
          role: "error",
          text: "未选择上下文：请至少开启 Positive / Negative / Recipe 中的一项。",
        },
      ]);
      return;
    }
    const requestSessionId = activeSessionIdRef.current;
    if (!requestSessionId) {
      emitToast(host, "会话尚未就绪");
      return;
    }
    if (pendingSessionsRef.current.has(requestSessionId)) return;
    const token = Date.now();
    const userTurn: Turn = {
      id: "u-" + token,
      role: "user",
      text: customInstruction || ACTION_LABELS[action],
      action,
      contexts: [...active],
    };
    const pending: Turn = { id: "a-" + token, role: "assistant", status: "pending", action };
    markPending(requestSessionId, true);
    if (activeSessionIdRef.current === requestSessionId) {
      setTurns((prev) => [...prev, userTurn, pending]);
    }
    setInput("");

    const request: PromptRequest = {
      action,
      positive: ctxOn.positive ? prompt.positive : "",
      negative: ctxOn.negative ? prompt.negative : "",
      recipe: ctxOn.recipe ? prompt.recipe : {},
      customInstruction,
      contexts: [...active],
      session_id: requestSessionId,
    };

    const pendingAlias = "pending-" + requestSessionId;
    const applyLocalSuccess = (suggestion: Awaited<ReturnType<typeof CopilotService.requestSuggestion>>) => {
      setTurns((prev) =>
        prev.map((t) => {
          if (t.id === userTurn.id) {
            return { ...t, id: suggestion.user_message_id || t.id };
          }
          if (t.id === pending.id || t.id === pendingAlias) {
            return {
              ...t,
              id: suggestion.assistant_message_id || t.id,
              status: "done",
              text: suggestion.summary,
              suggestion,
              tools: suggestion.tools,
              checked: suggestion.operations.map(() => true),
            };
          }
          return t;
        }),
      );
    };
    const hydrateRequestSession = async (fallback?: () => void) => {
      if (activeSessionIdRef.current !== requestSessionId) {
        void refreshSessions();
        return;
      }
      try {
        await loadSession(requestSessionId);
      } catch {
        if (fallback) fallback();
        void refreshSessions();
      }
    };

    try {
      const suggestion = await CopilotService.requestSuggestion(request);
      const owned = suggestion.session_id || requestSessionId;
      markPending(requestSessionId, false);
      if (owned !== requestSessionId) return;
      await hydrateRequestSession(() => applyLocalSuccess(suggestion));
    } catch (err) {
      markPending(requestSessionId, false);
      const message = err instanceof Error ? err.message : "请求失败，请稍后重试";
      await hydrateRequestSession(() => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === pending.id || t.id === pendingAlias
              ? { id: pending.id, role: "error", text: message }
              : t,
          ),
        );
      });
    }
  }

  async function persistTurn(next: Turn) {
    const sid = activeSessionIdRef.current;
    if (!sid || next.id.startsWith("u-") || next.id.startsWith("a-") || next.id.startsWith("pending-")) return;
    try {
      await patchMessage(sid, next.id, {
        applied: next.applied,
        discarded: next.discarded,
        checked: next.checked,
      });
    } catch (err) {
      emitToast(host, err instanceof Error ? err.message : "无法保存应用状态");
    }
  }

  function applyTurn(turn: Turn, onlyChecked: boolean) {
    if (!turn.suggestion || turn.applied || turn.discarded) return;
    // 当前工作区已偏离会话快照时，历史 Diff 禁止直接写回，必须重新检查。
    if (showOldContext) {
      emitToast(host, "此建议基于较早的 Prompt，请先使用当前 Prompt 重新检查");
      return;
    }
    const ops = turn.suggestion.operations.filter((_, i) => !onlyChecked || turn.checked?.[i] !== false);
    if (!ops.length) {
      emitToast(host, "没有可应用的操作");
      return;
    }
    emitApply(host, ops);
    const next = { ...turn, applied: true };
    setTurns((prev) => prev.map((t) => (t.id === turn.id ? next : t)));
    void persistTurn(next);
  }

  const empty = turns.length === 0;

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden" data-copilot-shell="" data-session-id={activeSessionId}>
      <SessionBar
        sessions={sessions}
        active={activeSession}
        open={switcherOpen}
        onToggle={() => setSwitcherOpen((value) => !value)}
        onClose={() => setSwitcherOpen(false)}
        onNew={() => void handleNewSession()}
        search={sessionSearch}
        onSearch={setSessionSearch}
        onSelect={(id) => void handleSelectSession(id)}
        onViewAll={() => {
          setHistoryMode(true);
          setSwitcherOpen(false);
        }}
      />

      {historyMode ? (
        <SessionHistoryView
          sessions={sessions}
          activeId={activeSessionId}
          search={sessionSearch}
          onSearch={setSessionSearch}
          onSelect={(id) => void handleSelectSession(id)}
          onBack={() => setHistoryMode(false)}
          renamingId={renamingId}
          renameValue={renameValue}
          onRenameValue={setRenameValue}
          onStartRename={(session) => {
            setRenamingId(session.id);
            setRenameValue(session.title || "");
            setConfirmDeleteId(null);
          }}
          onCommitRename={() => void handleCommitRename()}
          onCancelRename={() => setRenamingId(null)}
          confirmDeleteId={confirmDeleteId}
          onAskDelete={(id) => {
            setConfirmDeleteId(id);
            setRenamingId(null);
          }}
          onConfirmDelete={(id) => void handleConfirmDelete(id)}
          onCancelDelete={() => setConfirmDeleteId(null)}
        />
      ) : (
        <>
          {showOldContext && activeSession && <OldContextNotice snapshot={activeSession.context_snapshot} />}
          <Conversation className="min-h-0 w-full min-w-0">
            <ConversationContent className="w-full min-w-0 gap-4 p-0">
              {sessionLoading && (
                <div className="copilot-session-loading" data-copilot-session-loading="">
                  加载会话…
                </div>
              )}
              {!sessionLoading && empty && (
                <ConversationEmptyState className="size-auto w-full min-w-0 flex-none items-start justify-start gap-3 p-0 text-left">
                  <div className="w-full min-w-0 space-y-3">
                    <div className="space-y-1.5">
                      <h3 className="copilot-empty-title">要我怎么改这段 Prompt？</h3>
                      <p className="copilot-empty-desc">
                        描述修改目标，我会先给建议，确认后再写回工作区。
                      </p>
                    </div>
                    <div className="flex w-full min-w-0 flex-wrap items-center gap-1.5">
                      {PRIMARY.map((action) => (
                        <Suggestion
                          key={action}
                          suggestion={ACTION_LABELS[action]}
                          data-copilot-action={action}
                          disabled={busy}
                          onClick={() => runAction(action)}
                        >
                          {ACTION_LABELS[action]}
                        </Suggestion>
                      ))}
                      <Suggestion
                        suggestion={more ? "收起" : "更多 →"}
                        data-copilot-more=""
                        aria-expanded={more}
                        onClick={() => setMore((v) => !v)}
                      >
                        {more ? "收起" : "更多 →"}
                      </Suggestion>
                    </div>
                    {more && (
                      <div className="flex w-full min-w-0 flex-wrap items-center gap-1.5" data-copilot-extra="">
                        {EXTRA.map((action) => (
                          <Suggestion
                            key={action}
                            suggestion={ACTION_LABELS[action]}
                            data-copilot-action={action}
                            disabled={busy}
                            onClick={() => runAction(action)}
                          >
                            {ACTION_LABELS[action]}
                          </Suggestion>
                        ))}
                      </div>
                    )}
                  </div>
                </ConversationEmptyState>
              )}

              {turns.map((turn) => (
                <Message key={turn.id} from={turn.role} data-turn-id={turn.id}>
                  {turn.role === "assistant" && turn.status !== "pending" && (
                    <div className="copilot-ai-label">AI</div>
                  )}
                  {turn.role === "user" && turn.contexts && (
                    <div className="flex flex-wrap justify-end gap-1">
                      {turn.contexts.map((c) => (
                        <span key={c} className="copilot-turn-ctx">
                          {c === "positive" ? "Positive" : c === "negative" ? "Negative" : "Recipe"}
                        </span>
                      ))}
                    </div>
                  )}
                  {turn.text && <MessageContent from={turn.role}>{turn.text}</MessageContent>}
                  {turn.role === "error" && (
                    <div className="flex items-center justify-between gap-2 rounded-lg border border-red-400/30 bg-red-950/30 px-2.5 py-2 text-xs text-red-300">
                      {turn.text}
                    </div>
                  )}
                  {turn.status === "pending" && (
                    <div className="grid gap-2">
                      <Task defaultOpen>
                        <TaskTrigger title="正在分析当前 Prompt…" />
                        <TaskContent>
                          <TaskItem>读取当前工作区上下文</TaskItem>
                        </TaskContent>
                      </Task>
                      <Loader />
                    </div>
                  )}
                  {turn.tools && turn.tools.length > 0 && turn.status !== "pending" && (
                    <Task defaultOpen>
                      <TaskTrigger title="工具调用" />
                      <TaskContent>
                        {turn.tools.map((tool, i) => (
                          <TaskItem key={i}>
                            {tool.summary || tool.name}
                            {tool.result_summary ? ` · ${tool.result_summary}` : ""}
                          </TaskItem>
                        ))}
                      </TaskContent>
                    </Task>
                  )}
                  {turn.suggestion?.stages && turn.suggestion.stages.length > 0 && turn.status !== "pending" && (
                    <Task defaultOpen>
                      <TaskTrigger title="执行阶段" />
                      <TaskContent>
                        {turn.suggestion.stages.map((s, i) => (
                          <TaskItem key={i}>
                            {s.label}
                            {s.detail ? ` · ${s.detail}` : ""}
                          </TaskItem>
                        ))}
                      </TaskContent>
                    </Task>
                  )}
                  {turn.suggestion?.diagnostics && (
                    <DiagnosisCard host={host} items={turn.suggestion.diagnostics} />
                  )}
                  {turn.suggestion && turn.suggestion.operations.length > 0 && (
                    <DiffCard
                      turn={turn}
                      stale={showOldContext}
                      onRecheck={() => runAction(turn.action || "diagnose")}
                      onToggle={(index) =>
                        setTurns((prev) =>
                          prev.map((t) => {
                            if (t.id !== turn.id) return t;
                            const checked = [...(t.checked || t.suggestion!.operations.map(() => true))];
                            checked[index] = !checked[index];
                            const next = { ...t, checked };
                            void persistTurn(next);
                            return next;
                          }),
                        )
                      }
                      onApplyChecked={() => applyTurn(turn, true)}
                      onApplyAll={() => {
                        const checked = turn.suggestion!.operations.map(() => true);
                        const next = { ...turn, checked };
                        setTurns((prev) => prev.map((t) => (t.id === turn.id ? next : t)));
                        applyTurn(next, false);
                      }}
                      onDiscard={() => {
                        const next = { ...turn, discarded: true };
                        setTurns((prev) => prev.map((t) => (t.id === turn.id ? next : t)));
                        void persistTurn(next);
                      }}
                    />
                  )}
                </Message>
              ))}
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>

          <div className="w-full min-w-0 flex-none" data-copilot-composer-area="">
            <PromptInput
              className="w-full min-w-0"
              onSubmit={(msg) => runAction("freeform", msg.text)}
            >
              <PromptInputBody>
                <PromptInputTextarea
                  data-copilot-input=""
                  value={input}
                  placeholder="描述你想怎么修改当前 Prompt…"
                  onChange={(e) => setInput(e.target.value)}
                  onSubmitShortcut={() => {
                    const text = input.trim();
                    if (text && !busy) runAction("freeform", text);
                  }}
                />
                <PromptInputFooter>
                  <PromptContext
                    value={ctxOn}
                    onToggle={(key) => setCtxOn((prev) => ({ ...prev, [key]: !prev[key] }))}
                  />
                  <PromptInputSubmit disabled={!input.trim() || busy} data-copilot-send="" />
                </PromptInputFooter>
              </PromptInputBody>
            </PromptInput>
            <p className="copilot-composer-hint">Enter 发送 · Shift+Enter 换行</p>
          </div>
        </>
      )}
    </div>
  );
}
