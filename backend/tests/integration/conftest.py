import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.services.session_service import redis_client


RUN_INTEGRATION_TESTS = os.getenv("RUN_INTEGRATION_TESTS") == "1"


if engine.url.database != "ai_shopping_test":
    raise RuntimeError("Tests must use the ai_shopping_test PostgreSQL database")

redis_connection = redis_client.connection_pool.connection_kwargs
if (
    redis_connection.get("host") != "127.0.0.1"
    or redis_connection.get("port") != 46379
    or redis_connection.get("db") != 15
):
    raise RuntimeError("Tests must use the isolated test Redis database")


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> Generator[None, None, None]:
    if not RUN_INTEGRATION_TESTS:
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run PostgreSQL/Redis tests")

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_storage() -> Generator[None, None, None]:
    redis_client.flushdb()

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE users CASCADE"))

    yield

    redis_client.flushdb()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
