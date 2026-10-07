# Tripwire — visual identity

The product is about trust, so the interface has to feel calm and legible, never
like a security console that shouts. The one place it raises its voice is the
moment an attack is blocked.

## Typography

- **Inter** for all UI text. Weights 400/500/600/700. Humanist, neutral, highly
  legible at small sizes.
- **JetBrains Mono** for anything that is a machine identifier: rule ids
  (`R3.exfiltration_chain`), value handles, URLs, costs, token counts. Monospace
  signals "this is data, not prose."

## Color

A single brand teal on quiet slate-tinted neutrals (not pure gray). The flow
colors are the semantic core and are the same in the graph, the chips and the
drawer, so a color always means the same thing.

| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--brand` | `#0d7d72` | `#2bb8a8` | Tripwire, primary actions |
| `--trusted` | `#2f9e6e` | `#45c184` | trusted data (you typed it) |
| `--untrusted` | `#d98a2b` | `#e6a34d` | untrusted data (web, outside docs) |
| `--private` | `#7c5cd6` | `#a287e8` | private data (files, memory) |
| `--danger` | `#d6454f` | `#e85b64` | blocked flow |

Neutrals are `--ink` (text) over `--surface` / `--surface-raised` / `--surface-sunken`,
separated by `--line`. All are CSS variables on `:root`, re-defined under
`:root[data-theme="dark"]`, so every component themes for free.

Flow-color accessibility: color is never the only signal. Edges and chips also
carry a label or icon, blocked edges animate, and the drawer states the verdict in
words.

## Motion

Restrained. A new event rises in (`riseIn`, 220ms). The drawer slides from the
right (`slideIn`, 200ms). The one deliberate flourish is a **blocked edge**: it
turns `--danger` and pulses three times (`pulseRed`), the money shot of the demo.

## Modes

The naive-agent / protected switch is a full-width header bar that changes color
and label: brand teal "Protected by Tripwire" vs a flat danger-tinted "Naive agent
(no Tripwire)". It should be impossible to mistake which agent is running.

## States

Every screen has an empty, loading and error state. Users never see raw JSON:
decisions, labels and results are always rendered as chips, rows or prose.

## Layout

Assistant is a two-pane split (chat left, flow graph right) on desktop; the graph
collapses below the chat on phone width. Everything works down to 360px.
