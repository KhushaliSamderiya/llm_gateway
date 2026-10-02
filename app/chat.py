import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.concurrency import run_in_threadpool

from app.auth import AuthContext
from app.ratelimit import rate_limited
from app.errors import GatewayError
from app.providers.base import ProviderError
from app.providers.registry import get_provider
from app.schemas import ChatRequest
from app.usage import record_request

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest,
    background: BackgroundTasks,
    auth: AuthContext = Depends(rate_limited),
):
    if request.stream:
        raise GatewayError(
            400,
            "Streaming is not supported yet. Send 'stream': false.",
            "invalid_request_error",
            "streaming_not_supported",
        )

    provider = get_provider(request.model)

    started = time.perf_counter()
    try:
        result = await provider.chat(request)
    except ProviderError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        # Background tasks are dropped when an endpoint raises, so log this one directly
        await run_in_threadpool(
            record_request,
            team_id=auth.team_id,
            api_key_id=auth.api_key_id,
            model=request.model,
            provider=provider.name,
            latency_ms=latency_ms,
            status_code=502,
        )
        raise GatewayError(
            502,
            f"Upstream provider error: {exc.message}",
            "api_error",
            "provider_error",
        ) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    background.add_task(
        record_request,
        team_id=auth.team_id,
        api_key_id=auth.api_key_id,
        model=result.model,
        provider=result.provider,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=latency_ms,
        status_code=200,
    )

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
