import { useState } from "react";
import { Chat } from "../components/Chat";
import { FlowGraph } from "../components/FlowGraph";
import { Drawer } from "../components/Drawer";
import type { Selection } from "../components/flowModel";

export function Assistant() {
  const [selected, setSelected] = useState<Selection | null>(null);
  const selectedId = selected ? (selected.type === "decision" ? selected.node.call_id : selected.node.id) : undefined;
  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="min-h-0 border-b border-line lg:border-b-0 lg:border-r">
        <Chat />
      </section>
      <section className="relative min-h-[18rem]">
        <div className="absolute left-3 top-3 z-10 text-xs font-semibold uppercase tracking-wide text-ink-faint">
          Flow graph
        </div>
        <FlowGraph onSelect={setSelected} selectedId={selectedId} />
      </section>
      <Drawer selection={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
