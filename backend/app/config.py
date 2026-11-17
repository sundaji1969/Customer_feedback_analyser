"""Reads settings from the .env file (never hard-code secrets here)."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two folders up from this file).
# Inside Docker, the variables come from docker-compose instead.
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _temperature(name: str, default: float) -> float:
    """Read a temperature (0 to 1) from the environment, with a clear error if it is wrong."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number between 0 and 1, got {raw!r}") from None
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1, got {value}")
    return value


# 0 = same answer every time (best for tags). Higher = more varied wording (good for replies).
TAG_TEMPERATURE = _temperature("TAG_TEMPERATURE", 0.0)
REPLY_TEMPERATURE = _temperature("REPLY_TEMPERATURE", 0.4)

POSTGRES_USER = os.getenv("POSTGRES_USER", "reviewlens")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "reviewlens")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)
