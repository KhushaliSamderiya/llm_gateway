import logging

from app.providers.base import ProviderError, ProviderResult
from app.providers.registry import Route
from app.schemas import ChatRequest

logger = logging.getLogger("gateway.fallback")


class FallbackExhausted(Exception):
    def __init__(self, error: ProviderError, failed: list[str]):
        super().__init__(error.message)
        self.error = error
        self.failed = failed


async def call_with_fallback(
    routes: list[Route], request: ChatRequest
) -> tuple[ProviderResult, list[str]]:
    """Try each route in order. Returns (result, names of providers that failed first)."""
    failed: list[str] = []
    last_error: ProviderError | None = None

    for route in routes:
        # Each provider gets the model name it understands
        attempt = request.model_copy(update={"model": route.model})
        try:
            result = await route.provider.chat(attempt)
            return result, failed
        except ProviderError as exc:
            failed.append(route.provider.name)
            last_error = exc
            if not exc.retryable:
                # A bad request would fail everywhere, so stop here
                break
            logger.warning(
                "Provider %s failed (%s); trying next", route.provider.name, exc.message
            )

    assert last_error is not None
    raise FallbackExhausted(last_error, failed)
