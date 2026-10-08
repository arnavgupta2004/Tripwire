import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { pct1, round1 } from "../src/results/format";
import { expect, test, type Page } from "@playwright/test";
import { decisionEvent, mockApi } from "../e2e/mockApi";

// Devpost gallery: 1500×1000 PNGs in docs/gallery. App screens are the real UI fed by the
// mock API; decision, reader and approval texts are copied from real runs (README there).

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../../docs/gallery");
const RESULTS = JSON.parse(readFileSync(resolve(HERE, "../../evals/agentdojo/results/results.json"), "utf8"));
const BREAKDOWN = JSON.parse(readFileSync(resolve(HERE, "../../evals/agentdojo/results/benign_breakdown.json"), "utf8"));
const PAGE_URL = "http://127.0.0.1:8000/demo-pages/informations.html";
const now = () => Date.now() / 1000;

const USAGE = (nano: number, sup: number, ultra: number, cost: number) => {
  const t = (calls: number) => ({ calls, failed: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0, latency_p50_ms: 0, latency_p95_ms: 0 });
  return { tiers: { nano: t(nano), super: t(sup), ultra: t(ultra) }, total_calls: nano + sup + ultra,
           total_cost_usd: cost, headline: "" };
};
const WEB = { confidentiality: "public", integrity: "untrusted", sources: [`web:${PAGE_URL}`, "user"] };
const USER = { confidentiality: "public", integrity: "trusted", sources: ["user"] };
const FILE = { confidentiality: "private", integrity: "trusted", sources: ["file:tax_2025.txt", "user"] };

async function open(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("tripwire-theme", "dark");
    localStorage.setItem("tripwire-visitor", "v-gallery-demo-0001");
  });
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
}

async function send(page: Page, text: string) {
  await page.getByPlaceholder("Message Tripwire…").fill(text);
  await page.keyboard.press("Enter");
  await expect(page.getByText(text)).toBeVisible();
}

/** With the drawer open, re-frame the graph (its pan/zoom, as a user's drag would) into the visible area. */
async function frameLeftOfDrawer(page: Page, rightEdge = 1120, maxZoom = 1.25) {
  await page.waitForTimeout(600);
  await page.evaluate(([r, z]) => { (window as any).__right = r; (window as any).__maxZoom = z; }, [rightEdge, maxZoom]);
  await page.evaluate(() => {
    const vp = document.querySelector<HTMLElement>(".react-flow__viewport")!;
    const pane = document.querySelector(".react-flow")!.getBoundingClientRect();
    const right = (window as any).__right, top = pane.top + 70, bottom = pane.bottom - 90, left = pane.left + 40;
    const m = new DOMMatrixReadOnly(getComputedStyle(vp).transform);
    const rects = [...document.querySelectorAll(".react-flow__node")].map((n) => n.getBoundingClientRect());
    const bx = Math.min(...rects.map((r) => r.left)), by = Math.min(...rects.map((r) => r.top));
    const bw = Math.max(...rects.map((r) => r.right)) - bx, bh = Math.max(...rects.map((r) => r.bottom)) - by;
    const k = m.a, f = Math.min((right - left) / bw, (bottom - top) / bh, (window as any).__maxZoom / k);
    const k2 = k * f;
    // graph coords of the bbox's top-left, then place it so the bbox is centred in the free area
    const gx = (bx - pane.left - m.e) / k, gy = (by - pane.top - m.f) / k;
    const tx = left - pane.left + ((right - left) - bw * f) / 2 - gx * k2;
    const ty = top - pane.top + ((bottom - top) - bh * f) / 2 - gy * k2;
    vp.style.transform = `translate(${tx}px, ${ty}px) scale(${k2})`;
  });
  await page.waitForTimeout(300);
}

