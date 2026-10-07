import { useState } from "react";
import { Chat } from "../components/Chat";
import { FlowGraph } from "../components/FlowGraph";
import { Drawer } from "../components/Drawer";
import type { DecisionNode } from "../components/flowModel";

export function Assistant() {
  const [selected, setSelected] = useState<DecisionNode | null>(null);
  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="min-h-0 border-b border-line lg:border-b-0 lg:border-r">
        <Chat />
      </section>
      <section className="relative min-h-[18rem]">
        <div className="absolute left-3 top-3 z-10 text-xs font-semibold uppercase tracking-wide text-ink-faint">
          Flow graph
        </div>
        <FlowGraph onSelect={setSelected} selectedId={selected?.call_id} />
      </section>
      <Drawer decision={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
