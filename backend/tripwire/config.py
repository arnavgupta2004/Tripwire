"""Runtime settings, read from the environment (.env at the repo root)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
TIERS = ("nano", "super", "ultra")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(value: str | None, default: Path) -> Path:
    p = Path(value).expanduser() if value and value.strip() else default
    return p if p.is_absolute() else REPO_ROOT / p


@dataclass(frozen=True)
class Settings:
    # Secrets are excluded from repr so tracebacks and logs never print them.
    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_BASE_URL
    models: dict[str, str] = field(default_factory=dict)  # tier -> model id
    judge_tier: str = "ultra"
    tavily_api_key: str = field(default="", repr=False)
    telegram_bot_token: str = field(default="", repr=False)
    telegram_chat_id: str = ""
    # A chat you control that stands in for the attacker in naive-agent demos.
    telegram_demo_attacker_chat_id: str = ""
    demo_mode: bool = False
    files_dir: Path = REPO_ROOT / "demo" / "private"
    notes_dir: Path = REPO_ROOT / "data" / "notes"
    data_dir: Path = REPO_ROOT / "data"
    pricing_file: Path = REPO_ROOT / "config" / "pricing.yaml"
    fetch_allowlist: tuple[str, ...] = ()
    user_name: str = ""  # the assistant's user, named in the system prompt (both modes)
    planner_max_steps: int = 8
    planner_tool_mode: str = "native"  # native | json
    context_turns: int = 8  # how many past turns stay in context (and keep their taint)
    approval_timeout: float = 300.0  # seconds a paused turn waits for an answer before denying
    # Public demo: per-visitor sessions, forced DEMO_MODE, no Telegram, rate limits, spend cap.
    public_demo: bool = False
    daily_spend_cap_usd: float = 2.0
    chat_rate_per_visitor: int = 8  # turns per 10 minutes per visitor
    chat_rate_global: int = 60  # turns per 10 minutes across all visitors
    max_visitors: int = 200

    @classmethod
    def from_env(cls, env_file: Path | None = REPO_ROOT / ".env") -> "Settings":
        if env_file is not None:
            load_dotenv(env_file)
        e = os.environ.get
        models = {t: e(f"NEMOTRON_{t.upper()}_MODEL", "").strip() for t in TIERS}
        judge_tier = (e("JUDGE_TIER") or "ultra").strip().lower()
        if judge_tier not in TIERS:
            raise ValueError(f"JUDGE_TIER must be one of {TIERS}, got {judge_tier!r}")
        return cls(
            api_key=(e("NEBIUS_API_KEY") or "").strip(),
            base_url=(e("TOKEN_FACTORY_BASE_URL") or "").strip() or DEFAULT_BASE_URL,
            models={t: m for t, m in models.items() if m},
            judge_tier=judge_tier,
            tavily_api_key=(e("TAVILY_API_KEY") or "").strip(),
            telegram_bot_token=(e("TELEGRAM_BOT_TOKEN") or "").strip(),
            telegram_chat_id=(e("TELEGRAM_CHAT_ID") or "").strip(),
            telegram_demo_attacker_chat_id=(e("TELEGRAM_DEMO_ATTACKER_CHAT_ID") or "").strip(),
            demo_mode=_bool(e("DEMO_MODE")) or _bool(e("PUBLIC_DEMO")),  # a public demo is always DEMO_MODE
            files_dir=_path(e("DEMO_FILES_DIR"), REPO_ROOT / "demo" / "private"),
            notes_dir=_path(e("NOTES_DIR"), REPO_ROOT / "data" / "notes"),
            data_dir=_path(e("DATA_DIR"), REPO_ROOT / "data"),
            pricing_file=_path(e("PRICING_FILE"), REPO_ROOT / "config" / "pricing.yaml"),
            fetch_allowlist=tuple(
                h.strip().lower() for h in (e("FETCH_ALLOWLIST") or "").split(",") if h.strip()
            ),
            user_name=(e("USER_NAME") or "").strip(),
            planner_max_steps=int(e("PLANNER_MAX_STEPS") or 8),
            planner_tool_mode=(e("PLANNER_TOOL_MODE") or "native").strip().lower(),
            context_turns=int(e("PLANNER_CONTEXT_TURNS") or 8),
            approval_timeout=float(e("APPROVAL_TIMEOUT_S") or 300),
            public_demo=_bool(e("PUBLIC_DEMO")),
            daily_spend_cap_usd=float(e("DAILY_SPEND_CAP_USD") or 2.0),
            chat_rate_per_visitor=int(e("CHAT_RATE_PER_VISITOR") or 8),
            chat_rate_global=int(e("CHAT_RATE_GLOBAL") or 60),
            max_visitors=int(e("MAX_VISITORS") or 200),
        )

    @property
    def effective_judge_tier(self) -> str:
        """The judge runs on Ultra, falling back to Super when Ultra isn't configured."""
        if self.judge_tier == "ultra" and "ultra" not in self.models:
            return "super"
        return self.judge_tier
