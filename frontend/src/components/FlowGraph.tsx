import { useEffect, useMemo } from "react";
import ReactFlow, { Background, Controls, MarkerType, type Edge, type Node, useReactFlow, ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import { useStore } from "../store";
import { cssVar } from "../theme";
import { EmptyState } from "./ui/primitives";
import {
  decisionsFromEvents, edgeTone, readersFromEvents, sourceOf, type FlowTone, type Selection,
} from "./flowModel";

const TONE_VAR: Record<FlowTone, string> = {
  trusted: "--trusted", untrusted: "--untrusted", private: "--private", danger: "--danger", approval: "--untrusted",
};

const baseNode = {
  background: "var(--surface-raised)", color: "var(--ink)", borderRadius: 12, padding: "8px 12px",
  fontSize: 12, fontWeight: 600,
};

function Graph({ onSelect, selectedId }: { onSelect: (s: Selection | null) => void; selectedId?: string }) {
  const { events, theme } = useStore();
  const rf = useReactFlow();
  const decisions = useMemo(() => decisionsFromEvents(events), [events]);
  const readers = useMemo(() => readersFromEvents(events), [events]);

  const { nodes, edges } = useMemo(() => {
    const color = (t: FlowTone) => cssVar(TONE_VAR[t]) || "#888";
    const srcUsed = new Map<string, { label: string; tone: FlowTone }>();
    decisions.forEach((d) => { const s = sourceOf(d); srcUsed.set(s.id, { label: s.label, tone: s.tone }); });
    if (srcUsed.size === 0) srcUsed.set("src-you", { label: "You", tone: "trusted" });

    const nodes: Node[] = [];
    [...srcUsed.keys()].forEach((id, i) => {
      const s = srcUsed.get(id)!;
      nodes.push({
        id, position: { x: 0, y: i * 90 + 20 }, data: { label: s.label }, selectable: false,
        sourcePosition: "right" as any, targetPosition: "left" as any,
        style: { ...baseNode, border: `1.5px solid ${color(s.tone)}`, width: 150 },
      });
    });

    const edges: Edge[] = [];
    const rowOf = new Map<string, number>();
    decisions.forEach((d, i) => {
      rowOf.set(d.call_id, i);
      const tone = edgeTone(d);
      const blocked = d.verdict === "BLOCK";
      const held = d.verdict === "NEEDS_APPROVAL";
      nodes.push({
        id: d.call_id, position: { x: 300, y: i * 72 + 10 }, data: { label: d.tool },
        sourcePosition: "right" as any, targetPosition: "left" as any,
        style: {
          ...baseNode, width: 170,
          border: `2px solid ${blocked ? color("danger") : held ? color("approval") : "var(--line)"}`,
          boxShadow: d.call_id === selectedId ? `0 0 0 3px ${color(tone)}44` : undefined,
        },
        className: blocked ? "animate-pulseRed" : undefined,
      });
      const s = sourceOf(d);
      edges.push({
        id: `e-${d.call_id}`, source: s.id, target: d.call_id, animated: !blocked && !held,
        style: { stroke: color(tone), strokeWidth: blocked ? 3 : 2, strokeDasharray: held ? "5 4" : undefined },
        markerEnd: { type: MarkerType.ArrowClosed, color: color(tone) },
        className: blocked ? "animate-pulseRed" : undefined,
      });
    });

    // Reader passes sit to the right of the fetch that produced them.
    const perParent = new Map<string, number>();
    readers.forEach((r) => {
      const parent = r.parent && rowOf.has(r.parent) ? r.parent : null;
      const k = parent ?? "none";
      const n = perParent.get(k) ?? 0;
      perParent.set(k, n + 1);
      const row = parent ? rowOf.get(parent)! : decisions.length;
      nodes.push({
        id: r.id, position: { x: 560, y: row * 72 + 10 + n * 56 },
        data: { label: r.suspicious ? "Reader · hidden instructions detected — treated as data" : "Reader · nothing suspicious" },
        sourcePosition: "right" as any, targetPosition: "left" as any,
        style: {
          ...baseNode, width: 230, fontSize: 11,
          border: `2px solid ${r.suspicious ? color("untrusted") : "var(--line)"}`,
          background: r.suspicious ? `${color("untrusted")}18` : "var(--surface-raised)",
          boxShadow: r.id === selectedId ? `0 0 0 3px ${color("untrusted")}44` : undefined,
        },
        className: r.suspicious ? "animate-readerFlag" : undefined,
      });
      if (parent) {
        edges.push({
          id: `e-${r.id}`, source: parent, target: r.id,
          style: { stroke: r.suspicious ? color("untrusted") : "var(--line)", strokeWidth: 2,
                   strokeDasharray: "3 3" },
          markerEnd: { type: MarkerType.ArrowClosed, color: r.suspicious ? color("untrusted") : "#999" },
        });
      }
    });
    return { nodes, edges };
  }, [decisions, readers, selectedId, theme]);

  useEffect(() => { const t = setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 60); return () => clearTimeout(t); },
    [nodes.length, rf]);

  if (decisions.length === 0 && readers.length === 0) {
    return <EmptyState icon="◇" title="No activity yet"
      hint="Ask the assistant to do something. Each tool call appears here, colored by the data flowing through it." />;
  }
  const decisionById = new Map(decisions.map((d) => [d.call_id, d]));
  const readerById = new Map(readers.map((r) => [r.id, r]));
  const select = (id: string) => {
    const d = decisionById.get(id);
    if (d) return onSelect({ type: "decision", node: d });
    const r = readerById.get(id);
    if (r) return onSelect({ type: "reader", node: r });
  };
  return (
    <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => select(n.id)} onEdgeClick={(_, e) => select(e.target)}
      nodesConnectable={false} nodesDraggable={false} minZoom={0.3}>
      <Background gap={18} color="var(--line)" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export function FlowGraph(props: { onSelect: (s: Selection | null) => void; selectedId?: string }) {
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}
