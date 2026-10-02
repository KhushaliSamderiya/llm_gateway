import asyncio
import sys

from app.providers.base import ProviderError
from app.providers.registry import get_provider
from app.schemas import ChatRequest, Message


async def main(models: list[str]) -> None:
    for model in models:
        request = ChatRequest(
            model=model,
            messages=[
                Message(role="system", content="Answer in one short sentence."),
                Message(role="user", content="What is an LLM gateway?"),
            ],
            temperature=0,
        )
        try:
            result = await get_provider(model).chat(request)
            print(f"\n{model}\n  {result}")
        except ProviderError as exc:
            print(f"\n{model}\n  ProviderError: {exc.message} (retryable={exc.retryable})")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["mock", "gemini-3.5-flash-lite"]))
