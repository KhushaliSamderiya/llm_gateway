import os

# These must be set BEFORE any `app` import: the app reads its settings once, at import time.
os.environ["DATABASE_URL"] = "postgresql://gateway:gateway@localhost:5432/gateway_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["GEMINI_API_KEY"] = "test-key-not-real"
os.environ["MOCK_DELAY_MS"] = "0"
os.environ["MOCK_FAILURE_RATE"] = "0"

from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
import redis as redis_sync  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402,F401  (registers the tables on Base.metadata)
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ApiKey, Team  # noqa: E402
from app.security import generate_api_key, hash_api_key  # noqa: E402


def _assert_test_db() -> None:
    assert engine.url.database == "gateway_test", "Refusing to touch a non-test database"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _assert_test_db()
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean_state():
    _assert_test_db()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE requests, api_keys, teams RESTART IDENTITY CASCADE"))
    r = redis_sync.Redis.from_url(os.environ["REDIS_URL"])
    r.flushdb()
    r.close()
    yield


@pytest.fixture(scope="session")
def client():
    # One client (and so one event loop) for the whole session: the app's Redis
    # connections are bound to the loop they were created on.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def redis_db():
    r = redis_sync.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    yield r
    r.close()


@pytest.fixture
def make_key():
    """Create a team (if new) and an API key; returns the raw key.
    Tables are reset per test, so the first team is id 1 and its first key is id 1."""

    def _make(team: str = "t1", rpm: int = 60, budget: str = "50.00") -> str:
        raw = generate_api_key()
        with SessionLocal() as db:
            team_row = db.scalar(select(Team).where(Team.name == team))
            if team_row is None:
                team_row = Team(name=team, monthly_budget_usd=Decimal(budget))
                db.add(team_row)
                db.flush()
            db.add(
                ApiKey(team_id=team_row.id, key_hash=hash_api_key(raw), rate_limit_rpm=rpm)
            )
            db.commit()
        return raw

    return _make


@pytest.fixture
def chat(client):
    def _chat(key, model: str = "mock", content: str = "hello", **extra):
        body = {"model": model, "messages": [{"role": "user", "content": content}], **extra}
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return client.post("/v1/chat/completions", json=body, headers=headers)

    return _chat
