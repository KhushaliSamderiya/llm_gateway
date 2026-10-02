import logging

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
                    cost_usd=compute_cost(model, prompt_tokens, completion_tokens),
                    latency_ms=latency_ms,
                    cache_hit=cache_hit,
                    status_code=status_code,
                )
            )
            db.commit()
    except Exception:
        # Never let a logging failure break a request
        logger.exception("Failed to record usage")
