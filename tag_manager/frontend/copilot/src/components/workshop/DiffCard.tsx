import type { PromptOperation, Turn } from "../../types";

function sign(op: PromptOperation) {
  if (op.kind === "add") return "+";
  if (op.kind === "remove") return "−";
  return "~";
}

function tagText(op: PromptOperation) {
  if (op.kind === "replace") return op.from;
  return op.tag;
}

export function DiffCard({
  turn,
  stale,
  onRecheck,
  onToggle,
  onApplyChecked,
  onApplyAll,
  onDiscard,
}: {
  turn: Turn;
  stale?: boolean;
  onRecheck?: () => void;
  onToggle: (index: number) => void;
  onApplyChecked: () => void;
  onApplyAll: () => void;
  onDiscard: () => void;
}) {
  const suggestion = turn.suggestion;
  if (!suggestion || !suggestion.operations.length) return null;
  const settled = !!(turn.applied || turn.discarded);
  const outdated = !settled && !!stale;
  const title = turn.applied ? "已应用的修改" : turn.discarded ? "已放弃的建议" : "建议修改";
  const state = turn.applied ? "applied" : turn.discarded ? "discarded" : outdated ? "stale" : "open";
  const selected = suggestion.operations.filter((_, i) => turn.checked?.[i] !== false).length;

  return (
    <div
      className={`copilot-section ${settled ? "is-settled" : ""} ${outdated ? "is-stale" : ""}`}
      data-copilot-diff=""
      data-copilot-diff-state={state}
    >
      <p className="copilot-section-title">
        {title}
        {turn.applied && <span className="copilot-diff-badge is-applied">已应用</span>}
        {turn.discarded && <span className="copilot-diff-badge is-discarded">已放弃</span>}
      </p>
      <div className="mb-2 grid gap-0">
        {suggestion.operations.map((op, i) => {
          const checked = turn.checked ? turn.checked[i] !== false : true;
          const signColor =
            op.kind === "add" ? "text-emerald-400" : op.kind === "remove" ? "text-red-400" : "text-violet-300";
          return (
            <label key={i} className="copilot-diff-row" data-kind={op.kind}>
              <input
                type="checkbox"
                className="shrink-0"
                checked={checked}
                disabled={settled || outdated}
                onChange={() => onToggle(i)}
              />
              <span className={`w-3 shrink-0 text-center font-bold ${signColor}`}>{sign(op)}</span>
              <span className="min-w-0 truncate">
                <span className={op.kind === "remove" ? "line-through" : undefined}>{tagText(op)}</span>
                {op.kind === "replace" && <span className="text-violet-200"> → {op.to}</span>}
                {op.reason && (
                  <span className="copilot-diff-reason" title={op.reason}>
                    {" · "}{op.reason}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {outdated && (
        <div className="copilot-diff-stale" data-copilot-diff-stale="">
          <p className="copilot-diff-stale-text">此建议基于较早的 Prompt</p>
          <button type="button" data-copilot-recheck="" onClick={onRecheck}>
            使用当前 Prompt 重新检查
          </button>
        </div>
      )}
      {!settled && !outdated && (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <button type="button" data-copilot-apply="checked" onClick={onApplyChecked}>
            应用选中项
          </button>
          <button type="button" data-copilot-apply="all" onClick={onApplyAll}>
            应用全部
          </button>
          <button type="button" data-copilot-apply="discard" onClick={onDiscard}>
            放弃
          </button>
        </div>
      )}
      {turn.applied && <p className="m-0 text-[11px] text-emerald-400">已写回工作区</p>}
      {!settled && !outdated && selected > 0 && (
        <span className="sr-only">{selected}</span>
      )}
    </div>
  );
}
