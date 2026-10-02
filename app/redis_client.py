from redis.asyncio import Redis

from app.config import settings

# Short timeouts so a dead Redis fails fast instead of hanging requests
redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=0.5,
    socket_timeout=0.5,
)