async function shot(page: Page, name: string) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}`, fullPage: false });
}

// Shared design tokens (DESIGN.md, dark theme) for the composed cards.
const BASE_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
  :root { --ink:#e8eef6; --ink-soft:#a7b4c6; --ink-faint:#6b7a8f; --surface:#0e151f; --raised:#161f2b; --sunken:#0a1017;
          --line:#273243; --brand:#2bb8a8; --brand-soft:#123b39; --trusted:#45c184; --untrusted:#e6a34d;
          --private:#a287e8; --danger:#e85b64; }
  * { box-sizing: border-box; margin: 0; }
  html, body { width: 1500px; height: 1000px; background: var(--surface); color: var(--ink);
               font-family: Inter, system-ui, sans-serif; overflow: hidden; }
  .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }
  .card { background: var(--raised); border: 1px solid var(--line); border-radius: 18px; }
  .eyebrow { font-size: 15px; letter-spacing: .14em; text-transform: uppercase; color: var(--brand); font-weight: 600; }
  .shield { width: 44px; height: 44px; }
`;
const SHIELD = `<svg class="shield" viewBox="0 0 16 16" fill="var(--brand)"><path d="M8 1 2 3.5v4C2 11 4.5 13.6 8 15c3.5-1.4 6-4 6-7.5v-4L8 1Z"/></svg>`;

