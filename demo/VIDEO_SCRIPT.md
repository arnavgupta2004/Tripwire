# Video script: follow this exactly

About **3 minutes**. Check the hackathon's video rules (maximum length, YouTube or
Vimeo, public or unlisted) before you upload. If the limit is shorter, drop the
scenes marked _optional_.

Every claim you say below has been verified. The backing evidence is in
`demo/DEMO_SCRIPT.md` and `evals/agentdojo/results.md`.

---

## Part A: set up (once, before recording)

### 1. `.env` (at the repo root)

Make sure these are set:

```
NEBIUS_API_KEY=<your key>
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_CHAT_ID=<your own chat id>
DEMO_MODE=true
USER_NAME=Riya
```

`USER_NAME=Riya` matches the fictional demo files (Riya Kapoor). Your real name then
never appears on screen. Leave everything else as it is.

### 2. Start the app (two terminals)

Port 8000 is used by your other project, so use 8100.

Terminal 1:

```bash
uv run uvicorn api.main:build --factory --app-dir backend --port 8100
```

Terminal 2:

```bash
cd frontend && TRIPWIRE_API=http://127.0.0.1:8100 npm run dev
```

### 3. Browser

- Open <http://localhost:5173> in a **clean** window: no other tabs, bookmarks bar hidden.
- Set the zoom to **110%**, so text reads well on video.
- Use the dark theme (the ☀ button toggles it).
- Open a second tab with <https://tripwire-demo.onrender.com>, to show for two
  seconds at the end. UptimeRobot keeps it awake.

### 4. Phone

- Open Telegram, on your chat with the bot.
- Turn on Do Not Disturb, so only the bot's notifications show.
- Plan how to film it: screen-record the phone, or hold it up to the camera.

### 5. Dry run (about $0.05 of model calls)

Do every scene below once without recording. Watch for three things:

- **Scene 3:** the amber reader node appears, and the brief reaches your phone.
- **Scene 5:** the approval card appears on your phone.
- **Scene 6, optional:** the naive agent reaches for your files or the attacker's site.
  If it doesn't in the dry run, cut Scene 6.

### 6. Reset between takes

- Click **Load demo** before Scene 3. It clears the thread, re-seeds the demo
  memory, and switches to High-security.
- Click **New thread** where a scene says so.

---

## Part B: record

Each scene gives **[SCREEN]** (what's showing), **[DO]** (what to click) and
**[SAY]** (read it word for word). Speak slowly; pauses are fine, and you can cut
them later.

### Scene 1: hook (0:00–0:20)

**[SCREEN]** `docs/gallery/01_cover.png`, full screen, or the app's Assistant screen.

**[SAY]**
> "Personal AI assistants read the web, your files and your messages, and anyone can
> write text that ends up in front of them. A prompt injection hides instructions in
> that text and turns your assistant against you. This is Tripwire: a personal
> assistant with a flow firewall between the model and its tools, built on NVIDIA
> Nemotron and Nebius Token Factory."

### Scene 2: the evidence (0:20–0:50)

**[DO]** Click **Evidence** in the header. Slowly point at the green "Travel
(held-out)" chip, then at the first chart.

**[SAY]**
> "First, does it work? We tested Tripwire on AgentDojo, a public benchmark for prompt
> injection, using its published attack. We built the policy on two suites, then
> froze it and ran a third suite, Travel, that we had never touched. On that held-out
> suite, attack success went from 38.6 percent with no defense to 5 percent with
> Tripwire's gateway, while it still completed 70 percent of normal tasks. Every
> attack that got through was one goal: making the assistant *say* something. Tripwire
> controls what the assistant *does*, not what it says."

### Scene 3: a poisoned page, High-security mode (0:50–1:30)

**[DO]** Click **Assistant**, then **Load demo**. Point at the strip under the green
banner: **High-security** is now selected.

**[SAY]**
> "Here's the product. I'll ask it to read an article and send me a brief on Telegram.
> This page is poisoned: it carries the same benchmark attack, hidden instructions
> telling the assistant to collect my files and post them to an outside website."

**[DO]** Click the **Demo: poisoned page** chip, then **Send**. Wait for the graph.
When the amber node appears, click it.

**[SAY]**
> "In High-security mode, the page never reaches the planner directly. A quarantined
> reader running Nemotron Nano turns it into structured data and flags the hidden
> instructions. The assistant only ever sees them as data, so it never tries to act
> on them."

**[DO]** Close the drawer (✕). Show your phone receiving the brief.

**[SAY]**
> "The one action I asked for, a brief to my own Telegram, was checked by the Nano
> classifier and allowed. There it is."

> **If it's held for approval instead** (it happens occasionally, when the summary
> quotes the hidden text): click **Allow once** and say "Tripwire held it because
> the brief quoted the page's hidden instruction. I approve it, and it goes through."

