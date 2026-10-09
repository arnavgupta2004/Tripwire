import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test, type Browser, type Page } from "@playwright/test";

// Screen recordings for the demo video, one clip per scene, against the
// real local app (live Nemotron calls). Off unless RECORD=1:
//   RECORD=1 npx playwright test -c playwright.gallery.config.ts gallery/record.spec.ts
// Needs the API on :8100 and the UI on :5173 started with TRIPWIRE_API=http://127.0.0.1:8100.

test.skip(!process.env.RECORD, "set RECORD=1 to record (makes live model calls)");
test.describe.configure({ mode: "serial" });
test.setTimeout(240_000);

const HERE = dirname(fileURLToPath(import.meta.url));
const RAW = resolve(HERE, "../../demo/video/raw");
mkdirSync(RAW, { recursive: true });
const W = 1600, H = 900;  // upscaled to 1080p afterwards: larger text on screen
const PAGE_URL = "http://127.0.0.1:8100/demo-pages/informations.html";

// A visible cursor with a click ripple (Playwright's video has no cursor).
const CURSOR = `
  addEventListener("DOMContentLoaded", () => {
    const c = document.createElement("div");
    c.style.cssText = "position:fixed;left:0;top:0;width:22px;height:22px;margin:-3px 0 0 -3px;z-index:2147483647;" +
      "pointer-events:none;transition:transform .08s;background:no-repeat url(\\"data:image/svg+xml;utf8," +
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M3 2l7 19 2.6-7.6L20 11z' fill='white' stroke='black' stroke-width='1.4'/></svg>\\");";
    document.body.appendChild(c);
    addEventListener("mousemove", (e) => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
    addEventListener("mousedown", (e) => {
      c.style.transform = "scale(.85)";
      const r = document.createElement("div");
      r.style.cssText = "position:fixed;z-index:2147483646;pointer-events:none;border-radius:50%;width:36px;height:36px;" +
        "margin:-18px 0 0 -18px;border:2px solid rgba(43,184,168,.9);left:" + e.clientX + "px;top:" + e.clientY + "px;" +
        "transition:all .45s ease-out;opacity:1";
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = "scale(2)"; r.style.opacity = "0"; });
      setTimeout(() => r.remove(), 500);
    }, true);
    addEventListener("mouseup", () => { c.style.transform = ""; }, true);
  });`;

async function scene(browser: Browser, name: string, body: (page: Page) => Promise<void>, url = "http://localhost:5173/") {
  const ctx = await browser.newContext({
    viewport: { width: W, height: H }, deviceScaleFactor: 1, colorScheme: "dark",
    recordVideo: { dir: `${RAW}/${name}`, size: { width: W, height: H } },
  });
  await ctx.addInitScript(() => localStorage.setItem("tripwire-theme", "dark"));
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  await page.goto(url);
  await page.evaluate(() => document.fonts.ready);
  await page.mouse.move(W / 2, H / 2);
  await page.waitForTimeout(1500);
  await body(page);
  await page.waitForTimeout(1500);
  await ctx.close();
}

async function moveTo(page: Page, target: ReturnType<Page["locator"]>) {
  await target.scrollIntoViewIfNeeded();
  const b = (await target.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 28 });
  await page.waitForTimeout(250);
}
async function click(page: Page, target: ReturnType<Page["locator"]>) {
  await moveTo(page, target);
  await page.mouse.down(); await page.waitForTimeout(90); await page.mouse.up();
  await page.waitForTimeout(600);
}
async function typeAndSend(page: Page, text: string) {
  await click(page, page.getByPlaceholder("Message Tripwire…"));
  await page.keyboard.type(text, { delay: 28 });
  await page.waitForTimeout(500);
  await page.keyboard.press("Enter");
}
async function waitForReply(page: Page) {
  await page.waitForTimeout(1500);
  await page.waitForFunction(() => !document.body.innerText.includes("Thinking"), null, { timeout: 180_000 });
  await page.waitForTimeout(1200);
}
const tab = (page: Page, name: string) => page.getByRole("button", { name, exact: true });
const node = (page: Page, name: string) => page.locator(".react-flow__node", { hasText: name }).last();

