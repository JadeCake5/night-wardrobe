/* Message 外壳：用户轻微衬底，助手扁平无气泡，便于直接嵌入诊断 / Diff / Task。 */

import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
  from: "user" | "assistant" | "error";
};

export function Message({ from, className, children, ...props }: MessageProps) {
  return (
    <div
      className={cn(
        "flex w-full min-w-0 flex-col gap-1.5 text-[13px] leading-relaxed",
        from === "user" && "items-end",
        from === "assistant" && "items-stretch",
        from === "error" && "items-stretch",
        className,
      )}
      data-role={from}
      {...props}
    >
      {children}
    </div>
  );
}

export function MessageContent({
  className,
  from = "assistant",
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { from?: "user" | "assistant" | "error"; children?: ReactNode }) {
  return (
    <div
      className={cn(
        "whitespace-pre-wrap break-words",
        from === "user" && "copilot-user-block max-w-[92%]",
        from === "assistant" && "copilot-assistant-block w-full max-w-none",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
