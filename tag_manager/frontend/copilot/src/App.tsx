import { useEffect, useMemo, useRef, useState } from "react";
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
import { PromptContext } from "@/components/workshop/PromptContext";
import { EVT_CONTEXT, emitApply, emitToast, payloadFromDetail, readHostContext } from "./bridge";
import { ACTION_LABELS, CopilotService } from "./mock";
import type { Action, PromptContextPayload, PromptRequest, Turn } from "./types";

const PRIMARY: Action[] = ["diagnose", "improve_pose", "reduce_conflicts", "improve_composition"];
const EXTRA: Action[] = ["dedupe", "enrich_environment", "optimize_negative"];

export function App({ host }: { host: HTMLElement }) {
  const [prompt, setPrompt] = useState(readHostContext);
  const [ctxOn, setCtxOn] = useState({ positive: true, negative: true, recipe: true });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [more, setMore] = useState(false);
  const sessionRef = useRef(0);
  const busy = useMemo(
    () => turns.some((t) => t.role === "assistant" && t.status === "pending"),
    [turns],
  );

  useEffect(() => {
    function onCtx(e: Event) {
      setPrompt(payloadFromDetail((e as CustomEvent<PromptContextPayload>).detail));
    }
    host.addEventListener(EVT_CONTEXT, onCtx);
    window.addEventListener(EVT_CONTEXT, onCtx);
    return () => {
      host.removeEventListener(EVT_CONTEXT, onCtx);
      window.removeEventListener(EVT_CONTEXT, onCtx);
    };
  }, [host]);

  function activeContexts() {
    return (["positive", "negative", "recipe"] as const).filter((k) => ctxOn[k]);
  }

  function historyForRequest() {
    return turns
      .filter((t) => (t.role === "user" || t.role === "assistant") && t.status !== "pending" && t.text)
      .map((t) => ({ role: t.role as "user" | "assistant", text: t.text || "" }));
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
    if (busy) return;
    const token = ++sessionRef.current;
    const userTurn: Turn = {
      id: "u-" + token,
      role: "user",
      text: customInstruction || ACTION_LABELS[action],
      action,
      contexts: [...active],
    };
    const pending: Turn = { id: "a-" + token, role: "assistant", status: "pending", action };
    setTurns((prev) => [...prev, userTurn, pending]);
    setInput("");

    const request: PromptRequest = {
      action,
      positive: ctxOn.positive ? prompt.positive : "",
      negative: ctxOn.negative ? prompt.negative : "",
      recipe: ctxOn.recipe ? prompt.recipe : {},
      customInstruction,
      contexts: [...active],
      history: historyForRequest(),
    };

    try {
      const suggestion = await CopilotService.requestSuggestion(request);
      if (token !== sessionRef.current) return;
      setTurns((prev) =>
        prev.map((t) =>
          t.id === pending.id
            ? {
                ...t,
                status: "done",
                text: suggestion.summary,
                suggestion,
                checked: suggestion.operations.map(() => true),
              }
            : t,
        ),
      );
    } catch (err) {
      if (token !== sessionRef.current) return;
      const message = err instanceof Error ? err.message : "请求失败，请稍后重试";
      setTurns((prev) =>
        prev.map((t) => (t.id === pending.id ? { id: pending.id, role: "error", text: message } : t)),
      );
    }
  }

  function applyTurn(turn: Turn, onlyChecked: boolean) {
    if (!turn.suggestion || turn.applied || turn.discarded) return;
    const ops = turn.suggestion.operations.filter((_, i) => !onlyChecked || turn.checked?.[i] !== false);
    if (!ops.length) {
      emitToast(host, "没有可应用的操作");
      return;
    }
    emitApply(host, ops);
    setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, applied: true } : t)));
  }

  const empty = turns.length === 0;

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden" data-copilot-shell="">
      <Conversation className="min-h-0 w-full min-w-0">
        <ConversationContent className="w-full min-w-0 gap-4 p-0">
          {empty && (
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
                  onToggle={(index) =>
                    setTurns((prev) =>
                      prev.map((t) => {
                        if (t.id !== turn.id) return t;
                        const checked = [...(t.checked || t.suggestion!.operations.map(() => true))];
                        checked[index] = !checked[index];
                        return { ...t, checked };
                      }),
                    )
                  }
                  onApplyChecked={() => applyTurn(turn, true)}
                  onApplyAll={() => {
                    setTurns((prev) =>
                      prev.map((t) =>
                        t.id === turn.id
                          ? { ...t, checked: t.suggestion!.operations.map(() => true) }
                          : t,
                      ),
                    );
                    applyTurn({ ...turn, checked: turn.suggestion!.operations.map(() => true) }, false);
                  }}
                  onDiscard={() => setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, discarded: true } : t)))}
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
    </div>
  );
}
