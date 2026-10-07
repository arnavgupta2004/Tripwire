import type { Page } from "@playwright/test";

/** In-browser stand-in for the FastAPI backend. Mutable so tests can drive it. */
export type MockState = {
  mode: "protected" | "naive";
  approvals: Record<string, unknown>[];
  answers: { id: string; answer: string }[];
  chatReply: string;
  chatEvents: Record<string, unknown>[];
};

export function decisionEvent(tool: string, verdict = "ALLOW", extra: Record<string, unknown> = {}) {
  return {
    kind: "decision", call_id: `c_${tool}_${Math.random().toString(36).slice(2, 7)}`, tool,
    args_summary: "{}", verdict, policy_verdict: verdict, rule_id: "R4.read_only_trusted",
    reason: `${tool} is read-only and the context is trusted.`, models: [], destination: null,
    explanation: null, evidence: null, ts: Date.now() / 1000,
    labels: { data: { confidentiality: "private", integrity: "trusted", sources: ["file:tax_2025.txt"] } },
    ...extra,
  };
}

const ZERO_TIER = { calls: 0, failed: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0, latency_p50_ms: 0, latency_p95_ms: 0 };

export async function mockApi(page: Page, overrides: Partial<MockState> = {}): Promise<MockState> {
  const state: MockState = {
    mode: "protected", approvals: [], answers: [], chatReply: "Done.", chatEvents: [], ...overrides,
  };
  await page.routeWebSocket("**/api/events", () => { /* accepted, silent */ });
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^\/api/, "");
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/health") return json({ ok: true, shield: state.mode === "protected", mode: state.mode, demo_mode: true });
    if (path === "/session/usage") {
      return json({ tiers: { nano: ZERO_TIER, super: ZERO_TIER, ultra: ZERO_TIER }, total_calls: 0,
                    total_cost_usd: 0, headline: "" });
    }
    if (path === "/session/context") return json({ private: false, untrusted: false, sources: [], badge: "" });
    if (path === "/memory") return json({ facts: [], tasks: [] });
    if (path === "/approvals") return json(state.approvals);
    if (path.startsWith("/approvals/") && req.method() === "POST") {
      const id = path.split("/")[2];
      state.answers.push({ id, answer: JSON.parse(req.postData() || "{}").answer });
      state.approvals = state.approvals.filter((a) => a.id !== id);
      return json({ ok: true, accepted: true });
    }
    if (path === "/shield") {
      const on = JSON.parse(req.postData() || "{}").on;
      state.mode = on ? "protected" : "naive";
      return json({ ok: true, shield: on, mode: state.mode });
    }
    if (path === "/chat") {
      const blocks = state.chatEvents.map((e) => `event: ${e.kind}\ndata: ${JSON.stringify(e)}\n\n`).join("");
      const done = `event: done\ndata: ${JSON.stringify({ reply: state.chatReply, steps: [] })}\n\n`;
      return route.fulfill({ contentType: "text/event-stream", body: blocks + done });
    }
    return json({ ok: true });
  });
  return state;
}
