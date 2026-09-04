export type Action =
  | "diagnose"
  | "reduce_conflicts"
  | "dedupe"
  | "improve_pose"
  | "improve_composition"
  | "enrich_environment"
  | "optimize_negative"
  | "freeform";

export type PromptOperation =
  | { kind: "add"; target: "positive" | "negative"; tag: string; category?: string; reason?: string }
  | { kind: "remove"; target: "positive" | "negative"; tag: string; reason?: string }
  | { kind: "replace"; target: "positive" | "negative"; from: string; to: string; reason?: string };

export type Diagnostic = {
  id: string;
  level: "success" | "info" | "warning" | "error";
  message: string;
  relatedTag?: string;
  target?: "positive" | "negative";
};

export type ExecutionStage = { label: string; detail?: string };

export type PromptRequest = {
  action: Action;
  positive: string;
  negative: string;
  recipe: Record<string, number>;
  customInstruction?: string;
  contexts?: Array<"positive" | "negative" | "recipe">;
  history?: Array<{ role: "user" | "assistant"; text: string }>;
  session_id?: string;
};

export type ToolSummary = {
  name: string;
  status: string;
  summary: string;
  result_summary?: string;
};

export type PromptSuggestion = {
  id: string;
  action: Action;
  summary: string;
  operations: PromptOperation[];
  diagnostics?: Diagnostic[];
  stages?: ExecutionStage[];
  tools?: ToolSummary[];
  session_id?: string;
  user_message_id?: string;
  assistant_message_id?: string;
};

export type Turn = {
  id: string;
  role: "user" | "assistant" | "error";
  text?: string;
  action?: Action;
  contexts?: Array<"positive" | "negative" | "recipe">;
  status?: "pending" | "done";
  suggestion?: PromptSuggestion;
  tools?: ToolSummary[];
  applied?: boolean;
  discarded?: boolean;
  checked?: boolean[];
};

export type PromptContextPayload = {
  positivePrompt?: string;
  negativePrompt?: string;
  positive?: string;
  negative?: string;
  recipe?: Record<string, number>;
};

export type ContextSnapshot = {
  character: string;
  outfit: string;
  artist: string;
  scene: string;
  negative_template: string;
  positive_preview: string;
  negative_preview: string;
};

export type MessagePart = {
  type: "text" | "diagnosis" | "diff" | "tool" | "execution" | "error";
  data: Record<string, unknown>;
};

export type CopilotSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  context_snapshot: ContextSnapshot;
  metadata?: Record<string, unknown>;
  parent_session_id?: string | null;
};

export type CopilotMessage = {
  id: string;
  session_id: string;
  seq: number;
  role: "user" | "assistant" | "error";
  content: {
    id?: string;
    role?: string;
    text?: string;
    created_at?: string;
    action?: Action;
    contexts?: Array<"positive" | "negative" | "recipe">;
    suggestion_id?: string;
    applied?: boolean;
    discarded?: boolean;
    checked?: boolean[];
    parts?: MessagePart[];
  };
  created_at: string;
};

export class CopilotRequestError extends Error {
  session_id?: string;
  user_message_id?: string;
  assistant_message_id?: string;
  status?: number;
}
