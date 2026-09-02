import type { Diagnostic } from "../../types";
import { emitHighlight } from "../../bridge";

const ICONS: Record<Diagnostic["level"], string> = {
  success: "✓",
  info: "ℹ",
  warning: "⚠",
  error: "✕",
};

const LEVEL_CLASS: Record<Diagnostic["level"], string> = {
  success: "text-emerald-400",
  info: "text-sky-400",
  warning: "text-amber-400",
  error: "text-red-400",
};

export function DiagnosisCard({
  host,
  items,
}: {
  host: HTMLElement;
  items: Diagnostic[];
}) {
  if (!items.length) return null;
  return (
    <div className="copilot-section" data-copilot-diagnosis="">
      <p className="copilot-section-title">Prompt 诊断</p>
      <div className="grid gap-0.5">
        {items.map((d) => (
          <button
            key={d.id}
            type="button"
            className="copilot-diag-row"
            data-tag={d.relatedTag || undefined}
            onClick={() => {
              if (d.relatedTag && d.target) emitHighlight(host, d.target, d.relatedTag);
            }}
          >
            <span className={LEVEL_CLASS[d.level]}>{ICONS[d.level]}</span>
            <span>{d.message}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
