import asyncio
import random

from app.providers.base import Provider, ProviderError, ProviderResult
from app.schemas import ChatRequest


class MockProvider(Provider):
    name = "mock"

    def __init__(self, delay_ms: int = 200, failure_rate: float = 0.0):
        self.delay_ms = delay_ms
        self.failure_rate = failure_rate

    async def chat(self, request: ChatRequest) -> ProviderResult:
        await asyncio.sleep(self.delay_ms / 1000)

        if random.random() < self.failure_rate:
            raise ProviderError(
                "Mock provider simulated failure", retryable=True, status_code=503
            )

        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        content = f"[mock] You said: {last_user}"
        return ProviderResult(
            content=content,
            model=request.model,
            provider=self.name,
            # Rough word-count "tokens"; only the real provider's numbers are exact
            prompt_tokens=sum(len(m.content.split()) for m in request.messages),
            completion_tokens=len(content.split()),
            finish_reason="stop",
        )
