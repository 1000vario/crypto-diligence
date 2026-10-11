"""Settings read from the environment (and a local .env file when present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, no expansion, existing variables win."""
    path = path or Path(".env")
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    provider: str = "anthropic"
    model_orchestrator: str = "claude-opus-5-5"
    model_subagent: str = "claude-opus-5-5"
    model_openai: str = "gpt-5.2"
    effort: str = "medium"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    etherscan_api_key: str | None = None
    coingecko_api_key: str | None = None
    github_token: str | None = None
    rpc_url: str = "https://ethereum-rpc.publicnode.com"
    max_turns: int = 12
    max_web_searches: int = 6
    max_tokens: int = 8000
    free_reports_per_day: int = 3
    global_reports_per_day: int = 30
    cache_days: int = 7
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    paid_tier_enabled: bool = False
    email_salt: str = "crypto-diligence"
    pricing_json: Path | None = None

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)  # a str here breaks every `data_dir / name`
        if self.pricing_json is not None:
            self.pricing_json = Path(self.pricing_json)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = env if env is not None else os.environ
        return cls(
            provider=(e.get("CD_PROVIDER") or "anthropic").strip().lower(),
            model_orchestrator=e.get("CD_MODEL_ORCHESTRATOR") or "claude-opus-5-5",
            model_subagent=e.get("CD_MODEL_SUBAGENT") or "claude-opus-5-5",
            model_openai=e.get("CD_MODEL_OPENAI") or "gpt-5.2",
            effort=(e.get("CD_EFFORT") or "medium").strip().lower(),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY") or None,
            openai_api_key=e.get("OPENAI_API_KEY") or None,
            etherscan_api_key=e.get("ETHERSCAN_API_KEY") or None,
            coingecko_api_key=e.get("COINGECKO_API_KEY") or None,
            github_token=e.get("GITHUB_TOKEN") or None,
            rpc_url=e.get("CD_RPC_URL") or "https://ethereum-rpc.publicnode.com",
            max_turns=int(e.get("CD_MAX_TURNS") or 12),
            max_web_searches=int(e.get("CD_MAX_WEB_SEARCHES") or 6),
            max_tokens=int(e.get("CD_MAX_TOKENS") or 8000),
            free_reports_per_day=int(e.get("CD_FREE_REPORTS_PER_DAY") or 3),
            global_reports_per_day=int(e.get("CD_GLOBAL_REPORTS_PER_DAY") or 30),
            cache_days=int(e.get("CD_CACHE_DAYS") or 7),
            data_dir=Path(e.get("CD_DATA_DIR") or "./data"),
            paid_tier_enabled=_bool(e.get("PAID_TIER_ENABLED"), False),
            email_salt=e.get("CD_EMAIL_SALT") or "crypto-diligence",
            pricing_json=Path(e["CD_PRICING_JSON"]) if e.get("CD_PRICING_JSON") else None,
        )

    def model_for(self, role: str) -> str:
        if self.provider == "openai":
            return self.model_openai
        return self.model_orchestrator if role == "orchestrator" else self.model_subagent
