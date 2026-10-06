# NemoClaw / OpenShell spike notes

Phase 0 spike, 7 Oct 2026. Docs research only: nothing was installed and no
installer was run. Anything marked **(verify)** comes from docs I couldn't fully
render, or depends on version, so check it at install time.

## TL;DR

- **NemoClaw** is NVIDIA's *alpha* reference stack. It runs one of three
  supported agents (OpenClaw, Hermes, LangChain Deep Agents Code) inside an
  **OpenShell** sandbox, with managed inference, network policy and onboarding.
  It has no documented way to run a custom agent.
- **OpenShell** is the runtime underneath. It can run **any process** as the
  agent (`openshell sandbox create --from <image> -- <cmd>`), applies a
  default-deny egress policy, and injects credentials at the network boundary.
- **Recommendation:** build the Tripwire core standalone. Then integrate with
  **plain OpenShell** (not NemoClaw): run the Tripwire backend image inside an
  OpenShell sandbox whose egress policy allows only Token Factory, Tavily and
  Telegram. This gives the two-layer story from the spec. OpenShell decides
  *which hosts* can be reached; Tripwire decides *which information flows* are
  allowed. Treat NemoClaw only as background for the README and the feedback
  section.
- **Blocker on this Mac:** Docker isn't installed. Docker Desktop or Colima is
  required first.

## What gets installed

### NemoClaw (`curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash`)
- Node.js via `nvm` and the NemoClaw CLI via `npm`, both user-local (no sudo).
  Needs Node 22.19+.
- The OpenShell gateway: a host process that handles credential storage,
  sandbox lifecycle and an L7 egress proxy.
- Sandbox container images for the chosen agent. The sandbox uses Landlock,
  seccomp and a network namespace, with read-write access only to `/sandbox` and
  `/tmp`.
- A "blueprint": a versioned YAML package of sandbox shape, policies and
  inference profiles. The default OpenClaw policy is
  `nemoclaw-blueprint/policies/openclaw-sandbox.yaml`.
- State in `~/.nemoclaw/` (`sandboxes.json`, `gateways/<port>/`).
- An onboarding wizard: agent → inference provider/model → credential → sandbox
  name → optional web search (Brave or **Tavily**) → optional messaging
  (**Telegram**, Discord, Slack…) → network policy tier (Balanced / Restricted /
  Open).
- The docs give no uninstall command.

### OpenShell (`curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh`)
- The `openshell` CLI and a local gateway. The default sandbox image is minimal
  Ubuntu with no agent installed.
- Version 0.1.x, Apache-2.0. It collects anonymous telemetry; disable with
  `OPENSHELL_TELEMETRY_ENABLED=false`.
- Python SDK: `uv add openshell`. It talks to a gateway but does **not** install
  the CLI.

## macOS support

- OpenShell supports Linux, macOS on Apple Silicon, and WSL 2 (experimental). It
  needs Docker, Podman or host virtualization.
- The NemoClaw quickstart lists macOS (including Apple Silicon) with Docker
  Desktop or Colima. The GitHub README only mentions DGX/WSL, so macOS support
  in this alpha is less proven.
- Landlock and seccomp are Linux kernel features. On macOS they run inside the
  Docker VM's Linux kernel, which is fine for a demo.
- **This machine** (arm64, macOS 27) has Node 24 but **no Docker or Colima**.

## Inference routing → Token Factory

Two mechanisms, depending on version. **(verify)** against whatever version gets
installed.

1. **NemoClaw custom provider** (current NemoClaw docs):
   ```bash
   NEMOCLAW_PROVIDER=custom \
   NEMOCLAW_ENDPOINT_URL=https://api.tokenfactory.nebius.com/v1 \
   NEMOCLAW_MODEL=<nemotron-3-super id from check_models.py> \
   COMPATIBLE_API_KEY=<NEBIUS_API_KEY> \
   nemoclaw onboard --non-interactive
   ```
   The agent calls `inference.local` inside the sandbox, and the gateway
   forwards to Token Factory with the real key injected. The sandbox never sees
   the key. NemoClaw sends a test inference request during onboarding, so a bad
   URL fails early. Change the model later with
   `nemoclaw <sandbox> inference set --endpoint-url …`. This is a single
   configured model route, which doesn't fit Tripwire's three tiers well.

2. **OpenShell providers** (latest OpenShell docs): OpenShell **removed** the
   workspace-global `inference.local` route and the `openshell inference`
   commands. Providers are now attached per sandbox. The workload calls the
   provider's native API through `OPENAI_BASE_URL` with a placeholder key, and
   the gateway injects the real credential. "Provider attachment does not select
   or rewrite a model", so **all three Nemotron tiers work through one
   provider**. A non-OpenAI host like Token Factory needs its own provider
   *profile* that declares host, port, credential and allowed binaries. I
   couldn't render the exact profile syntax, so take it from the Inference page
   or the `npx skills add NVIDIA/OpenShell` skills. **(verify)**

Because NemoClaw pins its own OpenShell version, the two may disagree. Use
whichever one the installed `openshell --help` shows.

## Can a custom Python agent run in an OpenShell sandbox?

**Yes with OpenShell directly. Not documented with NemoClaw.**

