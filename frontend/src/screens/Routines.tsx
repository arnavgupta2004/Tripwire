import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useAsync } from "../useAsync";
import { Button, EmptyState, ErrorState, Spinner } from "../components/ui/primitives";

function nextRun(schedule: string): string {
  const [h, m] = schedule.split(":").map(Number);
  if (Number.isNaN(h)) return schedule;
  const now = new Date();
  const next = new Date();
  next.setHours(h, m || 0, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  const day = next.toDateString() === now.toDateString() ? "today" : "tomorrow";
  return `${day} at ${schedule}`;
}

export function Routines() {
  const { runNow, thinking } = useStore();
  const { data, loading, error, reload } = useAsync(() => api.memory(), []);
  const [ran, setRan] = useState<string | null>(null);
  if (loading) return <div className="grid h-full place-items-center"><Spinner label="Loading routines…" /></div>;
  if (error) return <ErrorState message="Could not load routines." onRetry={reload} />;
  const tasks = data?.tasks || [];

  const run = async (topic: string) => { setRan(null); await runNow(topic); setRan(topic); reload(); };
  const forget = async (id: string) => { await api.forget(id); reload(); };

  return (
    <div className="mx-auto max-w-2xl p-4 sm:p-6">
      <h2 className="mb-1 text-lg font-bold">Routines</h2>
      <p className="mb-4 text-sm text-ink-soft">
        Standing tasks that run on a schedule — each one goes through the same gateway as a live request.
        Say “every morning brief me on X” in chat to add one.
      </p>
      {tasks.length === 0 ? (
        <EmptyState icon="⟳" title="No routines yet" hint="Ask Tripwire to brief you every morning on a topic." />
      ) : (
        <ul className="space-y-2">
          {tasks.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 rounded-xl border border-line
                                      bg-surface-raised p-3 shadow-card">
              <div>
                <p className="text-sm font-medium text-ink">Daily brief · {t.topic}</p>
                <p className="text-xs text-ink-faint">Next run {nextRun(t.schedule)}</p>
                {ran === t.topic && <p className="mt-0.5 text-xs text-trusted">Ran just now — check your chat.</p>}
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="primary" disabled={thinking} onClick={() => run(t.topic)}>Run now</Button>
                <Button size="sm" variant="ghost" onClick={() => forget(t.id)}>Delete</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
