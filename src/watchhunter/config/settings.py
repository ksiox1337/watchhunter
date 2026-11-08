"""Typed application settings loaded from environment / .env file."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import (
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)

# Fields below are stored as CSV in the env / .env file (e.g. "EBAY_US,EBAY_DE").
# pydantic-settings would otherwise try to JSON-decode any list-typed env var
# before running validators, so we pre-split them in a custom source.
_CSV_FIELDS = frozenset(
    {
        "ebay_marketplaces",
        "ebay_category_ids",
        "ebay_keywords",
        "buy_now_keywords",
        "kleinanzeigen_keywords",
    }
)


def _split_csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [v.strip() for v in value if v and v.strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


class _CsvAwareMixin:
    """Mixin that pre-splits CSV strings for list[str] fields before pydantic validates."""

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        if field_name in _CSV_FIELDS and isinstance(value, str):
            return _split_csv(value)
        return super().prepare_field_value(  # type: ignore[misc]
            field_name, field, value, value_is_complex
        )


class _CsvEnvSource(_CsvAwareMixin, EnvSettingsSource):
    pass


class _CsvDotEnvSource(_CsvAwareMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── eBay ──────────────────────────────────────────────────────────────
    ebay_use_api: bool = False
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_oauth_url: str = "https://api.ebay.com/identity/v1/oauth2/token"
    ebay_api_base_url: str = "https://api.ebay.com"
    ebay_marketplaces: list[str] = Field(default_factory=lambda: ["EBAY_US", "EBAY_DE"])
    ebay_category_ids: list[str] = Field(default_factory=lambda: ["31387", "260324"])
    ebay_keywords: list[str] = Field(
        default_factory=lambda: ["watch", "wristwatch", "armbanduhr"]
    )
    ebay_html_pages_per_query: int = 2

    # ─── Buy-It-Now hunter ─────────────────────────────────────────────────
    # Separate "fresh-listed only" scan over fixed-price listings. Catches
    # underpriced items in the seconds after they're posted.
    buy_now_enabled: bool = False
    buy_now_keywords: list[str] = Field(default_factory=list)
    buy_now_scan_interval_minutes: int = 1
    # Overrides the minutes value if > 0. Sub-minute cadence makes the bot react
    # to brand-new BIN listings within seconds of going live.
    buy_now_scan_interval_seconds: int = 0
    buy_now_html_pages_per_query: int = 1
    # Warmup mode: first scan after startup records what's already up but
    # does NOT analyze anything. Subsequent scans only act on truly new items.
    buy_now_warmup_on_start: bool = True

    # ─── Kleinanzeigen watchdog ────────────────────────────────────────────
    # Separate scan over kleinanzeigen.de (Germany's classifieds). Always
    # treated as fixed-price + fresh-only — each item analyzed at most once.
    kleinanzeigen_enabled: bool = False
    kleinanzeigen_keywords: list[str] = Field(default_factory=list)
    kleinanzeigen_scan_interval_seconds: int = 60
    kleinanzeigen_pages_per_query: int = 1
    kleinanzeigen_warmup_on_start: bool = True
    kleinanzeigen_rate_limit_rpm: int = 20

    # ─── Analyzer (OpenAI) ─────────────────────────────────────────────────
    # Triage = cheap text-only verdict on titles, batched many per call.
    # Eval   = multimodal deep look at the few that pass triage.
    openai_api_key: str = ""
    # Optional: any OpenAI-compatible endpoint (proxy, Azure-compatible gateway, …).
    openai_base_url: str = ""
    openai_model: str = "gpt-5-mini"
    openai_triage_model: str = "gpt-5-nano"
    # Cheap vision pass before the full evaluation; empty = always full eval.
    openai_screen_model: str = ""  # e.g. gpt-5-nano; off: it dropped 10 of 16 good finds in a test
    # Listings the screen scores below MIN_SCORE - margin never get the full eval.
    screen_margin: int = 10
    # Verdict first, Russian card text only for listings that will be sent.
    two_step_eval: bool = True
    # gpt-5 family only: "minimal" | "low" | "medium" | "high". Minimal = fastest, cheapest.
    openai_reasoning_effort: str = "minimal"
    # "low" = fixed ~85 tokens/image; "high"/"auto" tile the image (more tokens, finer detail).
    openai_image_detail: str = "low"
    openai_rate_limit_rpm: int = 300
    openai_triage_rate_limit_rpm: int = 300
    # ─── Triage provider ───────────────────────────────────────────────────
    #   openai — batched gpt-5-nano JSON verdicts
    #   jev    — TypeSafe Jev decision model (noul probability per listing);
    #            falls back to OpenAI triage on any Jev error.
    triage_provider: str = "openai"
    typesafe_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_base_url: str = "https://api.typesafe.ai/v1/systemone"
    # Listings with p(interesting) >= threshold go to the photo evaluation.
    # Low on purpose: a missed deal costs more than one extra mini call.
    jev_threshold: float = 0.3
    jev_rate_limit_rpm: int = 120

    max_images_per_listing: int = 4
    triage_batch_size: int = 25
    # Parallel evaluations per scan.
    eval_concurrency: int = 8

    # Hard daily spend cap. When today's recorded LLM spend + the estimated
    # cost of the next call would exceed this, the call is refused (triage
    # treats it as "not interesting"; eval skips). 0 / unset = no cap.
    max_daily_cost_usd: Decimal = Decimal("0")
    # Emit a warning the first time today's spend crosses this fraction of the cap.
    budget_warn_at_pct: float = 80.0

    # ─── Telegram ──────────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Times in notifications (auction end) are shown in this zone.
    timezone: str = "Europe/Berlin"

    # ─── App ───────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/watchhunter.db"
    scan_interval_minutes: int = 15
    notify_interval_minutes: int = 60
    min_score: int = 60
    # Only notify references at least this rare: "", low, medium, high, very_high.
    min_rarity: str = ""
    auction_ends_within_hours: int = 24
    max_price_eur: Decimal | None = None
    max_shipping_eur: Decimal | None = None
    reanalysis_ttl_hours: int = 6
    log_level: str = "INFO"
    log_json: bool = True

    # ─── Validators ────────────────────────────────────────────────────────
    @field_validator(
        "ebay_marketplaces",
        "ebay_category_ids",
        "ebay_keywords",
        "buy_now_keywords",
        "kleinanzeigen_keywords",
        mode="before",
    )
    @classmethod
    def _csv(cls, v: str | list[str]) -> list[str]:
        return _split_csv(v)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    # Swap default env / .env sources for our CSV-aware versions.
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _CsvEnvSource(settings_cls),
            _CsvDotEnvSource(settings_cls),
            file_secret_settings,
        )

    # ─── Convenience ───────────────────────────────────────────────────────
    @property
    def data_dir(self) -> Path:
        return Path("data")

    @property
    def logs_dir(self) -> Path:
        return Path("logs")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
