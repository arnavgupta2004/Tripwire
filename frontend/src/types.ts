export type LabelFlags = { confidentiality: string; integrity: string; sources: string[] };

export type DecisionEvent = {
  kind: "decision";
  call_id: string;
  tool: string;
  args_summary: string;
  labels: { args?: LabelFlags; context?: LabelFlags; data?: LabelFlags };
  verdict: "ALLOW" | "BLOCK" | "NEEDS_APPROVAL" | "ESCALATE";
  policy_verdict: string;
  rule_id: string;
  reason: string;
  models: string[];
  destination: string | null;
  explanation: string | null;
  evidence: string | null;
  ts: number;
};

export type ModelCallEvent = {
  kind: "model_call";
  tier: "nano" | "super" | "ultra";
  model: string;
  purpose: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  cost_usd: number | null;
  ok: boolean;
  reasoning: boolean;
  error: string | null;
  ts: number;
};

export type EgressEvent = {
  kind: "egress";
  tool: string;
  target: string;
  delivered: boolean;
  note: string;
  preview: string;
  canaries: string[];
  ts: number;
};

export type BlockExplanationEvent = {
  kind: "block_explanation";
  call_id: string;
  explanation: string;
  evidence: string;
  rule_id: string;
  ts: number;
};

export type ReaderEvent = {
  kind: "reader";
  source: string;
  suspicious: boolean;
  note: string;
  chunks: number;
  ok: boolean;
  ts: number;
};

export type ApprovalOpenedEvent = Omit<DecisionEvent, "kind"> & { kind: "approval_opened" };

export type BusEvent =
  | DecisionEvent
  | ModelCallEvent
  | EgressEvent
  | BlockExplanationEvent
  | ReaderEvent
  | ApprovalOpenedEvent;

export type Approval = {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  reason: string;
  explanation: string | null;
  evidence: string | null;
  rule_id: string;
  source: string;
  created_at: number;
  answered: boolean;
};

export type Step = {
  tool: string;
  args: Record<string, unknown>;
  verdict: string;
  rule_id: string;
  reason: string;
  explanation: string | null;
  models: string[];
  shield: boolean;
};

export type ContextLabel = {
  private: boolean; untrusted: boolean; sources: string[]; badge: string;
  thread_started?: number; // seconds since epoch; events before it belong to an earlier thread
};

export type TierUsage = {
  calls: number;
  failed: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
};
export type Usage = {
  tiers: Record<"nano" | "super" | "ultra", TierUsage>;
  total_calls: number;
  total_cost_usd: number;
  headline: string;
};

export type MemoryFact = {
  id: string;
  fact: string;
  trusted: boolean;
  provenance_warning?: string;
  label: LabelFlags;
};
export type Routine = { id: string; kind: string; topic: string; schedule: string };
export type Health = { ok: boolean; shield: boolean; mode: "protected" | "naive"; demo_mode: boolean };
