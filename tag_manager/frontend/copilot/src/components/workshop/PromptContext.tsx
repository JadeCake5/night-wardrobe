const KEYS = ["positive", "negative", "recipe"] as const;
const LABELS: Record<(typeof KEYS)[number], string> = {
  positive: "Positive",
  negative: "Negative",
  recipe: "Recipe",
};

export function PromptContext({
  value,
  onToggle,
}: {
  value: Record<(typeof KEYS)[number], boolean>;
  onToggle: (key: (typeof KEYS)[number]) => void;
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center" role="group" aria-label="随指令一起发送的上下文">
      {KEYS.map((key, i) => {
        const on = value[key];
        return (
          <span key={key} className="inline-flex items-center">
            {i > 0 && (
              <span className="copilot-ctx-sep" aria-hidden="true">
                ·
              </span>
            )}
            <button
              type="button"
              data-copilot-context={key}
              aria-pressed={on}
              onClick={() => onToggle(key)}
            >
              <span className="copilot-ctx-dot" aria-hidden="true" />
              {LABELS[key]}
            </button>
          </span>
        );
      })}
    </div>
  );
}
