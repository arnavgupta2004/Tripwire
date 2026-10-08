"""Publish the public demo to a Hugging Face Docker Space.

  python deploy/hf_space.py arnavguptas/tripwire --mode clone   # Space holds only a Dockerfile
  python deploy/hf_space.py arnavguptas/tripwire --mode bundle  # Space holds the source

clone:  the Space's Dockerfile clones this (private) GitHub repo at the pinned
        commit during the build, using the GH_CLONE_TOKEN build secret. The Space's
        Files tab shows only the Dockerfile and README.
bundle: the tracked source at HEAD is uploaded to the Space, so it's public.

Non-secret settings are set as Space variables. Secrets (NEBIUS_API_KEY,
SPEND_GIST_TOKEN, and GH_CLONE_TOKEN in clone mode) are never handled here:
enter them in the Space's Settings -> Variables and secrets.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

REPO = Path(__file__).resolve().parents[1]
GITHUB_REPO = "arnavgupta2004/Tripwire"
BUNDLE_PATHS = ["Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "backend", "frontend", "config",
                "demo/private", "demo/injection", "deploy/entrypoint.sh"]
MODEL_VARS = ("NEMOTRON_NANO_MODEL", "NEMOTRON_SUPER_MODEL", "NEMOTRON_ULTRA_MODEL")

SPACE_README = """---
title: Tripwire
emoji: 🪤
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
short_description: Prompt-injection flow firewall for a personal AI assistant
---

Tripwire's public demo. Fictional demo data only; nothing is sent anywhere.
Each visitor gets an isolated session; model spend is capped per day and in total.
Source and docs: https://github.com/{repo}
"""

CLONE_DOCKERFILE = """# Builds Tripwire from its GitHub repo at a pinned commit; the clone token is a
# build secret (Space settings), never stored in the image.
FROM alpine:3.20 AS src
RUN apk add --no-cache git
# The token goes in a header, not the URL, so git never echoes it in the build log.
RUN --mount=type=secret,id=GH_CLONE_TOKEN,mode=0444,required=true \\
    auth="$(printf 'x-access-token:%s' "$(cat /run/secrets/GH_CLONE_TOKEN)" | base64 | tr -d '\\n')" \\
 && git -c http.extraHeader="Authorization: Basic $auth" clone --quiet \\
      https://github.com/{repo}.git /src \\
 && git -C /src checkout --quiet {sha} && rm -rf /src/.git

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY --from=src /src/frontend/package.json /src/frontend/package-lock.json ./
RUN npm ci
COPY --from=src /src/frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=src /src/pyproject.toml /src/uv.lock /src/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --from=src /src/backend/ backend/
COPY --from=src /src/config/ config/
COPY --from=src /src/demo/private/ demo/private/
COPY --from=src /src/demo/injection/ demo/injection/
COPY --from=frontend /app/frontend/dist frontend/dist
COPY --from=src /src/deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN useradd --create-home --uid 1000 tripwire && mkdir -p /data && chown tripwire /data
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app/backend PYTHONUNBUFFERED=1 \\
    PUBLIC_DEMO=true DATA_DIR=/data PORT=8000
USER tripwire
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
"""


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout


def _env_value(name: str) -> str:
    """Read one non-secret setting from .env without loading the rest of the file."""
    for line in (REPO / ".env").read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("space", help="owner/name of an existing Docker Space")
    ap.add_argument("--mode", choices=["clone", "bundle"], required=True)
    args = ap.parse_args()

    if _git("status", "--porcelain", "--untracked-files=no").strip():
        sys.exit("commit your changes first: the Space is built from a commit")
    if args.mode == "clone" and _git("rev-list", "--count", "@{u}..HEAD").strip() != "0":
        sys.exit("push first: clone mode builds from GitHub")
    sha = _git("rev-parse", "HEAD").strip()

    api = HfApi()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        if args.mode == "bundle":
            archive = subprocess.run(["git", "-C", str(REPO), "archive", "HEAD", *BUNDLE_PATHS],
                                     check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", str(out)], input=archive, check=True)
        else:
            (out / "Dockerfile").write_text(CLONE_DOCKERFILE.format(repo=GITHUB_REPO, sha=sha))
        (out / "README.md").write_text(SPACE_README.format(repo=GITHUB_REPO))
        api.upload_folder(repo_id=args.space, repo_type="space", folder_path=str(out),
                          commit_message=f"Deploy {sha[:7]} ({args.mode})",
                          delete_patterns=["*"])  # the Space holds exactly this deploy

    variables = {name: _env_value(name) for name in MODEL_VARS}
    variables.update(PUBLIC_DEMO="true", SPEND_STORE="gist", DAILY_SPEND_CAP_USD="0.75",
                     LIFETIME_SPEND_CAP_USD="15")
    for key, value in variables.items():
        if not value:
            sys.exit(f"{key} is empty in .env")
        api.add_space_variable(args.space, key, value)
    print(f"deployed {sha[:7]} to https://huggingface.co/spaces/{args.space} ({args.mode})")
    print("secrets to set in the Space settings: NEBIUS_API_KEY, SPEND_GIST_TOKEN"
          + (", GH_CLONE_TOKEN" if args.mode == "clone" else ""))


if __name__ == "__main__":
    main()