- OpenShell: "any arbitrary process can serve as the agent". There's no required
  supervisor or base image; any OCI image works.
  ```bash
  docker build -t tripwire:dev .
  openshell sandbox create --name tripwire --from tripwire:dev \
    --policy openshell/policy.yaml --forward 8000 \
    -- uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
  ```
  `--from` doesn't build Dockerfiles, so build the image first. `--upload
  ./src:/workspace/src` and `openshell sandbox upload` copy files in, and
  `--forward` / `openshell forward start 8000 <sandbox>` exposes the UI.
- NemoClaw: `NEMOCLAW_AGENT` accepts only `openclaw | hermes |
  langchain-deepagents-code`. Wrapping Tripwire as an OpenClaw plugin would mean
  rewriting it in OpenClaw's TypeScript plugin model, which isn't worth it.

## Egress policy (what OpenShell would enforce for Tripwire)

Default-deny: every outbound connection is denied unless a `network_policies`
rule allows it. Rules are per binary and can be L7-aware (e.g. read-only REST).
A sketch for Tripwire, with fields copied from the docs' examples **(verify
paths and access levels)**:

```yaml
network_policies:
  token_factory:
    endpoints:
      - { host: api.tokenfactory.nebius.com, port: 443, protocol: rest, enforcement: enforce, access: read-write }
    binaries: [ { path: /usr/local/bin/python3.12 } ]
  tavily:
    endpoints:
      - { host: api.tavily.com, port: 443, protocol: rest, enforcement: enforce, access: read-write }
    binaries: [ { path: /usr/local/bin/python3.12 } ]
  telegram:
    endpoints:
      - { host: api.telegram.org, port: 443, protocol: rest, enforcement: enforce, access: read-write }
    binaries: [ { path: /usr/local/bin/python3.12 } ]
```

- `network_policies` can be hot-reloaded on a running sandbox
  (`openshell policy set`, or `openshell policy update <sb> --rule-name …
  --add-endpoint host:443:read-only:rest:enforce`). The filesystem, landlock and
  process sections are fixed at creation.
- Denials show up in `openshell logs <sandbox> --since 5m --source sandbox`.
  Don't filter with `--level warn`, or policy events get hidden.

## Recommendation for Tripwire

1. **Don't let this block the core.** Phases 1–4 run standalone on the host.
2. **Integrate with plain OpenShell after Phase 3** (≈2–3h): a Dockerfile for
   the backend, the policy above, and a Token Factory provider so the key never
   enters the sandbox.
3. **The demo story (the main payoff):** an injected page tells the agent to
   send `tax_2025.pdf` to Telegram. **OpenShell allows it**, because
   `api.telegram.org` is an approved host. **Tripwire blocks it**, because the
   flow is private data going to a sink and was triggered by untrusted content.
   An exfil attempt to `evil.example` is blocked by *both* layers, and
   OpenShell's log line can sit next to Tripwire's red edge. This shows exactly
   why semantic flow control is the missing layer.
4. **NemoClaw is optional.** Install it only if you want first-hand feedback for
   the "Most Valuable Feedback" prize (the custom-agent gap and the
   `inference.local` → providers drift are both good feedback points).
5. **Fallback:** if OpenShell on macOS fights back, ship standalone and
   document this integration path in the README, as the spec allows.

## Commands to run yourself (if you try it)

Download and read the installers before running them; don't pipe them straight
into a shell.

```bash
# 1. Container runtime (pick one). Colima is lighter than Docker Desktop.
brew install colima docker
colima start --cpu 4 --memory 8 --disk 60
docker info

# 2. OpenShell (recommended path)
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh -o /tmp/openshell-install.sh
less /tmp/openshell-install.sh
OPENSHELL_TELEMETRY_ENABLED=false sh /tmp/openshell-install.sh
openshell --version
openshell sandbox create --name demo          # smoke test: minimal Ubuntu sandbox
npx skills add NVIDIA/OpenShell               # optional: lets Claude Code drive the CLI and write policies

# 3. NemoClaw (optional, for feedback only)
curl -fsSL https://www.nvidia.com/nemoclaw.sh -o /tmp/nemoclaw.sh
less /tmp/nemoclaw.sh
bash /tmp/nemoclaw.sh            # interactive: choose OpenClaw, "custom" provider,
                                 # https://api.tokenfactory.nebius.com/v1, Nemotron 3 Super
nemoclaw <sandbox-name> status
```

## Sources

- NemoClaw repo: https://github.com/NVIDIA/NemoClaw
- NemoClaw quickstart (OpenClaw): https://docs.nvidia.com/nemoclaw/user-guide/openclaw/get-started/quickstart
- NemoClaw architecture: https://docs.nvidia.com/nemoclaw/latest/reference/architecture
- NemoClaw custom OpenAI-compatible endpoint: https://docs.nvidia.com/nemoclaw/user-guide/openclaw/inference/custom-endpoints/set-up-openai-compatible-endpoint
- OpenShell repo: https://github.com/NVIDIA/OpenShell
- OpenShell sandboxes: https://docs.nvidia.com/openshell/latest/how-it-works/sandboxes/overview
- OpenShell inference: https://docs.nvidia.com/openshell/latest/how-it-works/inference
- OpenShell providers: https://docs.nvidia.com/openshell/latest/how-it-works/providers/overview
- OpenShell policies / network rules: https://docs.nvidia.com/openshell/latest/how-it-works/policies/overview , https://docs.nvidia.com/openshell/latest/how-it-works/policies/network-rules
