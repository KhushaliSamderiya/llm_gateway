from dataclasses import dataclass
from decimal import Decimal

from fastapi import Header
from sqlalchemy import select

from app.db import SessionLocal
from app.errors import GatewayError
from app.models import ApiKey, Team
from app.security import hash_api_key


@dataclass
class AuthContext:
    team_id: int
    team_name: str
    api_key_id: int
    rate_limit_rpm: int
    monthly_budget_usd: Decimal


def authenticate(authorization: str | None = Header(default=None)) -> AuthContext:
    scheme, _, raw_key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw_key.strip():
        raise GatewayError(
            401,
            "Missing API key. Send 'Authorization: Bearer <key>'.",
            "authentication_error",
            "missing_api_key",
        )

    # A short-lived session: the connection returns to the pool as soon as the lookup
    # is done, instead of being held through the slow provider call.
    with SessionLocal() as db:
        row = db.execute(
            select(ApiKey, Team)
            .join(Team, Team.id == ApiKey.team_id)
            .where(ApiKey.key_hash == hash_api_key(raw_key.strip()))
        ).first()

        if row is None or not row.ApiKey.is_active:
            raise GatewayError(
                401, "Invalid API key.", "authentication_error", "invalid_api_key"
            )

        return AuthContext(
            team_id=row.Team.id,
            team_name=row.Team.name,
            api_key_id=row.ApiKey.id,
            rate_limit_rpm=row.ApiKey.rate_limit_rpm,
            monthly_budget_usd=row.Team.monthly_budget_usd,
        )
