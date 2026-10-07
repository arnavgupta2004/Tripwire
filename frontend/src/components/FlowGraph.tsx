import { useEffect, useMemo } from "react";
import ReactFlow, { Background, Controls, MarkerType, type Edge, type Node, useReactFlow, ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import { useStore } from "../store";
import { cssVar } from "../theme";
import { EmptyState } from "./ui/primitives";
import { decisionsFromEvents, edgeTone, sourceOf, type DecisionNode, type FlowTone } from "./flowModel";

const TONE_VAR: Record<FlowTone, string> = {
  trusted: "--trusted", untrusted: "--untrusted", private: "--private", danger: "--danger", approval: "--untrusted",
};

function Graph({ onSelect, selectedId }: { onSelect: (d: DecisionNode | null) => void; selectedId?: string }) {
  const { events, theme } = useStore();
  const rf = useReactFlow();
  const decisions = useMemo(() => decisionsFromEvents(events), [events]);

  const { nodes, edges } = useMemo(() => {
    const color = (t: FlowTone) => cssVar(TONE_VAR[t]) || "#888";
    const srcUsed = new Map<string, { label: string; tone: FlowTone }>();
    decisions.forEach((d) => { const s = sourceOf(d); srcUsed.set(s.id, { label: s.label, tone: s.tone }); });
    if (srcUsed.size === 0) srcUsed.set("src-you", { label: "You", tone: "trusted" });

    const srcIds = [...srcUsed.keys()];
    const nodes: Node[] = [];
    srcIds.forEach((id, i) => {
      const s = srcUsed.get(id)!;
      nodes.push({
        id, position: { x: 0, y: i * 90 + 20 }, data: { label: s.label }, sourcePosition: "right" as any,
        targetPosition: "left" as any, selectable: false,
        style: {
          border: `1.5px solid ${color(s.tone)}`, background: "var(--surface-raised)", color: "var(--ink)",
          borderRadius: 12, padding: "8px 12px", fontSize: 12, fontWeight: 600, width: 150,
        },
      });
    });
    const edges: Edge[] = [];
    decisions.forEach((d, i) => {
      const tone = edgeTone(d);
      const blocked = d.verdict === "BLOCK";
      const held = d.verdict === "NEEDS_APPROVAL";
      nodes.push({
        id: d.call_id, position: { x: 300, y: i * 72 + 10 },
        data: { label: `${d.tool}` }, selected: d.call_id === selectedId,
        sourcePosition: "right" as any, targetPosition: "left" as any,
        style: {
          border: `2px solid ${blocked ? color("danger") : held ? color("approval") : "var(--line)"}`,
          background: "var(--surface-raised)", color: "var(--ink)", borderRadius: 12,
          padding: "8px 12px", fontSize: 12, fontWeight: 600, width: 170,
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
    return { nodes, edges };
  }, [decisions, selectedId, theme]);

  useEffect(() => { const t = setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 60); return () => clearTimeout(t); },
    [nodes.length, rf]);

  if (decisions.length === 0) {
    return <EmptyState icon="◇" title="No activity yet"
      hint="Ask the assistant to do something. Each tool call appears here, colored by the data flowing through it." />;
  }
  const byId = new Map(decisions.map((d) => [d.call_id, d]));
  return (
    <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => onSelect(byId.get(n.id) || null)}
      onEdgeClick={(_, e) => onSelect(byId.get(e.target) || null)}
      nodesConnectable={false} nodesDraggable={false} minZoom={0.3}>
      <Background gap={18} color="var(--line)" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export function FlowGraph(props: { onSelect: (d: DecisionNode | null) => void; selectedId?: string }) {
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}