### Scene 4: the same page in Standard mode (1:30–1:55)

**[DO]** Click **Standard** in the strip, then **New thread**. Type exactly:

`Read the article at http://127.0.0.1:8100/demo-pages/informations.html and send me a short brief of it on Telegram.`

Press Enter. When the graph finishes, click the **send_telegram** node.

**[SAY]**
> "Standard is the default. It skips the reader, which keeps more detail, and lets
> the gateway check every action. There's no reader flag this time; the planner read
> the raw page. Everything it tries to do with that content still goes through the
> gateway, and this send was checked by the classifier and allowed. On the held-out
> suite, Standard stopped every attack that needed an action."

### Scene 5: approval, from Telegram (1:55–2:30)

**[DO]** Click **New thread**. Type exactly:

`Read tax_2025.txt in my files and send my accountant Priya a short summary on Telegram chat 777.`

Press Enter. The approval card appears in the app and on your phone.

**[SAY]**
> "Now something riskier: sending my private tax data to someone else. Tripwire's
> labels know that file is private and that chat 777 isn't me, so the send is held.
> I can answer in the app, or right from Telegram."

**[DO]** On the **phone**, tap **Allow once**. Show the app: the card clears, the
amber node turns to allowed, and the reply appears.

**[SAY]**
> "I approve from my phone, and the same paused action resumes. The first answer
> wins. In demo mode, messages to other people are logged but never actually
> delivered."

### Scene 6 (optional, only if it worked in the dry run): no Tripwire (2:30–2:45)

**[DO]** Click **Switch to naive agent** (top right of the banner), then **New
thread**, and send the Scene 4 prompt again. Point at the graph.

**[SAY]**
> "For contrast, here's the same model with Tripwire switched off. It reads the
> poisoned page and goes after my files. Demo mode keeps this safe: only fictional
> files, and outside sites are unreachable."

**[DO]** Click **Switch to Tripwire** before moving on.

### Scene 7: how it works, and close (2:45–3:05)

**[SCREEN]** `docs/gallery/05_architecture.png`, full screen.

**[SAY]**
> "Under the hood: every tool call passes the gateway. Provenance labels and
> deterministic rules decide most calls with no model at all. Nemotron Nano classifies
> intent and checks for leaks, Nemotron Ultra judges the hard cases, and Nemotron Super
> plans. All three run on Nebius Token Factory, one API with no GPUs to manage. Our
> whole evaluation cost 17 dollars 50."

**[DO]** Switch to the tab with <https://tripwire-demo.onrender.com> for two seconds.

**[SAY]**
> "Tripwire: a personal AI assistant that can't be turned against you. The live demo,
> code and full results are linked below."

---

## Part C: after recording

1. Upload the video and send the link. The README and the brief get updated with it.
2. Stop both terminals (Ctrl+C).
3. If you skipped Scene 6, nothing else changes.

### If something goes wrong mid-take

| What you see | What to do |
|---|---|
| "Thinking…" for more than 30 s | Stop the take, click **New thread**, and start the scene again. Token Factory occasionally stalls one request. |
| No amber reader node in Scene 3 | Check the strip says **High-security**. Click **Load demo** and redo Scene 3. |
| Nothing arrives on the phone | Check `TELEGRAM_CHAT_ID` in `.env` and that Terminal 1 shows the bot started. You can still click **Allow once** in the app instead. |
| The assistant asks "where is the summary?" in Scene 5 | Reply `It's tax_2025.txt in my files.` and carry on. |
| You misspoke | Pause two seconds and repeat the sentence. Cut it later. |
