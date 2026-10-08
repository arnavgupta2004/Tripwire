import { useState } from "react";
import type { Approval } from "../types";
import { useStore } from "../store";
import { Button, Chip } from "./ui/primitives";

export function ApprovalCard({ approval, compact }: { approval: Approval; compact?: boolean }) {
  const { answer, health } = useStore();
  const [busy, setBusy] = useState(false);
  const act = async (a: "allow" | "deny" | "always_deny") => {
    setBusy(true);
    await answer(approval.id, a);
  };
  return (
    <div className="animate-riseIn rounded-xl border border-untrusted/40 bg-untrusted/5 p-3 shadow-card">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-sm font-semibold text-ink">Tripwire paused an action</span>
        <Chip tone="neutral" mono>{approval.tool}</Chip>
      </div>
      <p className="text-sm text-ink-soft">{approval.explanation || approval.reason}</p>
      {approval.evidence && (
        <p className="mt-1 text-xs text-ink-faint">
          Source: <span className="font-mono">{approval.evidence}</span>
        </p>
      )}
      {!compact && (
        <pre className="mt-2 overflow-x-auto rounded-lg bg-surface-sunken p-2 text-xs text-ink-soft">
          {Object.entries(approval.args).map(([k, v]) => `${k}: ${String(v)}`).join("\n")}
        </pre>
      )}
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={busy} onClick={() => act("allow")}>Allow once</Button>
        <Button size="sm" disabled={busy} onClick={() => act("deny")}>Deny</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("always_deny")}>
          Always deny this
        </Button>
      </div>
      {!health?.public_demo && (
        <p className="mt-1.5 text-[11px] text-ink-faint">You can also answer from Telegram — the first answer wins.</p>
      )}
    </div>
  );
}
