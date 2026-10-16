"""Backend settings from environment / .env (see .env.example)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # SQLite file by default (no database server needed); any SQLAlchemy async URL works
    database_url: str = f"sqlite+aiosqlite:///{ROOT / 'out' / 'rfq.sqlite3'}"
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = "dev-key-change-me"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    frontend_url: str = "http://localhost:5173"
    storage_dir: Path = ROOT / "out" / "jobs"

    rfq_offline: bool = False
    rfq_use_llm: bool = True
    rfq_embed_images: bool = True  # product thumbnails inside the Excel
    chrome_cdp_url: str = "http://127.0.0.1:9333"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_ssl: bool = True
    smtp_starttls: bool = False
    bot_email: str = ""
    bot_password: str = ""
    allowed_recipient_domains: str = ""  # comma separated; empty = any domain

    worker_max_jobs: int = 4
    job_timeout_s: int = 900
    max_upload_bytes: int = 15 * 1024 * 1024
    default_user: str = Field(default="sourcing team")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_recipient_domains.split(",") if d.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
