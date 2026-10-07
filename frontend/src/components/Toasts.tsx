import { useStore } from "../store";
import { ApprovalCard } from "./ApprovalCard";

/** Pending approvals mirrored as toasts in the corner (also shown inline in chat). */
export function Toasts() {
  const { approvals } = useStore();
  const pending = approvals.filter((a) => !a.answered);
  if (pending.length === 0) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2">
      {pending.slice(-2).map((a) => (
        <div key={a.id} className="pointer-events-auto">
          <ApprovalCard approval={a} compact />
        </div>
      ))}
    </div>
  );
}
