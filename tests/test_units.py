import asyncio
from decimal import Decimal

import pytest

from app.cache import is_cacheable, make_key
from app.fallback import FallbackExhausted, call_with_fallback
from app.pricing import compute_cost
from app.providers.base import Provider, ProviderError, ProviderResult
from app.providers.registry import Route
from app.schemas import ChatRequest, Message
from app.security import generate_api_key, hash_api_key


def req(content: str = "hi", **kwargs) -> ChatRequest:
    return ChatRequest(
        model="m", messages=[Message(role="user", content=content)], **kwargs
    )


# ---- cache keys ----
def test_only_explicit_temperature_zero_is_cacheable():
    assert is_cacheable(req(temperature=0))
    assert not is_cacheable(req())
    assert not is_cacheable(req(temperature=0.7))


def test_cache_key_is_stable():
    assert make_key(1, req(temperature=0)) == make_key(1, req(temperature=0))


def test_cache_key_differs_by_team():
    assert make_key(1, req(temperature=0)) != make_key(2, req(temperature=0))


def test_cache_key_differs_by_max_tokens():
    assert make_key(1, req(temperature=0)) != make_key(1, req(temperature=0, max_tokens=50))


def test_cache_key_differs_by_content():
    assert make_key(1, req("a", temperature=0)) != make_key(1, req("b", temperature=0))


# ---- pricing ----
def test_gemini_cost_matches_hand_calculation():
    # 10 in * $0.30/M + 48 out * $2.50/M = $0.000123. If prices change, update PRICES and this.
    assert compute_cost("gemini-3.5-flash-lite", 10, 48) == Decimal("0.000123")


def test_mock_is_free():
    assert compute_cost("mock", 1000, 1000) == Decimal("0")


def test_unknown_model_costs_nothing():
    assert compute_cost("no-such-model", 10, 10) == Decimal("0")


# ---- API keys ----
def test_hash_is_deterministic_and_64_hex_chars():
    h = hash_api_key("gw_abc")
    assert h == hash_api_key("gw_abc")
    assert len(h) == 64
    assert h != hash_api_key("gw_abd")


def test_generated_keys_are_prefixed_and_unique():
    a, b = generate_api_key(), generate_api_key()
    assert a.startswith("gw_")
    assert a != b


# ---- fallback logic (with fake providers) ----
class Fake(Provider):
    def __init__(self, name: str, error: ProviderError | None = None):
        self.name = name
        self.error = error
        self.seen_models: list[str] = []

    async def chat(self, request):
        self.seen_models.append(request.model)
        if self.error:
            raise self.error
        return ProviderResult(
            content="ok",
            model=request.model,
            provider=self.name,
            prompt_tokens=1,
            completion_tokens=1,
            finish_reason="stop",
        )


def transient() -> ProviderError:
    return ProviderError("boom", retryable=True, status_code=503)


def test_falls_back_when_first_provider_fails():
    a, b = Fake("a", transient()), Fake("b")
    result, failed = asyncio.run(
        call_with_fallback([Route(a, "model-a"), Route(b, "model-b")], req())
    )
    assert result.provider == "b"
    assert failed == ["a"]


def test_each_provider_receives_its_own_model_name():
    a, b = Fake("a", transient()), Fake("b")
    asyncio.run(call_with_fallback([Route(a, "model-a"), Route(b, "model-b")], req()))
    assert a.seen_models == ["model-a"]
    assert b.seen_models == ["model-b"]


def test_non_retryable_error_stops_the_chain():
    a = Fake("a", ProviderError("bad request", retryable=False, status_code=400))
    b = Fake("b")
    with pytest.raises(FallbackExhausted) as exc:
        asyncio.run(call_with_fallback([Route(a, "m"), Route(b, "m")], req()))
    assert b.seen_models == []
    assert exc.value.failed == ["a"]


def test_all_providers_failing_raises_with_every_failure_listed():
    a, b = Fake("a", transient()), Fake("b", transient())
    with pytest.raises(FallbackExhausted) as exc:
        asyncio.run(call_with_fallback([Route(a, "m"), Route(b, "m")], req()))
    assert exc.value.failed == ["a", "b"]
