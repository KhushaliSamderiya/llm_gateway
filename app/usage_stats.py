from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.orm import Session

from app.models import RequestLog, Team
from app.pricing import compute_cost

HIT = RequestLog.cache_hit.is_(True)
MISS = RequestLog.cache_hit.is_(False)
OK = RequestLog.status_code < 400
FAILED = RequestLog.status_code >= 400
LIVE = and_(OK, MISS)  # successful calls that really went to a provider
CACHED = and_(OK, HIT)

# literal_column keeps 'day' and 'UTC' out of bind parameters: the SELECT and GROUP BY
# copies of this expression must be textually identical, or Postgres rejects the query.
GROUPS = {
    "team": RequestLog.team_id,
    "model": RequestLog.model,
    "provider": RequestLog.provider,
    "day": func.date_trunc(
        literal_column("'day'"),
        func.timezone(literal_column("'UTC'"), RequestLog.created_at),
    ),
}


def _pct(fraction: str):
    return func.percentile_cont(literal_column(fraction)).within_group(
        RequestLog.latency_ms
    )


def _aggregates() -> list:
    return [
        func.count().label("requests"),
        func.count().filter(FAILED).label("errors"),
        func.count().filter(OK).label("successes"),
        func.count().filter(HIT).label("cache_hits"),
        func.coalesce(func.sum(RequestLog.cost_usd), 0).label("cost_usd"),
        func.coalesce(func.sum(RequestLog.prompt_tokens).filter(MISS), 0).label(
            "prompt_tokens"
        ),
        func.coalesce(func.sum(RequestLog.completion_tokens).filter(MISS), 0).label(
            "completion_tokens"
        ),
        _pct("0.5").filter(LIVE).label("p50"),
        _pct("0.95").filter(LIVE).label("p95"),
        _pct("0.5").filter(CACHED).label("cached_p50"),
    ]


def _saved(db: Session, since: datetime, group_col) -> dict:
    """What the cache hits would have cost at list price, per group (None = overall)."""
    cols = [RequestLog.model] if group_col is None else [group_col, RequestLog.model]
    rows = db.execute(
        select(
            *cols,
            func.sum(RequestLog.prompt_tokens),
            func.sum(RequestLog.completion_tokens),
        )
        .where(RequestLog.created_at >= since, CACHED)
        .group_by(*cols)
    ).all()
    saved: dict = defaultdict(Decimal)
    for row in rows:
        key = None if group_col is None else row[0]
        model, prompt, completion = row[-3], row[-2], row[-1]
        saved[key] += compute_cost(model, int(prompt), int(completion))
    return saved


def _ratio(part: int, whole: int):
    return round(part / whole, 4) if whole else None


def _ms(value):
    return None if value is None else round(value)


def _money(value) -> str:
    return f"{Decimal(value):.6f}"


def _shape(row, saved: Decimal) -> dict:
    return {
        "requests": row.requests,
        "errors": row.errors,
        "error_rate": _ratio(row.errors, row.requests),
        "cache_hits": row.cache_hits,
        "cache_hit_rate": _ratio(row.cache_hits, row.successes),
        "cost_usd": _money(row.cost_usd),
        "saved_usd": _money(saved),
        "prompt_tokens": int(row.prompt_tokens),
        "completion_tokens": int(row.completion_tokens),
        "latency_ms": {"p50": _ms(row.p50), "p95": _ms(row.p95)},
        "cached_latency_ms": {"p50": _ms(row.cached_p50)},
    }


def _labels(db: Session, group_by: str, keys: list) -> dict:
    if group_by == "team":
        names = dict(
            db.execute(select(Team.id, Team.name).where(Team.id.in_(keys))).all()
        )
        return {k: names.get(k, f"team {k}") for k in keys}
    if group_by == "day":
        return {k: k.date().isoformat() for k in keys}
    return {k: str(k) for k in keys}


def usage_report(db: Session, days: int, group_by: str) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    in_window = RequestLog.created_at >= since

    totals_row = db.execute(select(*_aggregates()).where(in_window)).one()
    totals = _shape(totals_row, _saved(db, since, None).get(None, Decimal(0)))

    group_col = GROUPS[group_by]
    rows = db.execute(
        select(group_col.label("grp"), *_aggregates())
        .where(in_window)
        .group_by(group_col)
    ).all()
    saved = _saved(db, since, group_col)
    labels = _labels(db, group_by, [r.grp for r in rows])

    groups = [
        {
            "key": r.grp.date().isoformat() if group_by == "day" else r.grp,
            "label": labels[r.grp],
            **_shape(r, saved.get(r.grp, Decimal(0))),
        }
        for r in rows
    ]
    if group_by == "day":
        groups.sort(key=lambda g: g["key"])
    else:
        groups.sort(key=lambda g: Decimal(g["cost_usd"]), reverse=True)

    return {
        "window": {"days": days, "since": since.isoformat()},
        "group_by": group_by,
        "totals": totals,
        "groups": groups,
    }
