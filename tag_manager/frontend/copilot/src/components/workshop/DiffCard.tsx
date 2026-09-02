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
  onToggle,
  onApplyChecked,
  onApplyAll,
  onDiscard,
}: {
  turn: Turn;
  onToggle: (index: number) => void;
  onApplyChecked: () => void;
  onApplyAll: () => void;
  onDiscard: () => void;
}) {
  const suggestion = turn.suggestion;
  if (!suggestion || !suggestion.operations.length) return null;
  const settled = !!(turn.applied || turn.discarded);
  const title = turn.applied ? "已应用的修改" : turn.discarded ? "已放弃的建议" : "建议修改";
  const selected = suggestion.operations.filter((_, i) => turn.checked?.[i] !== false).length;

  return (
    <div className={`copilot-section ${settled ? "is-settled" : ""}`} data-copilot-diff="">
      <p className="copilot-section-title">{title}</p>
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
                disabled={settled}
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
      {!settled && (
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
      {!settled && selected > 0 && (
        <span className="sr-only">{selected}</span>
      )}
    </div>
  );
}