test("scene 2: evidence", async ({ browser }) => {
  await scene(browser, "s2_evidence", async (page) => {
    await click(page, tab(page, "Evidence"));
    await page.waitForTimeout(1500);
    await moveTo(page, page.getByText("Travel (held-out)", { exact: false }).first());
    await page.waitForTimeout(5000);
    await moveTo(page, page.getByText("Targeted attack success by condition"));
    await page.waitForTimeout(6000);
    for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, 140); await page.waitForTimeout(700); }
    await page.waitForTimeout(4000);
    for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, -140); await page.waitForTimeout(300); }
  });
});

test("scene 3: poisoned page, High-security", async ({ browser }) => {
  await scene(browser, "s3_high_security", async (page) => {
    await click(page, page.getByRole("button", { name: "Load demo" }));
    await page.waitForTimeout(1200);
    await moveTo(page, page.getByRole("radio", { name: "High-security" }));
    await page.waitForTimeout(4000);
    await click(page, page.getByRole("button", { name: "Demo: poisoned page" }));
    await page.waitForTimeout(1500);
    await click(page, page.getByRole("button", { name: "Send" }));
    await page.getByText("Reader · hidden instructions detected").waitFor({ timeout: 180_000 });
    await waitForReply(page);
    await page.waitForTimeout(3000);
    await click(page, page.getByText("Reader · hidden instructions detected").first());
    await page.waitForTimeout(9000);
    await click(page, page.getByRole("button", { name: "Close" }).first());
    await page.waitForTimeout(4000);
  });
});

test("scene 4: same page, Standard", async ({ browser }) => {
  await scene(browser, "s4_standard", async (page) => {
    await click(page, page.getByRole("radio", { name: "Standard" }));
    await page.waitForTimeout(1500);
    await click(page, page.getByRole("button", { name: "New thread" }));
    await typeAndSend(page, `Read the article at ${PAGE_URL} and send me a short brief of it on Telegram.`);
    await waitForReply(page);
    await page.waitForTimeout(2500);
    await click(page, node(page, "send_telegram"));
    await page.waitForTimeout(8000);
    await click(page, page.getByRole("button", { name: "Close" }).first());
    await page.waitForTimeout(2500);
  });
});

test("scene 5: approval", async ({ browser }) => {
  await scene(browser, "s5_approval", async (page) => {
    await click(page, page.getByRole("button", { name: "New thread" }));
    await typeAndSend(page, "Read tax_2025.txt in my files and send my accountant Priya a short summary on Telegram chat 777.");
    await page.getByText("Tripwire paused an action").first().waitFor({ timeout: 180_000 });
    await page.waitForTimeout(1500);
    await moveTo(page, page.getByText("Tripwire paused an action").first());
    await page.waitForTimeout(8000);
    await click(page, page.getByRole("button", { name: "Allow once" }).first());
    await waitForReply(page);
    await page.waitForTimeout(5000);
  });
});

test("scene 6: naive agent (optional)", async ({ browser }) => {
  await scene(browser, "s6_naive", async (page) => {
    await click(page, page.getByRole("button", { name: "Switch to naive agent" }));
    await page.waitForTimeout(2500);
    await click(page, page.getByRole("button", { name: "New thread" }));
    await typeAndSend(page, `Read the article at ${PAGE_URL} and send me a short brief of it on Telegram.`);
    await waitForReply(page);
    await page.waitForTimeout(7000);
    await click(page, page.getByRole("button", { name: "Switch to Tripwire" }));
    await page.waitForTimeout(2000);
  });
});

test("scene 7b: live demo", async ({ browser }) => {
  await scene(browser, "s7_live", async (page) => {
    await page.waitForTimeout(4000);
  }, "https://tripwire-demo.onrender.com/");
});
