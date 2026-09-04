import { useState } from "react";
import type { ContextSnapshot } from "../../types";
import { snapshotHasContent } from "../../session";

const LABELS: Array<{ key: keyof ContextSnapshot; label: string }> = [
  { key: "character", label: "角色" },
  { key: "outfit", label: "服装" },
  { key: "artist", label: "画师" },
  { key: "scene", label: "场景" },
  { key: "negative_template", label: "负面模板" },
  { key: "positive_preview", label: "当时 Positive" },
  { key: "negative_preview", label: "当时 Negative" },
];

export function OldContextNotice({ snapshot }: { snapshot: ContextSnapshot }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="copilot-old-ctx" data-copilot-old-context="">
      <div className="copilot-old-ctx-line">
        <span className="copilot-old-ctx-icon" aria-hidden="true">◷</span>
        <div className="copilot-old-ctx-text">
          <p className="copilot-old-ctx-title">此会话基于较早的 Prompt 上下文</p>
          <p className="copilot-old-ctx-body">当前工作区已发生变化。AI 后续回复将优先使用当前工作区内容。</p>
        </div>
        {snapshotHasContent(snapshot) && (
          <button
            type="button"
            data-copilot-old-context-toggle=""
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "收起旧上下文" : "查看旧上下文"}
          </button>
        )}
      </div>
      {open && (
        <dl className="copilot-old-ctx-dl" data-copilot-old-context-body="">
          {LABELS.map((item) => {
            const value = (snapshot[item.key] || "").trim();
            if (!value) return null;
            return (
              <div key={item.key}>
                <dt>{item.label}</dt>
                <dd title={value}>{value}</dd>
              </div>
            );
          })}
        </dl>
      )}
    </div>
  );
}
