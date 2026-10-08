# Public demo on Render: end-to-end checks

- URL: https://tripwire-demo.onrender.com
- Date: 2026-10-08
- Build: commit 8ef341f (first deploy); the phone-layout fixes in c4b6b37 were re-checked after redeploy.
- Browser: the Claude desktop app's built-in browser. It had never visited the site, so it started with no stored visitor ID.
- Host: Render free web service (Docker, Frankfurt). Spend caps are persisted in a secret GitHub gist.

| # | Check | Result |
|---|---|---|
| 0 | `/healthz`, `/api/health` | **Pass.** `{"ok":true,"public_demo":true}`. Budget reported $0.75/day and $15 lifetime. |
| 1 | Load demo, then "Demo: poisoned page" | **Pass.** The graph showed `fetch_url` and the reader node "hidden instructions detected — treated as data". No unrequested tool calls were made. |
| 2 | "Tripwire is strict" | **Pass.** `fetch_url` was blocked by `R3.exfiltration_chain`. The drawer showed Ultra's explanation: "The assistant tried to send your private tax information to an external website after reading your tax file." It also listed "Models used: none for the decision (deterministic rule); Ultra wrote the explanation afterwards". |
| 3 | Approval card | **Pass.** In check 1's run, `send_telegram` was held for approval, because the brief quoted the page's hidden instruction. Allow once resumed the same turn, and the reply said Telegram delivery is off in the demo, so nothing was delivered. |
| 4 | Evidence page | **Pass.** It rendered 15 charts and 46 bars, with no horizontal page scroll at 283 px. |
| 5 | Phone width (375×812) | **Pass.** No horizontal page scroll (`scrollWidth` = 375). The tabs scroll sideways inside the header. |
| WS | WebSocket `/api/events` through Render | **Pass.** The connection opened (readyState 1) and delivered 11 events (`model_call`, `decision`, `egress`, `reader`, `approval_opened`). During the turn, the graph updated before the reply arrived. |
| SSE | Streaming `/api/chat` through Render | **Pass.** The response was `text/event-stream`. In the strict example, events arrived at 977, 1901, 4134 and 4345 ms. Render's proxy didn't buffer them. |
| Caps | Persistence across a redeploy | **Pass.** Spend was $0.0143 before redeploying and $0.0143 after (both today and lifetime). |

## Observations

- **Variable outcome for check 1:** in the five earlier local runs, `send_telegram` to self was allowed under R1. Here it was escalated, because the model's summary quoted the injected instruction. Either outcome is acceptable, and nothing was delivered.
- **Fixed after the first pass (c4b6b37):**
  - On narrow screens, a floating copy of the approval card covered the chat. Floating copies are now hidden below the `md` width.
  - The approval card said "You can also answer from Telegram", which is untrue in the public demo. That line is now hidden there.
  - The "public demo" badge crowded the header on phones. It's now hidden below `sm`.
- **Not seen live after the fix:** an approval card at phone width. The re-check prompt was a direct user instruction with clean context, so it was correctly allowed rather than escalated.
- **Cold start:** the free plan sleeps after 15 minutes idle, and the first request after that takes about a minute.
