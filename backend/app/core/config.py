from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path
import os

BACKEND_ROOT = Path(__file__).resolve().parents[2]
print(BACKEND_ROOT)

load_dotenv(BACKEND_ROOT / ".env.backend")

@dataclass
class Config:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres/postgres@localhost:5432/ai-shopping-analyzer")

setting = Config()
