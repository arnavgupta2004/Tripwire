import type { DecisionNode } from "./flowModel";
import { Chip } from "./ui/primitives";

const VERDICT_TONE: Record<string, "trusted" | "untrusted" | "danger"> = {
  ALLOW: "trusted", NEEDS_APPROVAL: "untrusted", BLOCK: "danger",
};
const VERDICT_LABEL: Record<string, string> = {
  ALLOW: "Allowed", NEEDS_APPROVAL: "Held for your approval", BLOCK: "Blocked",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-t border-line py-2.5 first:border-t-0">
      <span className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <div className="text-sm text-ink">{children}</div>
    </div>
  );
}

export function Drawer({ decision, onClose }: { decision: DecisionNode | null; onClose: () => void }) {
  if (!decision) return null;
  const d = decision;
  const tone = VERDICT_TONE[d.verdict] || "untrusted";
  const data = d.labels.data;
  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/20" onClick={onClose} />
      <aside className="animate-slideIn fixed right-0 top-0 z-40 flex h-full w-[22rem] max-w-[90vw] flex-col
                        border-l border-line bg-surface-raised shadow-drawer">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="font-mono text-sm font-semibold">{d.tool}</span>
          <button onClick={onClose} className="text-ink-faint hover:text-ink" aria-label="Close">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto px-4">
          <Row label="Decision"><Chip tone={tone}>{VERDICT_LABEL[d.verdict] || d.verdict}</Chip></Row>
          <Row label="Rule"><span className="font-mono text-xs">{d.rule_id}</span></Row>
          <Row label="Reason">{d.reason}</Row>
          {d.explanation && (
            <Row label="Tripwire judge (Ultra)">
              <span className="text-ink-soft">{d.explanation}</span>
            </Row>
          )}
          {d.evidence && <Row label="Source"><span className="font-mono text-xs break-all">{d.evidence}</span></Row>}
          {data && (
            <Row label="Data labels">
              <div className="flex flex-wrap gap-1.5">
                <Chip tone={data.integrity === "untrusted" ? "untrusted" : "trusted"}>{data.integrity}</Chip>
                <Chip tone={data.confidentiality === "private" ? "private" : "neutral"}>{data.confidentiality}</Chip>
              </div>
            </Row>
          )}
          <Row label="Models used">
            {d.models.length ? (
              <div className="flex flex-wrap gap-1.5">
                {d.models.map((m, i) => <Chip key={i} tone="brand" mono>{m}</Chip>)}
              </div>
            ) : <span className="text-ink-faint">none (deterministic rule)</span>}
          </Row>
          {d.destination && <Row label="Destination">{d.destination}</Row>}
          <div className="h-6" />
        </div>
      </aside>
    </>
  );
}
