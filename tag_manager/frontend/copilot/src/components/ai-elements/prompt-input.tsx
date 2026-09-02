/* 精简 PromptInput：自增长 / Enter 发送 / Shift+Enter 换行。
 * 视觉上整个 Composer 是一块 surface，textarea 不再自带边框。 */

import type { ButtonHTMLAttributes, FormEvent, KeyboardEvent, ReactNode, TextareaHTMLAttributes } from "react";
import { useLayoutEffect, useRef } from "react";
import { cn } from "@/lib/utils";

const COMPOSER_MAX_PX = 220;

export type PromptInputMessage = { text: string };

export function PromptInput({
  className,
  children,
  onSubmit,
}: {
  className?: string;
  children: ReactNode;
  onSubmit: (message: PromptInputMessage) => void;
}) {
  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const ta = form.querySelector("textarea");
    const text = ta?.value.trim() || "";
    if (!text) return;
    onSubmit({ text });
  }

  return (
    <form
      data-copilot-composer=""
      className={cn("w-full min-w-0", className)}
      onSubmit={handleSubmit}
    >
      {children}
    </form>
  );
}

export function PromptInputBody({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div data-copilot-composer-body="" className={cn("flex w-full min-w-0 flex-col", className)}>
      {children}
    </div>
  );
}

export function PromptInputFooter({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-copilot-composer-footer=""
      className={cn("flex w-full min-w-0 items-end justify-between gap-2", className)}
    >
      {children}
    </div>
  );
}

export function PromptInputTextarea({
  className,
  onSubmitShortcut,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  onSubmitShortcut?: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, COMPOSER_MAX_PX) + "px";
  }, [props.value]);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    props.onKeyDown?.(e);
    if (e.key !== "Enter" || e.shiftKey) return;
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    onSubmitShortcut?.();
  }

  return (
    <textarea
      {...props}
      ref={ref}
      rows={1}
      className={cn(
        "w-full min-h-[108px] max-h-[220px] resize-none overflow-y-auto border-0 bg-transparent text-[13px] leading-relaxed text-foreground shadow-none outline-none",
        className,
      )}
      onKeyDown={onKeyDown}
    />
  );
}

export function PromptInputSubmit({
  disabled,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="submit"
      disabled={disabled}
      aria-label="发送"
      title="发送（Enter）"
      className={cn("inline-flex size-8 shrink-0 items-center justify-center", className)}
      {...props}
    >
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 19V5" />
        <path d="M5 12l7-7 7 7" />
      </svg>
    </button>
  );
}
