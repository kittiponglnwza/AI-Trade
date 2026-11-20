"""Environment-driven settings for the MT5 Trading Bridge."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

TERMINAL_PATH: str = os.getenv(
    "MT5_TERMINAL_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)
DEFAULT_SYMBOL: str = os.getenv("MT5_DEFAULT_SYMBOL", "XAUUSD")
API_KEY: str = os.getenv("MT5_API_KEY", "mt5-local-dev-key")
ALLOW_REAL_TRADING: bool = os.getenv("ALLOW_REAL_TRADING", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

DATA_DIR: Path = BACKEND_DIR / "data"
DB_PATH: Path = DATA_DIR / "trade_journal.db"

GOOGLE_SHEETS_WEBHOOK_URL: str = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
GOOGLE_SERVICE_ACCOUNT_FILE: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "").strip()

SUPABASE_URL: str = os.getenv(
    "SUPABASE_URL",
    "https://igdrxqpxbfvaeagppnus.supabase.co",
).strip().rstrip("/")
SUPABASE_PUBLISHABLE_KEY: str = os.getenv(
    "SUPABASE_PUBLISHABLE_KEY",
    "sb_publishable__Bc0V-v4EV0VJ0hZ_aV-9w_rd3uvyK1",
).strip()
SUPABASE_OWNER_ID: str = os.getenv(
    "SUPABASE_OWNER_ID",
    "20c1e655-72e7-4f18-ad5e-16b54794fee5",
).strip()
SUPABASE_OWNER_EMAIL: str = os.getenv(
    "SUPABASE_OWNER_EMAIL",
    "kitipongzaza566@gmail.com",
).strip()
SUPABASE_OWNER_PASSWORD: str = os.getenv("SUPABASE_OWNER_PASSWORD", "").strip()
