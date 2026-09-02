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
};

export type PromptSuggestion = {
  id: string;
  action: Action;
  summary: string;
  operations: PromptOperation[];
  diagnostics?: Diagnostic[];
  stages?: ExecutionStage[];
};

export type Turn = {
  id: string;
  role: "user" | "assistant" | "error";
  text?: string;
  action?: Action;
  contexts?: Array<"positive" | "negative" | "recipe">;
  status?: "pending" | "done";
  suggestion?: PromptSuggestion;
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