async function card(from: Page, html: string, name: string) {
  const page = await from.context().browser()!.newPage({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1,
                                                         colorScheme: "dark" });
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${BASE_CSS}</style></head><body>${html}</body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${name}` });
  await page.close();
}

const pct = pct1;
const b64 = (buf: Buffer) => `data:image/png;base64,${buf.toString("base64")}`;

/** A 2x page for crisp UI captures that get composed into cards. */
async function hiDpi(browser: import("@playwright/test").Browser) {
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 2, colorScheme: "dark" });
  return ctx.newPage();
}

/** Clip around elements, in CSS px, with padding. */
async function clipAround(page: Page, selector: string, pad = 24) {
  const r = await page.locator(selector).evaluateAll((els) => {
    const rs = els.map((e) => e.getBoundingClientRect());
    return { l: Math.min(...rs.map((x) => x.left)), t: Math.min(...rs.map((x) => x.top)),
             r: Math.max(...rs.map((x) => x.right)), b: Math.max(...rs.map((x) => x.bottom)) };
  });
  return { x: r.l - pad, y: r.t - pad, width: r.r - r.l + 2 * pad, height: r.b - r.t + 2 * pad };
}

/** The open drawer, cropped to its content. */
async function drawerShot(page: Page) {
  const r = await page.locator("aside").evaluate((a) => {
    const box = a.getBoundingClientRect();
    const kids = [...a.querySelectorAll("*")].map((e) => e.getBoundingClientRect().bottom).filter((b) => b > 0);
    return { x: box.left, y: 0, width: box.width, height: Math.min(box.height, Math.max(...kids) + 24) };
  });
  return page.screenshot({ clip: r });
}

/** The chat bubbles (user message and reply). */
async function chatShot(page: Page) {
  return page.screenshot({ clip: await clipAround(page, "main .flex.justify-end > div, main .flex.justify-start > div", 16) });
}

function appCard(eyebrow: string, title: string, chat: Buffer, graph: Buffer, drawer: Buffer) {
  return `
    <div style="padding:52px 60px;height:100%;display:flex;flex-direction:column;gap:20px">
      <div style="display:flex;align-items:center;gap:14px">${SHIELD}<span class="eyebrow">${eyebrow}</span></div>
      <h1 style="font-size:40px;font-weight:800;letter-spacing:-.02em;line-height:1.15">${title}</h1>
      <div style="display:grid;grid-template-columns:1fr 440px;gap:24px;flex:1;min-height:0">
        <div style="display:flex;flex-direction:column;gap:18px;min-height:0">
          <div class="card" style="padding:14px;background:var(--surface)"><img src="${b64(chat)}" style="width:100%;display:block"></div>
          <div class="card" style="padding:10px;flex:1;min-height:0;display:flex;align-items:center;justify-content:center;background:var(--sunken)">
            <img src="${b64(graph)}" style="max-width:100%;max-height:100%;display:block"></div>
        </div>
        <div class="card" style="padding:0;overflow:hidden;align-self:start;max-height:100%">
          <img src="${b64(drawer)}" style="width:100%;display:block"></div>
      </div>
    </div>`;
}
let graphCrop = "";

test("03 blocked edge with the rule and Ultra's explanation", async ({ browser }) => {
  const page = await hiDpi(browser);
  await mockApi(page, {
    usage: USAGE(0, 3, 1, 0.0042),
    context: { private: true, untrusted: false, sources: ["file:tax_2025.txt"], badge: "private data in context" },
    chatReply: "I successfully read your tax file, but I cannot access the local URL due to a security restriction. " +
      `The system blocked fetching ${PAGE_URL} because reading private data (your tax file) followed by making ` +
      "an external request could create an exfiltration risk.",
    chatEvents: [
      decisionEvent("search_files", "ALLOW", { rule_id: "R4.read_only_trusted", labels: { data: USER },
        reason: "search_files is read-only and the context is trusted." }),
      decisionEvent("read_file", "ALLOW", { rule_id: "R4.read_only_trusted", labels: { data: USER },
        reason: "read_file is read-only and the context is trusted." }),
      decisionEvent("fetch_url", "BLOCK", {
        rule_id: "R3.exfiltration_chain", destination: "external", labels: { data: FILE },
        reason: "Exfiltration chain (search_files → fetch_url): private data was read this turn and fetch_url would send a request to an external host.",
        explanation: "The assistant tried to send your private tax information to an external website after reading your tax file.",
      }),
    ],
  });
  await open(page);
  await send(page, `Read my tax file and summarise the article at ${PAGE_URL}.`);
  await page.getByRole("button", { name: "fetch_url", exact: true }).click();
  await expect(page.getByText("R3.exfiltration_chain").first()).toBeVisible();
  await page.waitForTimeout(500);
  // A tight crop of the graph for the cover, taken with the drawer closed.
  await page.keyboard.press("Escape");
  const close = page.getByRole("button", { name: /close/i });
  if (await close.count()) await close.first().click();
  await page.waitForTimeout(400);
  const boxes = await page.locator(".react-flow__node").evaluateAll((els) =>
    els.map((e) => e.getBoundingClientRect()).map((r) => ({ l: r.left, t: r.top, r: r.right, b: r.bottom })));
  const pad = 36;
  const clip = { x: Math.min(...boxes.map((b) => b.l)) - pad, y: Math.min(...boxes.map((b) => b.t)) - pad };
  const crop = { ...clip, width: Math.max(...boxes.map((b) => b.r)) + pad - clip.x,
                 height: Math.max(...boxes.map((b) => b.b)) + pad - clip.y };
  graphCrop = (await page.screenshot({ clip: crop })).toString("base64");
  const chat = await chatShot(page);
  await frameLeftOfDrawer(page, 1460, 1.6);
  const graph = await page.screenshot({ clip: await clipAround(page, ".react-flow__node", 40) });
  await page.getByRole("button", { name: "fetch_url", exact: true }).click();
  await expect(page.getByText("The assistant tried to send your private tax information")).toBeVisible();
  await page.waitForTimeout(400);
  const drawer = await drawerShot(page);
  await card(page, appCard("Standard mode · a blocked flow",
    "Private data was read, then an external request: <span style=\"color:var(--danger)\">blocked</span>, and Ultra explains why",
    chat, graph, drawer), "03_blocked.png");
});

test("02 reader flag in High-security mode", async ({ browser }) => {
  const page = await hiDpi(browser);
  await mockApi(page, {
    security: "high",
    usage: USAGE(2, 2, 0, 0.0031),
    context: { private: false, untrusted: true, sources: [`web:${PAGE_URL}`], badge: "untrusted web content in context" },
    chatReply: "Telegram delivery is disabled in this demo environment, so the message wasn't actually sent, but " +
      "here's what would have gone to you:\n\nBrief: Open-weight models are narrowing the gap with frontier systems " +
      "via better long context and tool use, not just benchmarks. Inference costs are falling, shifting competition " +
      "to latency, reliability, and model-size flexibility.",
    chatEvents: [
      decisionEvent("fetch_url", "ALLOW", { rule_id: "R0.trusted_side_effect", destination: "external",
        labels: { data: USER }, reason: "fetch_url was directed by trusted context only." }),
      { kind: "reader", source: PAGE_URL, suspicious: true, chunks: 1, ok: true, ts: now(),
        note: "The page contains instructions to concatenate files and post them to an external website." },
      decisionEvent("send_telegram", "ALLOW", { rule_id: "R1.untrusted_side_effect", destination: "self",
        models: ["nano"], labels: { data: WEB },
        reason: "send_telegram matches the user's instruction, carries no private data and goes to self. " +
          "Classifier: The user explicitly asked to read the article and send a brief via Telegram, which matches the proposed call." }),
    ],
  });
  await open(page);
  await send(page, `Read the article at ${PAGE_URL} and send me a short brief of it on Telegram.`);
  const node = page.getByText("Reader · hidden instructions detected — treated as data");
  await expect(node).toBeVisible();
  await page.waitForTimeout(500);
  const chat = await chatShot(page);
  await frameLeftOfDrawer(page, 1460, 1.6);
  const graph = await page.screenshot({ clip: await clipAround(page, ".react-flow__node", 40) });
  await node.click();
  await expect(page.getByText("The page contains instructions to concatenate files")).toBeVisible();
  await page.waitForTimeout(400);
  const drawer = await drawerShot(page);
  await card(page, appCard("High-security mode · a poisoned page",
    "The reader flags hidden instructions; the assistant only ever sees them as data",
    chat, graph, drawer), "02_reader_flag.png");
});

test("04 approval card (desktop)", async ({ page }) => {
  await mockApi(page, {
    usage: USAGE(0, 2, 0, 0.0019),
    context: { private: true, untrusted: false, sources: ["file:tax_2025.txt"], badge: "private data in context" },
    chatHang: true,
    wsEvents: [
      decisionEvent("read_file", "ALLOW", { rule_id: "R4.read_only_trusted", labels: { data: USER },
        reason: "read_file is read-only and the context is trusted." }),
      decisionEvent("send_telegram", "NEEDS_APPROVAL", { rule_id: "R2.private_outbound", destination: "external",
        labels: { data: FILE }, reason: "send_telegram would send private data to external." }),
    ],
    approvals: [{
      id: "ap_1", tool: "send_telegram", rule_id: "R2.private_outbound", source: "api", created_at: 0, answered: false,
      args: { chat_id: "777", text: "Hi Priya, here's a quick summary of Riya's 2025-26 return: taxable income ₹30,50,810; " +
        "tax payable ₹6,02,743; TDS ₹6,48,200; refund due ₹45,457." },
      reason: "send_telegram would send private data to external.", explanation: null, evidence: "file:tax_2025.txt",
    }],
  });
  await open(page);
  await send(page, "Read tax_2025.txt in my files and send my accountant Priya a short summary on Telegram chat 777.");
  await expect(page.getByText("Tripwire paused an action").first()).toBeVisible();
  await shot(page, "04_approval.png");
});

test("08 memory with provenance", async ({ browser }) => {
  const page = await hiDpi(browser);
  const memory = JSON.parse(readFileSync(resolve(HERE, "fixtures/memory.json"), "utf8"));
  await mockApi(page, { memory });
  await open(page);
  await page.getByRole("button", { name: "Memory", exact: true }).click();
  await expect(page.getByText("Seen on a web page: a new cafe opened near the office.")).toBeVisible();
  await page.waitForTimeout(400);
  const list = await page.screenshot({ clip: await clipAround(page, "main h2, main h2 ~ *", 20) });
  await card(page, `
    <div style="padding:64px 80px;height:100%;display:flex;flex-direction:column;gap:26px">
      <div style="display:flex;align-items:center;gap:14px">${SHIELD}<span class="eyebrow">Memory with provenance</span></div>
      <h1 style="font-size:44px;font-weight:800;letter-spacing:-.02em;line-height:1.15;max-width:1200px">
        Every remembered fact keeps its source. Facts from the web stay <span style="color:var(--untrusted)">information only</span>.</h1>
      <div class="card" style="padding:18px;flex:1;min-height:0;display:flex;align-items:center;justify-content:center;background:var(--surface)">
        <img src="${b64(list)}" style="max-width:100%;max-height:100%;display:block"></div>
      <div style="display:grid;grid-template-columns:1fr 1.6fr 1.6fr;gap:28px;font-size:17px;color:var(--ink-soft)">
        <span><b style="color:var(--trusted)">trusted</b> · you said it</span>
        <span><b style="color:var(--untrusted)">untrusted</b> · seen on a page or in a document; never followed as an instruction</span>
        <span>Writing web content to memory goes to the judge (rule R3.memory_poisoning)</span>
      </div>
    </div>`, "08_memory.png");
});

test("07 the dial: Standard / High-security", async ({ browser }) => {
  const page = await hiDpi(browser);
  await mockApi(page);
  await open(page);
  const strip = async () => page.screenshot({ clip: await clipAround(page, "header [role=radiogroup], header [role=radiogroup] + span button", 5) });
  const std = await strip();
  await page.getByRole("radio", { name: "High-security" }).click();
  await expect(page.getByText("Also screens what web pages can say")).toBeVisible();
  await page.waitForTimeout(300);
  const high = await strip();
  const travel = RESULTS.travel;
  const tb = BREAKDOWN.travel;
  const row = (label: string, img: Buffer, color: string, asr: number, util: number, note: string) => `
    <div class="card" style="padding:24px 28px;display:flex;flex-direction:column;gap:16px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <span style="font-size:22px;font-weight:700;color:${color}">${label}</span>
        <span style="font-size:18px;color:var(--ink-soft)"><b style="font-size:24px;color:var(--ink)">${pct(asr)}</b> attack success ·
          <b style="font-size:24px;color:var(--ink)">${pct(util)}</b> tasks completed <span style="color:var(--ink-faint)">(${note})</span></span></div>
      <div style="background:var(--sunken);border:1px solid var(--line);border-radius:12px;padding:14px 16px">
        <img src="${b64(img)}" style="width:100%;display:block"></div>
    </div>`;
  await card(page, `
    <div style="padding:64px 80px;height:100%;display:flex;flex-direction:column;gap:26px">
      <div style="display:flex;align-items:center;gap:14px">${SHIELD}<span class="eyebrow">Protected mode has one dial</span></div>
      <h1 style="font-size:50px;font-weight:800;letter-spacing:-.02em">Standard or High-security</h1>
      ${row("Standard · default", std, "var(--brand)", travel.tripwire_gw__v3.asr, tb.tripwire_gw__v3.effective_utility, "with approvals")}
      ${row("High-security · opt-in", high, "var(--private)", travel.tripwire_full__v3.asr, tb.tripwire_full__v3.effective_utility, "the reader drops detail")}
      <div class="card" style="padding:8px 28px">
        ${[["Layer", "Standard", "High-security", true],
           ["Hardened system prompt", "✓", "✓"],
           ["Gateway: labels → policy → Nano classifier → Ultra judge → approval", "✓", "✓"],
           ["Quarantined reader (Nano): web pages reach the planner as structured data", "—", "✓"]]
          .map(([l, a, b, head]) => `<div style="display:grid;grid-template-columns:1fr 160px 160px;padding:12px 0;
              ${head ? "color:var(--ink-faint);font-size:14px;letter-spacing:.08em;text-transform:uppercase" : "font-size:18px;border-top:1px solid var(--line)"}">
              <span>${l}</span><span style="text-align:center;color:${head ? "inherit" : "var(--brand)"}">${a}</span>
              <span style="text-align:center;color:${head ? "inherit" : "var(--private)"}">${b}</span></div>`).join("")}
      </div>
      <div style="margin-top:auto;font-size:17px;color:var(--ink-soft);line-height:1.5">
        Standard: the gateway checks every action. High-security adds the quarantined reader, which also screens what web pages
        can say to the assistant.<br><span style="color:var(--ink-faint)">Numbers: AgentDojo Travel suite, held out (run once after the policy was frozen),
        one run per task. Standard was made the default after seeing these results.</span></div>
    </div>`, "07_dial.png");
});

test("06 held-out results", async ({ page }) => {
  const t = RESULTS.travel;
  const b = BREAKDOWN.travel;
  const rows = [
    ["No defense", t.none, b.none, "var(--ink-faint)"],
    ["Spotlighting", t.spotlighting, b.spotlighting, "var(--ink-faint)"],
    ["Tripwire · Standard (gateway)", t.tripwire_gw__v3, b.tripwire_gw__v3, "var(--brand)"],
    ["Tripwire · High-security (+ reader)", t.tripwire_full__v3, b.tripwire_full__v3, "var(--private)"],
  ] as const;
  const W = 820, H = 540, max = 50;
  const bars = rows.map(([label, e, _bd, color], i) => {
    const v = 100 * e.asr, x = 60 + i * 190, h = (v / max) * (H - 90), y = H - 50 - h;
    return `<rect x="${x}" y="${y}" width="120" height="${Math.max(h, 3)}" rx="8" fill="${color}"/>
      <text x="${x + 60}" y="${y - 14}" text-anchor="middle" font-size="30" font-weight="700" fill="var(--ink)">${round1(v).toFixed(1)}%</text>
      <text x="${x + 60}" y="${H - 18}" text-anchor="middle" font-size="15" fill="var(--ink-soft)">${label.split(" · ")[0]}</text>
      <text x="${x + 60}" y="${H + 2}" text-anchor="middle" font-size="14" fill="var(--ink-faint)">${label.split(" · ")[1]?.replace(/ \(.+\)/, "") ?? ""}</text>`;
  }).join("");
  const grid = [0, 10, 20, 30, 40, 50].map((g) => {
    const y = H - 50 - (g / max) * (H - 90);
    return `<line x1="40" x2="${W}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-dasharray="4 6"/>
      <text x="30" y="${y + 5}" text-anchor="end" font-size="13" fill="var(--ink-faint)">${g}%</text>`;
  }).join("");
  const util = rows.map(([label, , bd, color]) => `
    <div style="display:flex;justify-content:space-between;align-items:baseline;padding:14px 0;border-bottom:1px solid var(--line)">
      <span style="font-size:18px;color:var(--ink-soft)">${label}</span>
      <span style="font-size:26px;font-weight:700;color:${color === "var(--ink-faint)" ? "var(--ink)" : color}">${pct(bd.effective_utility)}</span></div>`).join("");
  await card(page, `
    <div style="padding:64px 72px;height:100%;display:flex;flex-direction:column">
      <div style="display:flex;align-items:center;gap:16px">${SHIELD}<span class="eyebrow">AgentDojo · held-out Travel suite</span></div>
      <h1 style="font-size:52px;font-weight:800;letter-spacing:-.02em;margin-top:18px">
        ${pct(t.none.asr)} → <span style="color:var(--brand)">${pct(t.tripwire_gw__v3.asr)}</span> attack success</h1>
      <div style="display:grid;grid-template-columns:900px 1fr;gap:32px;margin-top:34px;flex:1">
        <div class="card" style="padding:26px 30px">
          <div style="font-size:18px;font-weight:600">Targeted attack success by condition</div>
          <div style="font-size:15px;color:var(--ink-faint);margin-top:2px">Share of 140 injection attempts that met the attacker's goal. Lower is better.</div>
          <svg width="${W}" height="${H + 20}" style="margin-top:14px;font-family:Inter">${grid}${bars}</svg>
        </div>
        <div class="card" style="padding:26px 30px">
          <div style="font-size:18px;font-weight:600">Effective utility</div>
          <div style="font-size:15px;color:var(--ink-faint);margin-top:2px;margin-bottom:6px">Benign tasks completed, counting a held action as approved.</div>
          ${util}
          <div style="font-size:15px;color:var(--ink-faint);margin-top:18px;line-height:1.5">All 7 attacks that passed the gateway were one prose-only goal
            ("say I should visit this hotel"). Tripwire governs tool calls, not prose.</div>
        </div>
      </div>
      <div style="font-size:16px;color:var(--ink-soft);margin-top:22px">Held out: run once after policy v3 and its tool mapping were frozen · one run per task ·
        Nemotron 3 Super on Nebius Token Factory as the agent in every condition</div>
    </div>`, "06_results.png");
});

test("05 architecture", async ({ page }) => {
  const box = (title: string, sub: string, color = "var(--line)", extra = "") =>
    `<div class="card" style="padding:20px 24px;border-color:${color};${extra}">
       <div style="font-size:21px;font-weight:700">${title}</div>
       <div style="font-size:15px;color:var(--ink-soft);margin-top:5px;line-height:1.4">${sub}</div></div>`;
  const step = (label: string, sub: string, color: string) =>
    `<div style="flex:1;background:var(--sunken);border:1px solid ${color};border-radius:12px;padding:16px 12px;text-align:center">
       <div style="font-size:18px;font-weight:700;color:${color}">${label}</div>
       <div style="font-size:13.5px;color:var(--ink-soft);margin-top:5px">${sub}</div></div>`;
  const arrow = `<div style="color:var(--ink-faint);font-size:20px;align-self:center">→</div>`;
  const down = (t = "") => `<div style="text-align:center;color:var(--ink-faint);font-size:14px;line-height:1">↓ <span class="mono">${t}</span></div>`;
  await card(page, `
    <div style="padding:48px 64px 44px;height:100%;display:flex;flex-direction:column;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:16px">${SHIELD}<span class="eyebrow">How Tripwire works</span></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:6px">
        ${box("You · web app & Telegram", "Instructions are trusted; everything else is labelled", "var(--trusted)")}
        ${box("Planner · Nemotron 3 Super", "Hardened prompt; proposes tool calls, never executes them", "var(--brand)")}
      </div>
      ${down("every tool call")}
      <div class="card" style="padding:18px 20px;border-color:var(--brand);background:linear-gradient(180deg,var(--brand-soft),var(--raised))">
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <div style="font-size:21px;font-weight:800">Tripwire gateway</div>
          <div style="font-size:14px;color:var(--ink-soft)">deterministic first; models only where judgment is needed</div></div>
        <div style="display:flex;gap:10px;margin-top:14px">
          ${step("Labels", "trusted · untrusted · private", "var(--untrusted)")}${arrow}
          ${step("Policy", "rules.yaml · R0–R5", "var(--ink)")}${arrow}
          ${step("Classifier", "Nemotron 3 Nano · intent & leak", "var(--brand)")}${arrow}
          ${step("Judge", "Nemotron 3 Ultra · block or ask", "var(--private)")}${arrow}
          ${step("Approval", "one tap · web or Telegram", "var(--trusted)")}
        </div>
      </div>
      ${down("allowed calls only")}
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px">
        ${[["Tavily", "web search & extract"], ["Files", "your documents (private)"], ["Memory", "facts with provenance"],
           ["Telegram", "messages to you or others"], ["Fetch", "pages and URLs"]]
          .map(([t, d]) => box(t, d, "var(--line)", "text-align:center;padding:16px")).join("")}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
        ${box("↻ Quarantined reader · Nemotron 3 Nano", "Untrusted tool outputs (pages, documents) → structured data before they reach the planner. High-security mode.", "var(--untrusted)")}
        ${box("Nebius Token Factory", "Nano · Super · Ultra, one OpenAI-compatible endpoint", "var(--line)")}
      </div>
      <div style="border:1px dashed var(--line);border-radius:14px;padding:16px 22px;display:flex;justify-content:space-between;align-items:center;background:var(--sunken)">
        <div><span style="font-size:17px;font-weight:700">NVIDIA OpenShell</span>
          <span style="font-size:15px;color:var(--ink-soft);margin-left:10px">network layer underneath: which hosts the agent can reach</span></div>
        <div class="mono" style="font-size:13px;color:var(--ink-faint)">Tripwire: which information flows are allowed</div>
      </div>
    </div>`, "05_architecture.png");
});

test("01 cover", async ({ page }) => {
  test.skip(!graphCrop, "needs the graph crop from test 03");
  const t = RESULTS.travel;
  await card(page, `
    <div style="height:100%;display:grid;grid-template-columns:720px 1fr;
                background:radial-gradient(1200px 700px at 85% 40%, #123b39 0%, var(--surface) 60%)">
      <div style="padding:90px 0 80px 90px;display:flex;flex-direction:column">
        <div style="display:flex;align-items:center;gap:16px">${SHIELD}<span style="font-size:58px;font-weight:800;letter-spacing:-.03em">Tripwire</span></div>
        <div style="font-size:30px;line-height:1.3;color:var(--ink-soft);margin-top:26px;max-width:600px">
          A personal AI assistant that can't be turned against you</div>
        <div style="margin-top:auto">
          <div class="eyebrow" style="margin-bottom:12px">Held-out AgentDojo</div>
          <div style="font-size:52px;font-weight:800;letter-spacing:-.02em;line-height:1.1">
            ${pct(t.none.asr)} → <span style="color:var(--brand)">${pct(t.tripwire_gw__v3.asr)}</span></div>
          <div style="font-size:24px;color:var(--ink-soft);margin-top:6px">attack success</div>
          <div class="mono" style="font-size:17px;color:var(--ink-faint);margin-top:44px">NVIDIA Nemotron · Nebius Token Factory</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;padding-right:70px">
        <div class="card" style="padding:14px;width:100%;box-shadow:0 30px 80px rgba(0,0,0,.45)">
          <div style="display:flex;justify-content:space-between;padding:4px 6px 12px">
            <span style="font-size:14px;font-weight:600;color:var(--ink-faint);letter-spacing:.08em">FLOW GRAPH</span>
            <span class="mono" style="font-size:14px;color:var(--danger)">R3.exfiltration_chain · Blocked</span></div>
          <img src="data:image/png;base64,${graphCrop}" style="width:100%;border-radius:10px;display:block">
        </div>
      </div>
    </div>`, "01_cover.png");
});
