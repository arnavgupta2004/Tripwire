"""Shared helpers for the Phase 0 check scripts."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        print(f"note: {env_path} not found; using process environment only")
    load_dotenv(env_path)


def require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"error: {name} is not set. Add it to .env (see .env.example).")
    return value
