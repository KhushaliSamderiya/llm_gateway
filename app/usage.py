import logging
from decimal import Decimal

from app.db import SessionLocal
from app.models import RequestLog
from app.pricing import compute_cost

logger = logging.getLogger("gateway.usage")


def record_request(
    *,
    team_id: int,
    api_key_id: int,
    model: str,
    provider: str,
    latency_ms: int,
    status_code: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit: bool = False,
) -> None:
    # A cache hit costs nothing, but the token columns keep the size of the
    # cached answer so we can later compute how much the cache saved.
    cost = (
        Decimal("0")
        if cache_hit
        else compute_cost(model, prompt_tokens, completion_tokens)
    )
    try:
        with SessionLocal() as db:
            db.add(
                RequestLog(
                    team_id=team_id,
                    api_key_id=api_key_id,
                    model=model,
                    provider=provider,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    cache_hit=cache_hit,
                    status_code=status_code,
                )
            )
            db.commit()
    except Exception:
        # Never let a logging failure break a request
        logger.exception("Failed to record usage")
