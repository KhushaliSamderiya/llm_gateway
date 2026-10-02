from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.schemas import ChatRequest


@dataclass
class ProviderResult:
    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str  # "stop" or "length"


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class Provider(ABC):
    name: str

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ProviderResult: ...
