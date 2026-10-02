from app.config import settings
from app.errors import GatewayError
from app.providers.base import Provider
from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider

_gemini = GeminiProvider(settings.gemini_api_key)
_mock = MockProvider(settings.mock_delay_ms, settings.mock_failure_rate)

# Only these model names are accepted. Edit this dict to add models.
MODEL_ROUTES: dict[str, Provider] = {
    "gemini-3.5-flash-lite": _gemini,
    "mock": _mock,
}


def get_provider(model: str) -> Provider:
    provider = MODEL_ROUTES.get(model)
    if provider is None:
        raise GatewayError(
            404,
            f"Model '{model}' is not supported. Available: {', '.join(MODEL_ROUTES)}",
            "invalid_request_error",
            "model_not_found",
        )
    return provider
