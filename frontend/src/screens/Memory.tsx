import { api } from "../api";
import { useAsync } from "../useAsync";
import { Button, Chip, EmptyState, ErrorState, Spinner } from "../components/ui/primitives";

export function Memory() {
  const { data, loading, error, reload } = useAsync(() => api.memory(), []);
  if (loading) return <div className="grid h-full place-items-center"><Spinner label="Loading memory…" /></div>;
  if (error) return <ErrorState message="Could not load memory." onRetry={reload} />;
  const facts = data?.facts || [];

  const forget = async (id: string) => { await api.forget(id); reload(); };

  return (
    <div className="mx-auto max-w-2xl p-4 sm:p-6">
      <h2 className="mb-1 text-lg font-bold">Memory</h2>
      <p className="mb-4 text-sm text-ink-soft">
        What Tripwire remembers. Facts from untrusted sources are kept as information only and are never
        treated as instructions.
      </p>
      {facts.length === 0 ? (
        <EmptyState icon="❖" title="Nothing remembered yet"
          hint="Ask Tripwire to remember something, or load the demo." />
      ) : (
        <ul className="space-y-2">
          {facts.map((f) => (
            <li key={f.id} className="flex items-start justify-between gap-3 rounded-xl border border-line
                                      bg-surface-raised p-3 shadow-card">
              <div className="min-w-0">
                <p className="text-sm text-ink">{f.fact}</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Chip tone={f.trusted ? "trusted" : "untrusted"}>{f.trusted ? "trusted" : "untrusted"}</Chip>
                  {!f.trusted && <Chip tone="untrusted">information only</Chip>}
                  {f.label.sources.map((s, i) => <Chip key={i} tone="neutral" mono>{s}</Chip>)}
                </div>
              </div>
              <Button size="sm" variant="ghost" onClick={() => forget(f.id)} title="Forget this">Delete</Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
