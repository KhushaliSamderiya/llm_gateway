import time
import uuid

from fastapi import APIRouter, Depends

from app.auth import AuthContext, authenticate
from app.errors import GatewayError
from app.providers.base import ProviderError
from app.providers.registry import get_provider
from app.schemas import ChatRequest

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest, auth: AuthContext = Depends(authenticate)
):
    if request.stream:
        raise GatewayError(
            400,
            "Streaming is not supported yet. Send 'stream': false.",
            "invalid_request_error",
            "streaming_not_supported",
        )

    provider = get_provider(request.model)

    try:
        result = await provider.chat(request)
    except ProviderError as exc:
        raise GatewayError(
            502,
            f"Upstream provider error: {exc.message}",
            "api_error",
            "provider_error",
        ) from exc

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": result.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.prompt_tokens + result.completion_tokens,
        },
    }
