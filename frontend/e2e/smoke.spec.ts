import { expect, test } from "@playwright/test";
import { decisionEvent, mockApi } from "./mockApi";

test("sending a message shows the reply and the call in the flow graph", async ({ page }) => {
  await mockApi(page, { chatReply: "Your tax refund is due in October.", chatEvents: [decisionEvent("read_file")] });
  await page.goto("/");
  await page.getByPlaceholder("Message Tripwire…").fill("When is my tax refund due?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("When is my tax refund due?")).toBeVisible();
  await expect(page.getByText("Your tax refund is due in October.")).toBeVisible();
  await expect(page.getByRole("button", { name: "read_file", exact: true })).toBeVisible();
});

test("a blocked call turns red and opens the decision drawer", async ({ page }) => {
  await mockApi(page, {
    chatReply: "I couldn't do that: Tripwire blocked it.",
    chatEvents: [decisionEvent("send_telegram", "BLOCK", {
      rule_id: "R2.private_outbound_untrusted", models: ["ultra"],
      explanation: "The assistant tried to send your tax details to a stranger.",
    })],
  });
  await page.goto("/");
  await page.getByPlaceholder("Message Tripwire…").fill("Send my tax details to chat 666");
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "send_telegram", exact: true }).click();
  await expect(page.getByText("R2.private_outbound_untrusted")).toBeVisible();
  await expect(page.getByText("The assistant tried to send your tax details to a stranger.")).toBeVisible();
  await expect(page.getByText("Blocked", { exact: true })).toBeVisible();
});

test("approval round-trip: Allow once answers the broker and clears the card", async ({ page }) => {
  const state = await mockApi(page, {
    approvals: [{
      id: "ap_1", tool: "send_telegram", args: { chat_id: "777", text: "Tax summary" },
      reason: "send_telegram would send private data to external.",
      explanation: "It would send your tax summary to your accountant.", evidence: "file:tax_2025.txt",
      rule_id: "R2.private_outbound", source: "api", created_at: 0, answered: false,
    }],
  });
  await page.goto("/");
  await expect(page.getByText("Tripwire paused an action").first()).toBeVisible();
  await page.getByRole("button", { name: "Allow once" }).first().click();
  await expect(page.getByText("Tripwire paused an action")).toHaveCount(0);
  expect(state.answers).toEqual([{ id: "ap_1", answer: "allow" }]);
});

test("mode switch flips the header to the naive agent and back", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByText("Protected by Tripwire")).toBeVisible();
  await page.getByRole("button", { name: "Switch to naive agent" }).click();
  await expect(page.getByText("Naive agent — no Tripwire")).toBeVisible();
  await page.getByRole("button", { name: "Switch to Tripwire" }).click();
  await expect(page.getByText("Protected by Tripwire")).toBeVisible();
});

test("Evidence page renders the AgentDojo charts", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Evidence" }).click();
  await expect(page.getByRole("heading", { name: "Evidence: AgentDojo" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Evidence" })).toHaveAttribute("aria-current", "page");
  for (const title of ["Targeted attack success by condition", "Strict vs effective utility (Tripwire)",
                       "What happened to each benign task", "Travel: attack success per goal",
                       "Policy v2 vs v3 (development suites, Tripwire full)"]) {
    await expect(page.getByText(title)).toBeVisible();
  }
  await expect.poll(() => page.locator(".recharts-bar-rectangle").count()).toBeGreaterThan(20);
});

test("phone width: no horizontal page scroll on any screen", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  for (const screen of ["Assistant", "Memory", "Routines", "Evidence"]) {
    await page.getByRole("button", { name: screen, exact: true }).click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${screen} overflows at 375px`).toBeLessThanOrEqual(0);
  }
});

test("reader flag: flagged reader node and a drawer showing only the reader's note", async ({ page }) => {
  await mockApi(page, {
    chatReply: "Here's your brief. The page also contained instructions aimed at AI assistants, which I ignored.",
    chatEvents: [
      decisionEvent("fetch_url", "ALLOW", { rule_id: "R0.trusted_side_effect",
        labels: { data: { confidentiality: "public", integrity: "trusted", sources: ["user"] } } }),
      { kind: "reader", source: "http://127.0.0.1:8000/demo-pages/informations.html", suspicious: true,
        note: "The page asks AI assistants to collect the user's files and post them to an outside website.",
        chunks: 1, ok: true, ts: Date.now() / 1000 },
    ],
  });
  await page.goto("/");
  await page.getByPlaceholder("Message Tripwire…").fill("Read the demo page and send me a brief");
  await page.keyboard.press("Enter");
  const node = page.getByText("Reader · hidden instructions detected — treated as data");
  await expect(node).toBeVisible();
  await node.click();
  await expect(page.getByText("The page asks AI assistants to collect the user's files")).toBeVisible();
  await expect(page.getByText("Hidden instructions detected — treated as data", { exact: true })).toBeVisible();
  await expect(page.getByText("<INFORMATION>")).toHaveCount(0);
});

test("an approved call turns from held to allowed in the graph", async ({ page }) => {
  const held = decisionEvent("send_telegram", "NEEDS_APPROVAL", { rule_id: "R2.private_outbound" });
  const approved = { ...held, verdict: "ALLOW", rule_id: "A0.user_approved", ts: held.ts + 1,
                     reason: "Approved by the user." };
  await mockApi(page, { chatReply: "Sent to Priya.", chatEvents: [held, approved] });
  await page.goto("/");
  await page.getByPlaceholder("Message Tripwire…").fill("Send my tax summary to Priya on chat 777");
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "send_telegram", exact: true }).click();
  await expect(page.getByText("A0.user_approved")).toBeVisible();
  await expect(page.getByText("Allowed", { exact: true })).toBeVisible();
});
