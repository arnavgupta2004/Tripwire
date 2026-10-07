import type { BusEvent, DecisionEvent, BlockExplanationEvent } from "../types";

export type FlowTone = "trusted" | "untrusted" | "private" | "danger" | "approval";

export type DecisionNode = DecisionEvent & { explanation: string | null };

/** The dominant data source feeding a call, used to draw its incoming edge. */
export function sourceOf(e: DecisionEvent): { id: string; label: string; tone: FlowTone } {
  const data = e.labels.data;
  if (data?.confidentiality === "private") return { id: "src-private", label: "Your files & memory", tone: "private" };
  if (data?.integrity === "untrusted") return { id: "src-web", label: "Web / outside content", tone: "untrusted" };
  return { id: "src-you", label: "You", tone: "trusted" };
}

export function edgeTone(e: DecisionEvent): FlowTone {
  if (e.verdict === "BLOCK") return "danger";
  if (e.verdict === "NEEDS_APPROVAL") return "approval";
  const data = e.labels.data;
  if (data?.confidentiality === "private") return "private";
  if (data?.integrity === "untrusted") return "untrusted";
  return "trusted";
}

/** Reduce the raw event list to the decisions shown in the graph, with explanations attached. */
export function decisionsFromEvents(events: BusEvent[]): DecisionNode[] {
  const explanations = new Map<string, string>();
  for (const e of events) {
    if (e.kind === "block_explanation") {
      const be = e as BlockExplanationEvent;
      explanations.set(be.call_id, be.explanation);
    }
  }
  const out: DecisionNode[] = [];
  const seen = new Set<string>();
  for (const e of events) {
    if (e.kind !== "decision") continue;
    const d = e as DecisionEvent;
    if (seen.has(d.call_id)) continue;
    seen.add(d.call_id);
    out.push({ ...d, explanation: d.explanation || explanations.get(d.call_id) || null });
  }
  return out;
}
