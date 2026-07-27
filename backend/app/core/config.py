from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
import os

BACKEND_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(BACKEND_ROOT / ".env.backend")

@dataclass
class Config:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres/postgres@localhost:5432/ai-shopping-analyzer")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "604800"))
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

setting = Config()
