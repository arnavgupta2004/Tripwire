import type {
  Approval, BusEvent, ContextLabel, Health, MemoryFact, Routine, Step, Usage,
} from "./types";

const BASE = "/api";

/** A random id per browser: the public demo gives each visitor an isolated session. */
export const VISITOR: string = (() => {
  const fresh = () => "v-" + (globalThis.crypto?.randomUUID?.().replace(/-/g, "")
    ?? Math.random().toString(36).slice(2) + Date.now().toString(36));
  try {
    let v = localStorage.getItem("tripwire-visitor");
    if (!v || !/^[A-Za-z0-9_-]{8,64}$/.test(v)) {
      v = fresh();
      localStorage.setItem("tripwire-visitor", v);
    }
    return v;
  } catch {
    return fresh();
  }
})();
const VISITOR_HEADER = { "X-Tripwire-Visitor": VISITOR };

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...VISITOR_HEADER, ...(init?.headers || {}) },
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export type ChatDone = { reply: string; steps: Step[]; limited?: boolean };

/** POST /chat, parsing the SSE stream. Calls onEvent for each bus event; resolves on "done". */
export async function streamChat(
  message: string,
  onEvent: (e: BusEvent) => void,
  signal?: AbortSignal,
): Promise<ChatDone> {
  const res = await fetch(BASE + "/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...VISITOR_HEADER },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`/chat: ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done: ChatDone = { reply: "", steps: [] };
  for (;;) {
    const { value, done: streamDone } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const ev = block.match(/^event: (.*)$/m)?.[1];
      const data = block.match(/^data: (.*)$/m)?.[1];
      if (!data) continue;
      const payload = JSON.parse(data);
      if (ev === "done") done = payload;
      else if (ev === "error") throw new Error(payload.error || "chat failed");
      else onEvent(payload as BusEvent);
    }
  }
  return done;
}

export function connectEvents(onEvent: (e: BusEvent) => void, onStatus?: (up: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${BASE}/events?visitor=${VISITOR}`;
  const open = () => {
    ws = new WebSocket(url);
    ws.onopen = () => onStatus?.(true);
    ws.onmessage = (m) => onEvent(JSON.parse(m.data) as BusEvent);
    ws.onclose = () => {
      onStatus?.(false);
      if (!closed) retry = setTimeout(open, 1500);
    };
    ws.onerror = () => ws?.close();
  };
  open();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    ws?.close();
  };
}

export const api = {
  health: () => j<Health>("/health"),
  usage: () => j<Usage>("/session/usage"),
  context: () => j<ContextLabel>("/session/context"),
  approvals: () => j<Approval[]>("/approvals"),
  answer: (id: string, answer: "allow" | "deny" | "always_deny") =>
    j<{ ok: boolean; accepted: boolean }>(`/approvals/${id}`, {
      method: "POST", body: JSON.stringify({ answer }),
    }),
  memory: () => j<{ facts: MemoryFact[]; tasks: Routine[] }>("/memory"),
  forget: (id: string) => j<{ ok: boolean }>(`/memory/${id}`, { method: "DELETE" }),
  setShield: (on: boolean) => j<{ ok: boolean; shield: boolean; mode: string; error?: string }>("/shield", {
    method: "POST", body: JSON.stringify({ on }),
  }),
  newThread: () => j<{ ok: boolean }>("/thread/new", { method: "POST" }),
  runNow: (topic?: string) => j<{ ok: boolean; reply: string }>("/routines/run_now", { method: "POST", body: JSON.stringify({ topic: topic ?? null }) }),
  loadDemo: () => j<{ ok: boolean; suggested_prompt: string; examples?: { label: string; prompt: string }[];
                     files: string[]; error?: string }>("/demo/load", { method: "POST" }),
};
