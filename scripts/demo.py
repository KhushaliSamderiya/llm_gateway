import argparse
import os
import sys
import time
from decimal import Decimal

import httpx

from app.db import SessionLocal
from app.models import ApiKey, Team
from app.security import generate_api_key, hash_api_key

BASE_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
client = httpx.Client(base_url=BASE_URL, timeout=60)
results: list[bool] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    suffix = f"  ({detail})" if detail else ""
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{suffix}")


def make_key(team_name: str, rpm: int = 60, budget: str = "50.00") -> str:
    raw = generate_api_key()
    with SessionLocal() as db:
        team = Team(name=team_name, monthly_budget_usd=Decimal(budget))
        db.add(team)
        db.flush()
        db.add(
            ApiKey(
                team_id=team.id,
                key_hash=hash_api_key(raw),
                label="demo",
                rate_limit_rpm=rpm,
            )
        )
        db.commit()
    return raw


def chat(key, model: str = "mock", content: str = "hello", **extra):
    body = {"model": model, "messages": [{"role": "user", "content": content}], **extra}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    started = time.perf_counter()
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    return response, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end gateway demo")
    parser.add_argument(
        "--real", action="store_true", help="also make 2 real Gemini calls (free tier)"
    )
    args = parser.parse_args()

    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError:
        print(f"Gateway not reachable at {BASE_URL}. Start uvicorn first.")
        return 2

    run = int(time.time())
    main_key = make_key(f"demo-{run}-main")
    limited_key = make_key(f"demo-{run}-limited", rpm=5)
    broke_key = make_key(f"demo-{run}-broke", budget="0.00")
    print(f"Gateway: {BASE_URL}   (fresh demo teams: demo-{run}-*)")

    section("1. Authentication")
    r, _ = chat(None)
    check("no key is rejected", r.status_code == 401, r.json()["error"]["code"])
    r, _ = chat("gw_wrong_key")
    check("wrong key is rejected", r.status_code == 401, r.json()["error"]["code"])
    r, _ = chat(main_key)
    check("valid key is accepted", r.status_code == 200)

    section("2. PII redaction")
    r, _ = chat(
        main_key,
        content="Contact bob@example.com, card 4111 1111 1111 1111, SSN 123-45-6789",
    )
    seen = r.json()["choices"][0]["message"]["content"]
    flags = r.headers.get("x-gateway-pii-redacted", "")
    print(f"  provider saw: {seen}")
    check("PII types reported in a header", all(t in flags for t in ("EMAIL", "CARD_NUMBER", "SSN")), flags)
    check(
        "raw values never reached the provider",
        "bob@example.com" not in seen and "4111" not in seen and "123-45-6789" not in seen,
    )

    section("3. Response cache")
    q = "Explain what an API gateway does in two sentences."
    r1, t1 = chat(main_key, content=q, temperature=0)
    r2, t2 = chat(main_key, content=q, temperature=0)
    check("first request goes to the provider", r1.headers.get("x-gateway-cache") == "MISS", f"{t1:.0f} ms")
    check("identical request is served from cache", r2.headers.get("x-gateway-cache") == "HIT", f"{t2:.0f} ms")
    check("the cache hit is faster", t2 < t1)

    section("4. Rate limiting (this key allows 5 requests/minute)")
    codes = [chat(limited_key)[0].status_code for _ in range(8)]
    print(f"  status codes: {codes}")
    check("first 5 allowed, next 3 rejected", codes == [200] * 5 + [429] * 3)
    r, _ = chat(limited_key)
    check("rejection says when to retry", "retry-after" in r.headers, f"retry in {r.headers.get('retry-after')}s")

    section("5. Budget enforcement (this team has a $0 budget)")
    r, _ = chat(broke_key)
    check("over-budget team is blocked", r.status_code == 429, r.json()["error"]["code"])

    section("6. Provider failover")
    r, ms = chat(main_key, model="mock-down")
    check(
        "answered even though the primary provider is down",
        r.status_code == 200 and r.headers.get("x-gateway-provider") == "mock",
        f"{ms:.0f} ms",
    )
    check("response reports which provider failed", r.headers.get("x-gateway-fallback-from") == "mock-down")
    r, _ = chat(main_key, model="mock-dead")
    check("every provider down gives a clean 502", r.status_code == 502, r.json()["error"]["code"])

    if args.real:
        section("7. Real model (Gemini, free tier)")
        q = "Explain what a load balancer does in two sentences."
        r1, t1 = chat(main_key, model="gemini-3.5-flash-lite", content=q, temperature=0)
        r2, t2 = chat(main_key, model="gemini-3.5-flash-lite", content=q, temperature=0)
        check("real answer returned", r1.status_code == 200, f"{t1:.0f} ms")
        check(
            "repeat served from cache",
            r2.headers.get("x-gateway-cache") == "HIT",
            f"{t2:.0f} ms, about {t1 / max(t2, 1):.0f}x faster",
        )

    passed = sum(results)
    print(f"\n{passed} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
