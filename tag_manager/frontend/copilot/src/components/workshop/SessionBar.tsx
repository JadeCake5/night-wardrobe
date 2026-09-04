import { useEffect, useRef } from "react";
import type { CopilotSession } from "../../types";
import { SessionSwitcher } from "./SessionSwitcher";

export function SessionBar({
  sessions,
  active,
  open,
  onToggle,
  onClose,
  onNew,
  search,
  onSearch,
  onSelect,
  onViewAll,
}: {
  sessions: CopilotSession[];
  active: CopilotSession | null;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onNew: () => void;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onViewAll: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, onClose]);

  return (
    <div className="copilot-session-bar" data-copilot-session-bar="" ref={rootRef}>
      <button
        type="button"
        className="copilot-session-current"
        data-copilot-session-current=""
        aria-expanded={open}
        aria-haspopup="listbox"
        title={active?.title || "新会话"}
        onClick={onToggle}
      >
        <span className="copilot-session-current-label">{active?.title || "新会话"}</span>
        <span className="copilot-session-chevron" aria-hidden="true">▾</span>
      </button>
      <button
        type="button"
        className="copilot-session-new"
        data-copilot-session-new=""
        title="新建会话"
        aria-label="新建会话"
        onClick={onNew}
      >
        ＋
      </button>
      {open && (
        <SessionSwitcher
          sessions={sessions}
          activeId={active?.id || ""}
          search={search}
          onSearch={onSearch}
          onSelect={onSelect}
          onViewAll={onViewAll}
        />
      )}
    </div>
  );
}
