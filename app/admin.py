import secrets
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import GatewayError
from app.models import ApiKey, Team
from app.security import generate_api_key, hash_api_key


def require_admin(authorization: str | None = Header(default=None)) -> None:
    configured = settings.admin_api_key
    if not configured:
        raise GatewayError(
            503,
            "Admin API is disabled (ADMIN_API_KEY is not set).",
            "api_error",
            "admin_disabled",
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    # Constant-time comparison, so timing can't leak how much of a guess was right
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        supplied.strip().encode(), configured.encode()
    ):
        raise GatewayError(
            401, "Invalid admin key.", "authentication_error", "invalid_admin_key"
        )


# Auth on the router itself: a new route added here can't forget it
router = APIRouter(
    prefix="/admin/v1", tags=["admin"], dependencies=[Depends(require_admin)]
)

BUDGET = Field(ge=0, le=1_000_000, decimal_places=2)
RPM = Field(ge=1, le=100_000)


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    monthly_budget_usd: Decimal = Field(
        default=Decimal("50.00"), ge=0, le=1_000_000, decimal_places=2
    )


class TeamUpdate(BaseModel):
    monthly_budget_usd: Decimal = BUDGET


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    monthly_budget_usd: Decimal
    created_at: datetime


class KeyCreate(BaseModel):
    label: str = Field(default="", max_length=100)
    rate_limit_rpm: int = Field(default=60, ge=1, le=100_000)


class KeyUpdate(BaseModel):
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100_000)
    is_active: bool | None = None


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    label: str
    rate_limit_rpm: int
    is_active: bool
    created_at: datetime


class KeyCreated(KeyOut):
    api_key: str
    warning: str = "Store this key now. It cannot be shown again."


def _not_found(what: str, ident: int) -> GatewayError:
    return GatewayError(
        404,
        f"{what.capitalize()} {ident} not found.",
        "invalid_request_error",
        f"{what}_not_found",
    )


def _get_team(db: Session, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise _not_found("team", team_id)
    return team


@router.post("/teams", status_code=201, response_model=TeamOut)
def create_team(body: TeamCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise GatewayError(
            400, "Team name cannot be blank.", "invalid_request_error", "invalid_request"
        )
    team = Team(name=name, monthly_budget_usd=body.monthly_budget_usd)
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GatewayError(
            409,
            f"A team named '{name}' already exists.",
            "invalid_request_error",
            "team_exists",
        )
    db.refresh(team)
    return team


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)):
    return db.scalars(select(Team).order_by(Team.id)).all()


@router.patch("/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, body: TeamUpdate, db: Session = Depends(get_db)):
    team = _get_team(db, team_id)
    team.monthly_budget_usd = body.monthly_budget_usd
    db.commit()
    db.refresh(team)
    return team


@router.post("/teams/{team_id}/keys", status_code=201, response_model=KeyCreated)
def create_key(
    team_id: int,
    body: KeyCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    _get_team(db, team_id)
    raw = generate_api_key()
    row = ApiKey(
        team_id=team_id,
        key_hash=hash_api_key(raw),
        label=body.label,
        rate_limit_rpm=body.rate_limit_rpm,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    response.headers["Cache-Control"] = "no-store"
    return KeyCreated(**KeyOut.model_validate(row).model_dump(), api_key=raw)


@router.get("/teams/{team_id}/keys", response_model=list[KeyOut])
def list_keys(team_id: int, db: Session = Depends(get_db)):
    _get_team(db, team_id)
    return db.scalars(
        select(ApiKey).where(ApiKey.team_id == team_id).order_by(ApiKey.id)
    ).all()


@router.patch("/keys/{key_id}", response_model=KeyOut)
def update_key(key_id: int, body: KeyUpdate, db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise GatewayError(
            400,
            "Nothing to update. Send rate_limit_rpm and/or is_active.",
            "invalid_request_error",
            "invalid_request",
        )
    row = db.get(ApiKey, key_id)
    if row is None:
        raise _not_found("key", key_id)
    for field, value in changes.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row
