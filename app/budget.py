import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.concurrency import run_in_threadpool
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.auth import AuthContext
from app.db import SessionLocal
from app.errors import GatewayError
from app.models import RequestLog
from app.redis_client import redis_client

logger = logging.getLogger("gateway.budget")

MICROS = Decimal(1_000_000)
KEY_TTL_SECONDS = 35 * 24 * 3600


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _key(team_id: int) -> str:
    return f"spend:team:{team_id}:{_month_start():%Y-%m}"


def _to_micros(usd: Decimal) -> int:
    return int((Decimal(usd) * MICROS).to_integral_value())


def _sum_month_spend(team_id: int) -> Decimal:
    with SessionLocal() as db:
        total = db.scalar(
            select(func.coalesce(func.sum(RequestLog.cost_usd), 0)).where(
                RequestLog.team_id == team_id,
                RequestLog.created_at >= _month_start(),
            )
        )
    return Decimal(total)


async def check_budget(auth: AuthContext) -> None:
    key = _key(auth.team_id)
    try:
        spent = await redis_client.get(key)
        if spent is None:
            # Missing counter: rebuild it from the source of truth (Postgres)
            seeded = _to_micros(await run_in_threadpool(_sum_month_spend, auth.team_id))
            # NX: if a concurrent request seeded it first, keep that value
            await redis_client.set(key, seeded, nx=True, ex=KEY_TTL_SECONDS)
            spent = await redis_client.get(key)
        spent_micros = int(spent)
    except RedisError:
        logger.exception("Budget check unavailable; allowing request")
        return

    if spent_micros >= _to_micros(auth.monthly_budget_usd):
        raise GatewayError(
            429,
            f"Monthly budget of ${auth.monthly_budget_usd} has been reached.",
            "insufficient_quota",
            "monthly_budget_exceeded",
        )


async def record_spend(team_id: int, cost_usd: Decimal) -> None:
    micros = _to_micros(cost_usd)
    if micros <= 0:
        return
    key = _key(team_id)
    try:
        # Only increment an existing counter. If it expired or was flushed, skip:
        # creating it here would store a partial total and block re-seeding.
        if await redis_client.exists(key):
            await redis_client.incrby(key, micros)
    except RedisError:
        logger.exception("Could not record spend")
