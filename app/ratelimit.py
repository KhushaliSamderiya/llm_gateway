import logging
import uuid

from fastapi import Depends
from redis.exceptions import RedisError

from app.auth import AuthContext, authenticate
from app.errors import GatewayError
from app.redis_client import redis_client

logger = logging.getLogger("gateway.ratelimit")

WINDOW_MS = 60_000

# Runs atomically inside Redis: no other command can interleave between these steps.
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]

local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)

if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_after = window - (now - tonumber(oldest[2]))
  return {0, retry_after}
end

redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, 0}
"""

_script = redis_client.register_script(SLIDING_WINDOW_LUA)


async def check_rate_limit(auth: AuthContext) -> None:
    key = f"rl:key:{auth.api_key_id}"
    try:
        allowed, retry_ms = await _script(
            keys=[key],
            args=[WINDOW_MS, auth.rate_limit_rpm, uuid.uuid4().hex],
        )
    except RedisError:
        # Fail open: a Redis outage shouldn't take down every AI feature
        logger.exception("Rate limiter unavailable; allowing request")
        return

    if not allowed:
        retry_after = max(1, -(-int(retry_ms) // 1000))  # ceiling division to whole seconds
        raise GatewayError(
            429,
            f"Rate limit exceeded ({auth.rate_limit_rpm} requests/minute). "
            f"Retry in {retry_after}s.",
            "rate_limit_error",
            "rate_limit_exceeded",
            headers={"Retry-After": str(retry_after)},
        )


async def rate_limited(auth: AuthContext = Depends(authenticate)) -> AuthContext:
    await check_rate_limit(auth)
    return auth
