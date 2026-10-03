import hashlib
import json
import logging
from dataclasses import asdict

from redis.exceptions import RedisError

from app.providers.base import ProviderResult
from app.redis_client import redis_client
from app.schemas import ChatRequest

logger = logging.getLogger("gateway.cache")

CACHE_TTL_SECONDS = 3600


def is_cacheable(request: ChatRequest) -> bool:
    # Explicit 0 only: an unset temperature means the provider's default (usually > 0)
    return request.temperature == 0


def make_key(team_id: int, request: ChatRequest) -> str:
    payload = {
        "model": request.model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"cache:{team_id}:{digest}"


async def get_cached(key: str) -> ProviderResult | None:
    try:
        raw = await redis_client.get(key)
    except RedisError:
        logger.exception("Cache unavailable; treating as a miss")
        return None
    if raw is None:
        return None
    try:
        return ProviderResult(**json.loads(raw))
    except (TypeError, ValueError):
        logger.warning("Corrupt cache entry; ignoring it")
        return None


async def set_cached(key: str, result: ProviderResult) -> None:
    if result.finish_reason != "stop":
        return
    try:
        await redis_client.set(key, json.dumps(asdict(result)), ex=CACHE_TTL_SECONDS)
    except RedisError:
        logger.exception("Could not write cache entry")
