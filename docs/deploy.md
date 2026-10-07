# Deploying the public demo

One container serves everything: the API under `/api`, the built frontend at `/`,
and liveness at `/healthz`. The image defaults to `PUBLIC_DEMO=true`, which means:

- **DEMO_MODE forced on:** only the fictional files in `demo/private/`; fetches limited to the demo pages this server hosts.
- **No Telegram:** there's no bot token, so a "send to me" is allowed by the policy but never delivered.
- **Isolated visitors:** one session per visitor (a random ID kept in the browser), with its own memory, notes and approvals. Load demo resets that visitor's thread.
- **Rate limits:** 8 turns per visitor and 60 overall, per 10 minutes.
- **Spend cap:** a daily cap on model spend (UTC day, persisted in `DATA_DIR/spend.json`). Visitors get a friendly message when it's reached.

The image never contains secrets. `.env` is in `.dockerignore`, and keys come from the host's secret store.

## Configuration

| Variable | Where | Notes |
|---|---|---|
| `NEBIUS_API_KEY` | **secret** | Token Factory key. Use a dedicated key for the demo so it can be rotated alone. |
| `NEMOTRON_NANO_MODEL`, `NEMOTRON_SUPER_MODEL`, `NEMOTRON_ULTRA_MODEL` | env | Same values as your local `.env`. |
| `DAILY_SPEND_CAP_USD` | env | Default `2.0`. |
| `CHAT_RATE_PER_VISITOR`, `CHAT_RATE_GLOBAL`, `MAX_VISITORS` | env | Defaults `8`, `60`, `200`. |
| `PORT` | env | Default `8000`. |

Leave `TELEGRAM_*` and `TAVILY_API_KEY` unset; the public demo uses neither.

## Build

CI (`.github/workflows/ci.yml`, job `image`) does the following:

- builds the image on every push;
- smoke-tests `/healthz`, `/api/health` and `/`;
- on `main`, pushes it to `ghcr.io/arnavgupta2004/tripwire:<sha>` and `:latest`.

To build locally, run `docker build -t tripwire .`, then:

```bash
docker run --rm -p 8000:8000 --env-file .env.demo tripwire
```

`.env.demo` is gitignored. It should contain only the variables above.

## Deploy (Nebius Serverless AI endpoint, CPU)

```bash
nebius iam secret create --name tripwire-demo   # store NEBIUS_API_KEY in SecretStash (Console works too)
nebius ai endpoint create \
  --name tripwire-demo \
  --image ghcr.io/arnavgupta2004/tripwire:<sha> \
  --container-port 8000 \
  --platform cpu-d3 --preset 2vcpu-8gb \
  --env NEMOTRON_NANO_MODEL=... --env NEMOTRON_SUPER_MODEL=... --env NEMOTRON_ULTRA_MODEL=... \
  --env DAILY_SPEND_CAP_USD=2 \
  --env-secret NEBIUS_API_KEY=tripwire-demo:NEBIUS_API_KEY \
  --public
```

The `endpoint create` flags follow the Nebius Serverless docs. The secret, update and stop subcommands are confirmed on the first real deploy; check `nebius ai endpoint --help` if one differs. The endpoint prints its HTTPS URL. If the GHCR package is private, either make it public (it holds no secrets) or add registry credentials to the endpoint.

Run **exactly one replica**. Visitor sessions and the spend counter live in the process, so more replicas would split visitors across processes and multiply the cap.

## Verify

```bash
curl -s https://<url>/healthz
```

This should return `{"ok":true,"public_demo":true}`.

```bash
curl -s https://<url>/api/health
```

The `budget` field should show `spent_usd`, `cap_usd` and `remaining_usd`.

Then, in a private browser window:

1. Click **Load demo**, then send the "Demo: poisoned page" example. The graph should show the reader flag and the allowed send to self, and nothing is delivered.
2. Send the "Tripwire is strict" example. You should get an R3 block, and the drawer should show Ultra's reason.
3. Ask it to send something to another chat ID. An approval card should appear; Allow and Deny should both resume the turn.
4. Open the Evidence page, and check the layout at phone width.

## Roll back

Redeploy the previous image tag. Every `main` commit has a `<sha>` tag in GHCR:

```bash
nebius ai endpoint update --name tripwire-demo --image ghcr.io/arnavgupta2004/tripwire:<previous-sha>
```

## Rotate keys

1. Create a new key in Token Factory.
2. Update the secret in SecretStash.
3. Restart or redeploy the endpoint so it reads the new value.
4. Revoke the old key in Token Factory.

The key never appears in logs: settings exclude secrets from `repr`.

## Check spend

- **Today, as the app counts it:** `GET /api/health` returns `budget.spent_usd` against `cap_usd`. It resets at 00:00 UTC. Raise or lower the cap by changing `DAILY_SPEND_CAP_USD` and redeploying.
- **Ground truth:** the Token Factory console's usage page for the demo key. The app's figure is estimated from `config/pricing.yaml`, so compare the two now and then.
- **Hosting:** the endpoint itself is billed separately on Nebius AI Cloud. 2 vCPU and 8 GB of CPU comes to roughly $0.07/hour, or about $1.60/day, while it's running. Stop the endpoint when the demo isn't needed.

## Stop

```bash
nebius ai endpoint stop --name tripwire-demo
```

Or delete it to remove the URL entirely.
