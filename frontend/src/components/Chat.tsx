import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { Button, EmptyState, Spinner } from "./ui/primitives";
import { ContextChips } from "./ContextChips";
import { ApprovalCard } from "./ApprovalCard";

export function Chat() {
  const { messages, thinking, approvals, send, loadDemo } = useStore();
  const [text, setText] = useState("");
  const [loadingDemo, setLoadingDemo] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pending = approvals.filter((a) => !a.answered);

  useEffect(() => { scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" }); }, [messages, pending.length]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || thinking) return;
    setText("");
    void send(t);
  };
  const demo = async () => {
    setLoadingDemo(true);
    const prompt = await loadDemo();
    setLoadingDemo(false);
    setText(prompt);
  };

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && pending.length === 0 && (
          <EmptyState icon="✦" title="Ask Tripwire something"
            hint="It can research the web, read your files, remember things and message you — with every tool call checked." />
        )}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div className={
              m.role === "user" ? "max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-3.5 py-2 text-sm text-white"
              : m.role === "error" ? "max-w-[85%] rounded-2xl border border-danger/40 bg-danger/5 px-3.5 py-2 text-sm text-danger"
              : "max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-line bg-surface-raised px-3.5 py-2 text-sm text-ink"
            }>
              {m.pending ? <Spinner label="Thinking…" /> : m.text}
            </div>
          </div>
        ))}
        {pending.map((a) => <ApprovalCard key={a.id} approval={a} />)}
      </div>

      <div className="border-t border-line bg-surface-raised p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <ContextChips />
          <Button size="sm" variant="ghost" onClick={demo} disabled={loadingDemo}>
            {loadingDemo ? "Loading…" : "Load demo"}
          </Button>
        </div>
        <form onSubmit={submit} className="flex items-end gap-2">
          <textarea
            value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submit(e); }}
            rows={1} placeholder="Message Tripwire…"
            className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-xl border border-line bg-surface px-3 py-2
                       text-sm text-ink outline-none focus:border-brand focus:ring-2 focus:ring-brand/30" />
          <Button type="submit" variant="primary" disabled={thinking || !text.trim()}>Send</Button>
        </form>
      </div>
    </div>
  );
}
