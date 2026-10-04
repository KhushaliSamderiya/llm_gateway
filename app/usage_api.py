from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.admin import require_admin
from app.db import get_db
from app.usage_stats import usage_report

router = APIRouter(
    prefix="/admin/v1", tags=["usage"], dependencies=[Depends(require_admin)]
)


@router.get("/usage")
def usage(
    days: int = Query(30, ge=1, le=90),
    group_by: Literal["team", "model", "provider", "day"] = "team",
    db: Session = Depends(get_db),
):
    return usage_report(db, days, group_by)
