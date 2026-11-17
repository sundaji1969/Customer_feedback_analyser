"""Reads settings from the .env file (never hard-code secrets here)."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two folders up from this file).
# Inside Docker, the variables come from docker-compose instead.
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Two models: a small, fast one for tags (it scores as well as bigger ones there), and a stronger
# one for replies (better Tamil/Tanglish and more specific replies). See backend/eval_ai.py.
# OPENAI_MODEL is the old single setting and still works as the tag model.
def _models() -> tuple[str, str]:
    """Returns (tag model, reply model)."""
    tag = os.getenv("TAG_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"
    reply = os.getenv("REPLY_MODEL", "").strip() or "gpt-5.5"
    return tag, reply


TAG_MODEL, REPLY_MODEL = _models()


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


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"{name} must be a whole number of 1 or more, got {raw!r}")
    return int(raw)


# How many reviews are sent to OpenAI at the same time, and how long one call may take.
AI_CONCURRENCY = _positive_int("AI_CONCURRENCY", 8)
AI_TIMEOUT_SECONDS = _positive_int("AI_TIMEOUT_SECONDS", 60)

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
