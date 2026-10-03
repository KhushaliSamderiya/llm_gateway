import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from fastapi.concurrency import run_in_threadpool

from app.auth import AuthContext
from app.budget import check_budget, record_spend
from app.cache import get_cached, is_cacheable, make_key, set_cached
from app.errors import GatewayError
from app.fallback import FallbackExhausted, call_with_fallback
from app.pii import redact_messages
from app.pricing import compute_cost
from app.providers.base import ProviderResult
from app.providers.registry import get_routes
from app.ratelimit import rate_limited
from app.schemas import ChatRequest
from app.usage import record_request

router = APIRouter()


def _completion_body(result: ProviderResult) -> dict:
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


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest,
    background: BackgroundTasks,
    response: Response,
    auth: AuthContext = Depends(rate_limited),
):
    if request.stream:
        raise GatewayError(
            400,
            "Streaming is not supported yet. Send 'stream': false.",
            "invalid_request_error",
            "streaming_not_supported",
        )

    await check_budget(auth)

    # Mask PII before anything else sees the prompt (cache key, providers)
    clean_messages, redactions = redact_messages(request.messages)
    request = request.model_copy(update={"messages": clean_messages})
    if redactions:
        response.headers["X-Gateway-PII-Redacted"] = ",".join(
            f"{label}={count}" for label, count in sorted(redactions.items())
        )

    routes = get_routes(request.model)  # 404 for unknown models

    cache_key = make_key(auth.team_id, request) if is_cacheable(request) else None
    if cache_key is None:
        response.headers["X-Gateway-Cache"] = "BYPASS"
    else:
        lookup_started = time.perf_counter()
        cached = await get_cached(cache_key)
        if cached is not None:
            response.headers["X-Gateway-Cache"] = "HIT"
            response.headers["X-Gateway-Provider"] = cached.provider
            background.add_task(
                record_request,
                team_id=auth.team_id,
                api_key_id=auth.api_key_id,
                model=cached.model,
                provider=cached.provider,
                prompt_tokens=cached.prompt_tokens,
                completion_tokens=cached.completion_tokens,
                latency_ms=int((time.perf_counter() - lookup_started) * 1000),
                status_code=200,
                cache_hit=True,
            )
            return _completion_body(cached)
        response.headers["X-Gateway-Cache"] = "MISS"

    started = time.perf_counter()
    try:
        result, failed = await call_with_fallback(routes, request)
    except FallbackExhausted as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        # Background tasks are dropped when an endpoint raises, so log this one directly
        await run_in_threadpool(
            record_request,
            team_id=auth.team_id,
            api_key_id=auth.api_key_id,
            model=request.model,
            provider=exc.failed[-1],
            latency_ms=latency_ms,
            status_code=502,
        )
        raise GatewayError(
            502,
            f"Upstream provider error: {exc.error.message}",
            "api_error",
            "provider_error",
        ) from exc.error

    latency_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Gateway-Provider"] = result.provider
    if failed:
        response.headers["X-Gateway-Fallback-From"] = ",".join(failed)

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
    await record_spend(
        auth.team_id,
        compute_cost(result.model, result.prompt_tokens, result.completion_tokens),
    )

    # Answers from a backup provider are never cached
    if cache_key is not None and not failed:
        await set_cached(cache_key, result)

    return _completion_body(result)
