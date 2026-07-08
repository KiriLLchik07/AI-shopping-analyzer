from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from collections.abc import Generator

from backend.app.core.config import setting

engine = create_engine(setting.database_url)
SessionLocal = sessionmaker(engine, autoflush=False, autocommit=False, expire_on_commit=False)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

