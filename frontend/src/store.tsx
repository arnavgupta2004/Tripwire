import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, connectEvents, streamChat } from "./api";
import type { Approval, BusEvent, ContextLabel, Health, Usage } from "./types";
import { applyTheme, initialTheme, type Theme } from "./theme";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  pending?: boolean;
};

type State = {
  health: Health | null;
  usage: Usage | null;
  context: ContextLabel | null;
  events: BusEvent[];
  approvals: Approval[];
  messages: ChatMessage[];
  thinking: boolean;
  wsUp: boolean;
  theme: Theme;
};

type Store = State & {
  send: (text: string) => Promise<void>;
  answer: (id: string, ans: "allow" | "deny" | "always_deny") => Promise<void>;
  setShield: (on: boolean) => Promise<string | null>;
  newThread: () => Promise<void>;
  loadDemo: () => Promise<string>;
  demoExamples: { label: string; prompt: string }[];
  runNow: (topic?: string) => Promise<void>;
  toggleTheme: () => void;
  clearEvents: () => void;
};

const Ctx = createContext<Store | null>(null);
export const useStore = () => {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside provider");
  return s;
};

const uid = () => Math.random().toString(36).slice(2, 10);
const eventKey = (e: BusEvent) =>
  `${e.kind}:${(e as any).call_id || (e as any).tool || ""}:${(e as any).ts}`;

export function StoreProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [context, setContext] = useState<ContextLabel | null>(null);
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [thinking, setThinking] = useState(false);
  const [wsUp, setWsUp] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme());
  const [demoExamples, setDemoExamples] = useState<{ label: string; prompt: string }[]>([]);
  const seen = useRef<Set<string>>(new Set());

  useEffect(() => applyTheme(theme), [theme]);

  const refreshLight = useCallback(async () => {
    try { setUsage(await api.usage()); } catch { /* ignore */ }
    try { setContext(await api.context()); } catch { /* ignore */ }
    try { setApprovals(await api.approvals()); } catch { /* ignore */ }
  }, []);

  const addEvent = useCallback((e: BusEvent) => {
    const key = eventKey(e);
    if (seen.current.has(key)) return;
    seen.current.add(key);
    setEvents((prev) => [...prev.slice(-400), e]);
    if (e.kind === "model_call") api.usage().then(setUsage).catch(() => {});
    if (e.kind === "approval_opened") api.approvals().then(setApprovals).catch(() => {});
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    refreshLight();
    const off = connectEvents(addEvent, setWsUp);
    const poll = setInterval(() => api.approvals().then(setApprovals).catch(() => {}), 2500);
    return () => { off(); clearInterval(poll); };
  }, [addEvent, refreshLight]);

  const send = useCallback(async (text: string) => {
    const userMsg: ChatMessage = { id: uid(), role: "user", text };
    const pendingId = uid();
    setMessages((m) => [...m, userMsg, { id: pendingId, role: "assistant", text: "", pending: true }]);
    setThinking(true);
    try {
      const done = await streamChat(text, addEvent);
      setMessages((m) => m.map((msg) => msg.id === pendingId
        ? { ...msg, text: done.reply || "(no reply)", pending: false } : msg));
    } catch (err) {
      setMessages((m) => m.map((msg) => msg.id === pendingId
        ? { id: msg.id, role: "error", text: "Something went wrong handling that message." } : msg));
    } finally {
      setThinking(false);
      refreshLight();
    }
  }, [addEvent, refreshLight]);

  const answer = useCallback(async (id: string, ans: "allow" | "deny" | "always_deny") => {
    setApprovals((a) => a.map((x) => x.id === id ? { ...x, answered: true } : x));
    try { await api.answer(id, ans); } finally { refreshLight(); }
  }, [refreshLight]);

  const setShield = useCallback(async (on: boolean) => {
    const res = await api.setShield(on);
    if (!res.ok) return res.error || "Could not switch mode.";
    setHealth((h) => h ? { ...h, shield: res.shield, mode: res.mode as Health["mode"] } : h);
    return null;
  }, []);

  const newThread = useCallback(async () => {
    await api.newThread();
    setMessages([]);
    setEvents([]);
    seen.current = new Set();
    refreshLight();
  }, [refreshLight]);

  const loadDemo = useCallback(async () => {
    const res = await api.loadDemo();
    setDemoExamples(res.examples || []);
    setMessages([]); setEvents([]); seen.current = new Set();
    await refreshLight();
    return res.suggested_prompt || "";
  }, [refreshLight]);

  const runNow = useCallback(async (topic?: string) => {
    setThinking(true);
    try { await api.runNow(topic); } finally { setThinking(false); refreshLight(); }
  }, [refreshLight]);

  const value = useMemo<Store>(() => ({
    health, usage, context, events, approvals, messages, thinking, wsUp, theme, demoExamples,
    send, answer, setShield, newThread, loadDemo, runNow,
    toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    clearEvents: () => { setEvents([]); seen.current = new Set(); },
  }), [health, usage, context, events, approvals, messages, thinking, wsUp, theme, demoExamples,
       send, answer, setShield, newThread, loadDemo, runNow]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
