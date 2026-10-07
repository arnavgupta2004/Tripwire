import { useStore } from "../store";
import { Button, Chip } from "./ui/primitives";

export function ContextChips() {
  const { context, newThread } = useStore();
  const hasTaint = context && (context.untrusted || context.private);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {!hasTaint && <Chip tone="trusted">clean context</Chip>}
      {context?.untrusted && <Chip tone="untrusted">untrusted web content in context</Chip>}
      {context?.private && <Chip tone="private">private data in context</Chip>}
      {hasTaint && (
        <Button size="sm" variant="ghost" onClick={newThread} title="Clear context and start fresh">
          New thread
        </Button>
      )}
    </div>
  );
}
