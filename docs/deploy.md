# Deploying the public demo

**Where it runs today:** Render's free tier, at <https://tripwire-demo.onrender.com>; see
[Render (live)](#render-live) below. The Nebius section after it is a runbook only: that
deployment has **not** been made yet, because the account can't create AI Cloud resources
without billing set up.

One container serves everything: the API under `/api`, the built frontend at `/`,
and liveness at `/healthz`. The image defaults to `PUBLIC_DEMO=true`:

- **DEMO_MODE forced on:** only the fictional files in `demo/private/`, and fetches limited to the demo pages this server hosts.
- **No Telegram:** there's no bot token, so a "send to me" is allowed by the policy but never delivered.
- **Isolated visitors:** one session per visitor (a random ID kept in the browser), with its own memory, notes and approvals. Load demo resets that visitor's thread.
- **Rate limits:** 8 turns per visitor and 60 overall, per 10 minutes.
- **Spend caps:** **$0.75 per UTC day** and **$15 for the deployment's lifetime**.
  - Both are stored in `/data/spend.json`, so restarts don't reset them.
  - When either cap is hit, visitors get a friendly message and no further model calls are made.
  - If the file can't be read or written, the app refuses to start. It never forgets spend silently.

The image never contains secrets. `.env` is in `.dockerignore`, and keys come from Nebius MysteryBox.

## Render (live)

`render.yaml` defines a free Docker web service in Frankfurt.
- **Build:** from this repo's Dockerfile, on every push to `main`.
- **Health check:** `/healthz`.
- **Storage:** Render's free tier has no persistent disk, so the spend caps live in a secret GitHub gist (`SPEND_STORE=gist`).
  - The app finds that gist, "Tripwire public demo: spend caps (do not delete)", or creates it on first start.
  - Writes are batched to one every 30 s, written at once when a cap is within $0.10, and flushed on shutdown.
  - If the gist can't be read at startup, the app refuses to start.
  - If writes fail for 2 minutes, chat pauses with a message until they succeed again.
  - **Deleting the gist resets the caps.**
- **Cost:** $0. Free instance hours (750/month) cover one service. With no card on file, exceeding any limit suspends the service rather than billing.

**Secrets.** Set these in the dashboard under Environment. They are never in the repo.

| Name | What |
|---|---|
| `NEBIUS_API_KEY` | A Token Factory key used only by this deployment. |
| `SPEND_GIST_TOKEN` | A fine-grained GitHub token. Grant only **Account permissions → Gists: Read and write**, with no repository access. |

**Deploy:**
1. In the Render dashboard, choose New → Blueprint, pick this repo, enter the two secrets, then Apply.
2. After that, every push to `main` redeploys.

**Roll back:** in the dashboard, open Events, find an earlier deploy, and choose **Rollback**. The caps are unaffected, because they live in the gist.

**Rotate keys:**
1. Create the new key or token.
2. Update it under Environment. Saving redeploys.
3. Revoke the old one.

**Check spend:**
- `GET /api/health` → `budget` shows today's spend and lifetime spend against their caps.
- The gist holds the same numbers.
- Ground truth for model spend is the Token Factory usage page for the deployment key.

**Keep-alive:** `.github/workflows/keepalive.yml` GETs `/healthz` every 10 minutes. That endpoint returns a fixed response and never calls a model. GitHub may run scheduled jobs several minutes late, so a sleep can still slip through.
- **Hours:** the 750 free instance hours a month cover one service running 24/7 (31 × 24 = 744 h). That only holds if this is the workspace's only free service.
- **GitHub minutes:** each run bills one minute, which is about 4,460 minutes a month. Public repos get Actions minutes free. Private repos on GitHub Free get 2,000 a month, which the keep-alive would use up partway through the month. CI shares that pool.
- **Switch:** the job only runs when the repo variable is set. To turn it on: `gh variable set KEEPALIVE_ENABLED --body true`. To turn it off, set it to `false`.

**Verify:** run the checks in [demo/verification/render_public_checks.md](../demo/verification/render_public_checks.md). The most recent run passed all of them, including WebSockets and streaming.

## Sizing and cost (Nebius, eu-north1)

The app only makes API calls, so it uses the smallest CPU preset Nebius offers: **`cpu-d3` / `2vcpu-8gb`**.

| Item | Rate | Per hour | Per month (730 h) |
|---|---|---|---|
| 2 vCPU (AMD Genoa, from 1 Oct 2026) | $0.015 / vCPU-h | $0.030 | $21.90 |
| 8 GiB RAM | $0.0045 / GiB-h | $0.036 | $26.28 |
| 30 GiB boot disk (network SSD; the default is 250 GiB, so set it) | $0.071 / GiB-month | $0.003 | $2.13 |
| 1 GiB shared filesystem for `/data` | $0.08 / GiB-month | <$0.001 | $0.08 |
| **Total hosting** | | **≈ $0.069** | **≈ $50.4** |

- **Through Dec 15:** from Oct 9, that's 68 days (1,632 h), or **about $113 of AI Cloud spend**.
- **Models:** model spend is separate, on Token Factory, and capped by the app at $15.
- **Public IP:** we don't pass `--public`. The managed HTTPS URL works without it, and a public IP would cost extra.

These are list prices for Compute. Nebius doesn't publish a separate price for serverless endpoints, so check the billing page after day one.

## One-time setup

### 1. Nebius CLI (macOS)

```bash
curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash
exec -l $SHELL
nebius version
nebius profile create        # interactive; opens a browser to sign in; pick your tenant and project
nebius profile list
```

- **Project ID:** in the console, open the project list, click ⋯ next to the project, then **Copy project ID**. From the CLI:

  ```bash
  nebius iam v2 project list --parent-id <tenant-id>
  ```

  The tenant ID is shown in the console under the tenant name.

- **Subnet ID:** endpoints use the project's default subnet if you omit `--subnet-id`. To see it:

  ```bash
  nebius vpc subnet list --parent-id <project-id>
  ```

```bash
export PROJECT_ID=<project-id>
```

### 2. Read-only GitHub token for pulling the private image

GHCR only accepts **classic** personal access tokens. Fine-grained tokens can't read packages.

1. Open <https://github.com/settings/tokens/new>. This is the classic token page.
2. Set **Note** to `nebius-tripwire-pull`.
3. Set **Expiration** to a custom date of **2026-12-31**, just past the demo end date.
4. Under **Select scopes**, tick **only `read:packages`**. Leave `repo`, `write:packages` and everything else unticked.
5. Click **Generate token** and copy it. GitHub shows it once.

This token can only download packages your account can read. It can't push, delete, or touch code.

### 3. Secrets in MysteryBox

Values are read with `read -s`, so they never appear on screen or in your shell history.

```bash
read -s GH_PULL && read -s NEBIUS_KEY   # paste the GitHub token, Enter; then the demo Token Factory key, Enter
nebius mysterybox secret create --parent-id $PROJECT_ID --name tripwire-ghcr-pull \
  --secret-version-payload "[{\"key\":\"REGISTRY_USERNAME\",\"string_value\":\"arnavgupta2004\"},{\"key\":\"REGISTRY_PASSWORD\",\"string_value\":\"$GH_PULL\"}]"
nebius mysterybox secret create --parent-id $PROJECT_ID --name tripwire-nebius-key \
  --secret-version-payload "[{\"key\":\"NEBIUS_API_KEY\",\"string_value\":\"$NEBIUS_KEY\"}]"
unset GH_PULL NEBIUS_KEY
```

You can also create both secrets in the console (MysteryBox → Create secret) with the same names and keys.

Use a **dedicated** Token Factory key for the demo. You can then rotate or revoke it without touching your own.

### 4. Volume for the spend caps

```bash
nebius compute filesystem create --parent-id $PROJECT_ID --name tripwire-data \
  --type network_ssd --size-gibibytes 1
nebius compute filesystem list --parent-id $PROJECT_ID   # note its ID
```

## Deploy

CI builds every push to `main`, smoke-tests it (including a root-owned `/data` mount and a restart), and pushes `ghcr.io/arnavgupta2004/tripwire:<sha>` and `:latest`. Deploy a specific `<sha>`, never `:latest`, so a rollback is exact.

```bash
nebius ai endpoint create \
  --parent-id $PROJECT_ID \
  --name tripwire-demo \
  --image ghcr.io/arnavgupta2004/tripwire:<sha> \
  --registry-secret tripwire-ghcr-pull \
  --container-port 8000 \
  --platform cpu-d3 --preset 2vcpu-8gb \
  --disk-size 30Gi \
  --volume <filesystem-id>:/data:rw \
  --env NEMOTRON_NANO_MODEL=<from .env> \
  --env NEMOTRON_SUPER_MODEL=<from .env> \
  --env NEMOTRON_ULTRA_MODEL=<from .env> \
  --env DAILY_SPEND_CAP_USD=0.75 \
  --env LIFETIME_SPEND_CAP_USD=15 \
  --env-secret NEBIUS_API_KEY=tripwire-nebius-key
nebius ai endpoint get-by-name --parent-id $PROJECT_ID --name tripwire-demo   # shows the https:// URL
nebius ai endpoint logs <endpoint-id>
```

- **One replica only.** Visitor sessions live in the process.
- **The spend file is safe across restarts,** because it lives on the volume.
- **Swapping the volume resets the caps.** Don't delete or replace the filesystem while the demo is live.

## Verify

```bash
curl -s https://<url>/healthz
```

This should return `{"ok":true,"public_demo":true}`.

```bash
curl -s https://<url>/api/health
```

The `budget` field should show today's spend and lifetime spend against their caps.

Then, in a private browser window:

1. Click **Load demo**, then send "Demo: poisoned page".
   - The reply streams in, and the graph shows the reader flag and an allowed send to self, which isn't delivered.
   - The live graph proves the WebSocket works.
2. Send "Private read, then a requested fetch". Under policy v3 the fetch goes to the classifier under R3; the drawer shows its verdict and both checks' reasons. With `POLICY_PROFILE=strict` it's an R3 block, and Ultra writes the explanation.
3. Ask it to send a note to Telegram chat 12345. An approval card should appear, and Allow or Deny should resume the turn.
4. Open the Evidence page, and check phone width.

## Roll back

Point the endpoint at the previous `<sha>`. Every `main` commit keeps its tag in GHCR.

If your CLI version has `nebius ai endpoint update`, change `--image` with it. Otherwise delete and re-create with the old tag, using the same command as Deploy. Re-creating gives a new URL. The spend caps survive, because they live on the filesystem, not the endpoint.

## Rotate keys

- **Token Factory key:**
  1. Create a new key.
  2. Add it as a new version of `tripwire-nebius-key`, under MysteryBox → secret → New version, with the same `NEBIUS_API_KEY` key.
  3. `nebius ai endpoint stop --id <id>`, then `nebius ai endpoint start --id <id>`.
  4. Revoke the old key in Token Factory.
- **GitHub pull token:**
  1. Generate a new classic token with only `read:packages`.
  2. Add it as a new version of `tripwire-ghcr-pull`.
  3. Stop and start the endpoint.
  4. Delete the old token at <https://github.com/settings/tokens>.

Secrets never reach logs: settings exclude them from `repr`, and the image has none.

## Check spend

- **Models, as the app counts them:** `GET /api/health` returns `budget`:
  - `spent_usd` against `cap_usd`, for today (UTC);
  - `lifetime_spent_usd` against `lifetime_cap_usd`.

  To change a cap, change `DAILY_SPEND_CAP_USD` or `LIFETIME_SPEND_CAP_USD` and redeploy.
- **Models, ground truth:** the Token Factory console's usage page for the demo key. The app estimates costs from `config/pricing.yaml`, so compare the two weekly.
- **Hosting:** the AI Cloud console's Billing page. Expect about $1.65/day.

## Stop and clean up

```bash
nebius ai endpoint stop --id <endpoint-id>      # no compute charges; the volume (~$0.08/month) remains
nebius ai endpoint delete --id <endpoint-id>    # removes the VM and boot disk
nebius compute filesystem delete --id <filesystem-id>   # only after the demo is over
```

After Dec 15, delete the endpoint and filesystem, and revoke the GitHub token and the demo Token Factory key.
