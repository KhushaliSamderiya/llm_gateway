from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import func, select, update

from app.budget import _key as spend_key
from app.db import SessionLocal
from app.models import ApiKey, RequestLog


def count_rows(condition) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(RequestLog).where(condition))


def revoke_all_keys() -> None:
    with SessionLocal() as db:
        db.execute(update(ApiKey).values(is_active=False))
        db.commit()


# ---- health ----
def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---- auth ----
def test_missing_key_is_401(chat):
    r = chat(None)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_api_key"


def test_wrong_key_is_401(chat):
    r = chat("gw_not_a_real_key")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_revoked_key_is_401(chat, make_key):
    key = make_key()
    assert chat(key).status_code == 200
    revoke_all_keys()
    r = chat(key)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_valid_key_returns_an_openai_shaped_response(chat, make_key):
    r = chat(make_key(), content="hello")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"].startswith("[mock]")
    assert set(body["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}


# ---- validation ----
def test_empty_messages_is_400(client, make_key):
    r = client.post(
        "/v1/chat/completions",
        json={"model": "mock", "messages": []},
        headers={"Authorization": f"Bearer {make_key()}"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"


def test_unknown_model_is_404(chat, make_key):
    r = chat(make_key(), model="gpt-99")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"


def test_streaming_is_rejected(chat, make_key):
    r = chat(make_key(), stream=True)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "streaming_not_supported"


# ---- usage logging ----
def test_successful_request_is_logged(chat, make_key):
    chat(make_key())
    assert count_rows(RequestLog.status_code == 200) == 1


# ---- rate limiting ----
def test_rate_limit_blocks_after_the_limit(chat, make_key):
    key = make_key(rpm=3)
    assert [chat(key).status_code for _ in range(5)] == [200, 200, 200, 429, 429]


def test_429_carries_retry_after(chat, make_key):
    key = make_key(rpm=1)
    chat(key)
    r = chat(key)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(r.headers["retry-after"]) >= 1


def test_rate_limits_are_per_key(chat, make_key):
    a = make_key(team="a", rpm=1)
    b = make_key(team="b", rpm=1)
    assert chat(a).status_code == 200
    assert chat(a).status_code == 429
    assert chat(b).status_code == 200


def test_rate_limit_is_atomic_under_concurrency(chat, make_key):
    key = make_key(rpm=5)
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda _: chat(key).status_code, range(20)))
    assert codes.count(200) == 5
    assert codes.count(429) == 15


# ---- budgets (spend counters are in micro-dollars; team 1 is the first team created) ----
def test_zero_budget_is_blocked(chat, make_key):
    r = chat(make_key(budget="0.00"))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "monthly_budget_exceeded"


def test_spend_at_the_budget_is_blocked(chat, make_key, redis_db):
    key = make_key(budget="50.00")
    redis_db.set(spend_key(1), 50_000_000)
    assert chat(key).status_code == 429


def test_spend_under_the_budget_is_allowed(chat, make_key, redis_db):
    key = make_key(budget="50.00")
    redis_db.set(spend_key(1), 49_999_999)
    assert chat(key).status_code == 200


def test_missing_counter_is_rebuilt_from_postgres(chat, make_key, redis_db):
    key = make_key(budget="50.00")
    with SessionLocal() as db:
        db.add(
            RequestLog(
                team_id=1,
                api_key_id=1,
                model="mock",
                provider="mock",
                cost_usd=Decimal("60"),
                status_code=200,
            )
        )
        db.commit()
    assert redis_db.get(spend_key(1)) is None
    assert chat(key).status_code == 429


# ---- PII ----
def test_pii_is_masked_before_reaching_the_provider(chat, make_key):
    r = chat(make_key(), content="Contact bob@example.com about card 4111 1111 1111 1111")
    assert r.status_code == 200
    assert r.headers["x-gateway-pii-redacted"] == "CARD_NUMBER=1,EMAIL=1"
    echoed = r.json()["choices"][0]["message"]["content"]  # the mock echoes what it received
    assert "bob@example.com" not in echoed
    assert "4111" not in echoed
    assert "[EMAIL]" in echoed and "[CARD_NUMBER]" in echoed


# ---- cache ----
def test_second_identical_request_is_a_cache_hit(chat, make_key):
    key = make_key()
    first = chat(key, content="what is a cache", temperature=0)
    second = chat(key, content="what is a cache", temperature=0)
    assert first.headers["x-gateway-cache"] == "MISS"
    assert second.headers["x-gateway-cache"] == "HIT"
    assert first.json()["choices"] == second.json()["choices"]


def test_requests_without_temperature_zero_bypass_the_cache(chat, make_key):
    key = make_key()
    assert chat(key).headers["x-gateway-cache"] == "BYPASS"
    assert chat(key, temperature=0.7).headers["x-gateway-cache"] == "BYPASS"


def test_cache_is_not_shared_between_teams(chat, make_key):
    a = make_key(team="a")
    b = make_key(team="b")
    chat(a, content="same question", temperature=0)
    assert chat(b, content="same question", temperature=0).headers["x-gateway-cache"] == "MISS"


def test_prompts_differing_only_in_pii_share_a_cache_entry(chat, make_key):
    key = make_key()
    chat(key, content="Summarize the complaint from alice@example.com", temperature=0)
    r = chat(key, content="Summarize the complaint from bob@example.org", temperature=0)
    assert r.headers["x-gateway-cache"] == "HIT"


def test_no_raw_pii_is_stored_in_redis(chat, make_key, redis_db):
    chat(make_key(), content="Email alice@example.com please", temperature=0)
    keys = list(redis_db.scan_iter("cache:*"))
    assert keys, "expected a cache entry"
    for k in keys:
        assert "alice@example.com" not in redis_db.get(k)


def test_cache_hits_are_logged_as_hits(chat, make_key):
    key = make_key()
    chat(key, content="log me", temperature=0)
    chat(key, content="log me", temperature=0)
    assert count_rows(RequestLog.cache_hit.is_(True)) == 1
    assert count_rows(RequestLog.cache_hit.is_(False)) == 1


# ---- fallback ----
def test_failover_to_the_backup_provider(chat, make_key):
    r = chat(make_key(), model="mock-down")
    assert r.status_code == 200
    assert r.headers["x-gateway-provider"] == "mock"
    assert r.headers["x-gateway-fallback-from"] == "mock-down"


def test_healthy_chain_has_no_fallback_header(chat, make_key):
    r = chat(make_key(), model="mock")
    assert "x-gateway-fallback-from" not in r.headers


def test_backup_answers_are_not_cached(chat, make_key):
    key = make_key()
    for _ in range(2):
        r = chat(key, model="mock-down", content="x", temperature=0)
        assert r.headers["x-gateway-cache"] == "MISS"


def test_all_providers_down_is_a_502_and_is_logged(chat, make_key):
    r = chat(make_key(), model="mock-dead")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "provider_error"
    assert count_rows(RequestLog.status_code == 502) == 1
