from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db import SessionLocal
from app.models import RequestLog

ADMIN = {"Authorization": "Bearer adm_test_admin_key"}


def add(
    team_id=1,
    key_id=1,
    model="mock",
    provider="mock",
    cost="0",
    latency=100,
    hit=False,
    status=200,
    prompt=0,
    completion=0,
    age_days=0,
):
    with SessionLocal() as db:
        db.add(
            RequestLog(
                team_id=team_id,
                api_key_id=key_id,
                model=model,
                provider=provider,
                prompt_tokens=prompt,
                completion_tokens=completion,
                cost_usd=Decimal(cost),
                latency_ms=latency,
                cache_hit=hit,
                status_code=status,
                created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
            )
        )
        db.commit()


def usage(client, **params):
    return client.get("/admin/v1/usage", params=params, headers=ADMIN)


# ---- access ----
def test_usage_requires_the_admin_key(client):
    assert client.get("/admin/v1/usage").status_code == 401


def test_a_team_key_cannot_read_usage(client, make_key):
    r = client.get("/admin/v1/usage", headers={"Authorization": f"Bearer {make_key()}"})
    assert r.status_code == 401


# ---- empty data ----
def test_empty_database_gives_zeroes_and_no_division_errors(client):
    body = usage(client).json()
    totals = body["totals"]
    assert totals["requests"] == 0
    assert totals["cost_usd"] == "0.000000"
    assert totals["cache_hit_rate"] is None
    assert totals["error_rate"] is None
    assert totals["latency_ms"] == {"p50": None, "p95": None}
    assert body["groups"] == []


# ---- grouping and cost ----
def test_per_team_cost_and_ordering(client, make_key):
    make_key(team="cheap")
    make_key(team="pricey")
    add(team_id=1, key_id=1, cost="0.10")
    add(team_id=2, key_id=2, cost="0.30")
    add(team_id=2, key_id=2, cost="0.20")
    body = usage(client).json()
    assert body["totals"]["requests"] == 3
    assert body["totals"]["cost_usd"] == "0.600000"
    assert [g["label"] for g in body["groups"]] == ["pricey", "cheap"]
    assert body["groups"][0]["cost_usd"] == "0.500000"
    assert body["groups"][0]["requests"] == 2


def test_group_by_model(client, make_key):
    make_key()
    add(model="mock")
    add(model="mock")
    add(model="gemini-3.5-flash-lite", provider="gemini", cost="0.40")
    groups = usage(client, group_by="model").json()["groups"]
    assert [(g["label"], g["requests"]) for g in groups] == [
        ("gemini-3.5-flash-lite", 1),
        ("mock", 2),
    ]


def test_group_by_day_is_chronological(client, make_key):
    make_key()
    add(age_days=2)
    add(age_days=0)
    today = datetime.now(timezone.utc).date()
    keys = [g["key"] for g in usage(client, group_by="day").json()["groups"]]
    assert keys == [(today - timedelta(days=2)).isoformat(), today.isoformat()]


# ---- rates ----
def test_hit_rate_and_error_rate(client, make_key):
    make_key()
    add()
    add()
    add(hit=True)
    add(status=502)
    totals = usage(client).json()["totals"]
    assert totals["requests"] == 4
    assert totals["errors"] == 1
    assert totals["error_rate"] == 0.25
    assert totals["cache_hits"] == 1
    assert totals["cache_hit_rate"] == 0.3333  # 1 hit out of 3 successful requests


# ---- latency ----
def test_latency_percentiles_ignore_cache_hits_and_failures(client, make_key):
    make_key()
    for ms in (100, 200, 300, 400, 1000):
        add(latency=ms)
    add(latency=1, hit=True)
    add(latency=9999, status=502)
    totals = usage(client).json()["totals"]
    assert totals["latency_ms"] == {"p50": 300, "p95": 880}
    assert totals["cached_latency_ms"] == {"p50": 1}


# ---- tokens and savings ----
def test_billable_tokens_exclude_cache_hits(client, make_key):
    make_key()
    add(prompt=10, completion=20)
    add(prompt=1000, completion=2000, hit=True)
    totals = usage(client).json()["totals"]
    assert totals["prompt_tokens"] == 10
    assert totals["completion_tokens"] == 20


def test_cache_savings_are_priced_at_list_price(client, make_key):
    make_key()
    # 1M input tokens ($0.30) + 1M output tokens ($2.50) = $2.80
    add(
        model="gemini-3.5-flash-lite",
        provider="gemini",
        hit=True,
        prompt=1_000_000,
        completion=1_000_000,
    )
    body = usage(client).json()
    assert body["totals"]["saved_usd"] == "2.800000"
    assert body["totals"]["cost_usd"] == "0.000000"
    assert body["groups"][0]["saved_usd"] == "2.800000"


# ---- time window ----
def test_window_excludes_old_rows(client, make_key):
    make_key()
    add(age_days=40)
    add(age_days=1)
    assert usage(client, days=30).json()["totals"]["requests"] == 1
    assert usage(client, days=60).json()["totals"]["requests"] == 2


# ---- validation ----
def test_bad_parameters_are_400(client):
    for params in ({"days": 0}, {"days": 91}, {"group_by": "bogus"}):
        r = usage(client, **params)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "invalid_request"


# ---- end to end ----
def test_usage_reflects_real_traffic(client, chat, make_key):
    key = make_key()
    chat(key, content="same", temperature=0)
    chat(key, content="same", temperature=0)
    totals = usage(client).json()["totals"]
    assert totals["requests"] == 2
    assert totals["cache_hits"] == 1
    assert totals["cache_hit_rate"] == 0.5
