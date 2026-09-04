import { useState } from "react";
import type { CopilotSession } from "../../types";
import { formatSessionTime, groupSessions } from "../../session";

const RECENT_LIMIT = 8;

type ManagementProps = {
  renamingId: string | null;
  renameValue: string;
  onRenameValue: (value: string) => void;
  onStartRename: (session: CopilotSession) => void;
  onCommitRename: () => void;
  onCancelRename: () => void;
  confirmDeleteId: string | null;
  onAskDelete: (id: string) => void;
  onConfirmDelete: (id: string) => void;
  onCancelDelete: () => void;
};

function filterSessions(sessions: CopilotSession[], search: string): CopilotSession[] {
  const needle = search.trim().toLowerCase();
  if (!needle) return sessions;
  return sessions.filter((item) => (item.title || "").toLowerCase().includes(needle));
}

export function SessionSwitcher({
  sessions,
  activeId,
  search,
  onSearch,
  onSelect,
  onViewAll,
}: {
  sessions: CopilotSession[];
  activeId: string;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onViewAll: () => void;
}) {
  const searching = !!search.trim();
  const filtered = filterSessions(sessions, search);
  const visible = searching ? filtered : filtered.slice(0, RECENT_LIMIT);
  const groups = groupSessions(visible);

  return (
    <div className="copilot-session-pop" data-copilot-session-switcher="" role="listbox">
      <input
        type="search"
        data-copilot-session-search=""
        placeholder="搜索会话…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        autoFocus
      />
      <div className="copilot-session-list">
        {groups.length === 0 && <p className="copilot-session-empty">没有匹配的会话</p>}
        {groups.map((group) => (
          <div key={group.label} className="copilot-session-group">
            <p className="copilot-session-group-label">{group.label}</p>
            {group.items.map((session) => {
              const active = session.id === activeId;
              return (
                <div
                  key={session.id}
                  className={active ? "copilot-session-item is-active" : "copilot-session-item"}
                  data-copilot-session-item={session.id}
                  data-active={active ? "true" : "false"}
                >
                  <button
                    type="button"
                    className="copilot-session-pick"
                    onClick={() => onSelect(session.id)}
                  >
                    <span className="copilot-session-dot" aria-hidden="true" />
                    <span className="copilot-session-name">{session.title || "新会话"}</span>
                    <span className="copilot-session-time">{formatSessionTime(session.updated_at)}</span>
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <button type="button" className="copilot-session-all" data-copilot-history-all="" onClick={onViewAll}>
        <span>查看全部历史</span>
        <span aria-hidden="true">→</span>
      </button>
    </div>
  );
}

export function SessionHistoryView({
  sessions,
  activeId,
  search,
  onSearch,
  onSelect,
  onBack,
  renamingId,
  renameValue,
  onRenameValue,
  onStartRename,
  onCommitRename,
  onCancelRename,
  confirmDeleteId,
  onAskDelete,
  onConfirmDelete,
  onCancelDelete,
}: {
  sessions: CopilotSession[];
  activeId: string;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onBack: () => void;
} & ManagementProps) {
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const filtered = filterSessions(sessions, search);
  const groups = groupSessions(filtered);

  return (
    <div className="copilot-history-view" data-copilot-history-mode="">
      <div className="copilot-history-head">
        <button type="button" data-copilot-history-back="" onClick={onBack}>
          ←
        </button>
        <span className="copilot-history-title">会话历史</span>
      </div>
      <input
        type="search"
        data-copilot-session-search-all=""
        placeholder="搜索会话…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
      />
      <div className="copilot-session-list is-full">
        {groups.length === 0 && <p className="copilot-session-empty">没有匹配的会话</p>}
        {groups.map((group) => (
          <div key={group.label} className="copilot-session-group">
            <p className="copilot-session-group-label">{group.label}</p>
            {group.items.map((session) => {
              const active = session.id === activeId;
              return (
                <div
                  key={session.id}
                  className={active ? "copilot-session-item is-active" : "copilot-session-item"}
                  data-copilot-session-item={session.id}
                  data-active={active ? "true" : "false"}
                >
                  {renamingId === session.id ? (
                    <form
                      className="copilot-session-rename"
                      onSubmit={(e) => {
                        e.preventDefault();
                        onCommitRename();
                      }}
                    >
                      <input
                        data-copilot-session-rename=""
                        value={renameValue}
                        onChange={(e) => onRenameValue(e.target.value)}
                        autoFocus
                      />
                      <button type="submit">保存</button>
                      <button type="button" onClick={onCancelRename}>
                        取消
                      </button>
                    </form>
                  ) : confirmDeleteId === session.id ? (
                    <div className="copilot-session-confirm">
                      <span>确认删除？</span>
                      <button type="button" data-copilot-session-delete-confirm="" onClick={() => onConfirmDelete(session.id)}>
                        删除
                      </button>
                      <button type="button" onClick={onCancelDelete}>
                        取消
                      </button>
                    </div>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="copilot-session-pick"
                        onClick={() => onSelect(session.id)}
                      >
                        <span className="copilot-session-dot" aria-hidden="true" />
                        <span className="copilot-session-name">{session.title || "新会话"}</span>
                        <span className="copilot-session-time">{formatSessionTime(session.updated_at)}</span>
                      </button>
                      <button
                        type="button"
                        className="copilot-session-kebab"
                        data-copilot-session-menu={session.id}
                        aria-label="会话操作"
                        aria-expanded={menuFor === session.id}
                        onClick={() => setMenuFor((cur) => (cur === session.id ? null : session.id))}
                      >
                        ⋯
                      </button>
                    </>
                  )}
                  {menuFor === session.id && renamingId !== session.id && confirmDeleteId !== session.id && (
                    <div className="copilot-session-actions" data-copilot-session-actions={session.id}>
                      <button
                        type="button"
                        data-copilot-session-rename-start=""
                        onClick={() => {
                          setMenuFor(null);
                          onStartRename(session);
                        }}
                      >
                        重命名
                      </button>
                      <button
                        type="button"
                        data-copilot-session-delete=""
                        onClick={() => {
                          setMenuFor(null);
                          onAskDelete(session.id);
                        }}
                      >
                        删除
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
