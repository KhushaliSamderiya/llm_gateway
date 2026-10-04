from app.db import engine
from app.providers import registry


def test_no_db_connection_is_held_during_the_provider_call(chat, make_key, monkeypatch):
    """Regression: auth once kept its DB connection checked out for the whole request,
    including the slow provider call, which exhausted the pool under concurrency."""
    seen = {}
    original = registry._mock.chat

    async def spy(request):
        seen["checked_out"] = engine.pool.checkedout()
        return await original(request)

    monkeypatch.setattr(registry._mock, "chat", spy)

    assert chat(make_key()).status_code == 200
    assert seen["checked_out"] == 0
