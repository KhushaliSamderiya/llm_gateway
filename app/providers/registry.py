from dataclasses import dataclass

from app.config import settings
from app.errors import GatewayError
from app.providers.base import Provider
from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider


@dataclass(frozen=True)
class Route:
    provider: Provider
    model: str  # the model name this provider expects


_gemini = GeminiProvider(settings.gemini_api_key)
_mock = MockProvider(settings.mock_delay_ms, settings.mock_failure_rate)
# Always fails: lets us rehearse an outage without touching a real provider
_mock_down = MockProvider(settings.mock_delay_ms, failure_rate=1.0, name="mock-down")

# Ordered chains: the first route is tried first, the rest are fallbacks.
MODEL_ROUTES: dict[str, list[Route]] = {
    "gemini-3.5-flash-lite": [Route(_gemini, "gemini-3.5-flash-lite")],
    "mock": [Route(_mock, "mock")],
    "mock-down": [Route(_mock_down, "mock-down"), Route(_mock, "mock")],
    "mock-dead": [Route(_mock_down, "mock-dead")],
}


def get_routes(model: str) -> list[Route]:
    routes = MODEL_ROUTES.get(model)
    if routes is None:
        raise GatewayError(
            404,
            f"Model '{model}' is not supported. Available: {', '.join(MODEL_ROUTES)}",
            "invalid_request_error",
            "model_not_found",
        )
    return routes


def get_provider(model: str) -> Provider:
    # Kept for the helper scripts: returns the first provider in the chain
    return get_routes(model)[0].provider
