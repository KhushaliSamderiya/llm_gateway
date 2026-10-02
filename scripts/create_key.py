import argparse
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, Team
from app.security import generate_api_key, hash_api_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an API key (and its team if new)")
    parser.add_argument("--team", required=True)
    parser.add_argument("--budget", type=Decimal, default=Decimal("50.00"))
    parser.add_argument("--rpm", type=int, default=60)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    with SessionLocal() as db:
        team = db.scalar(select(Team).where(Team.name == args.team))
        if team is None:
            team = Team(name=args.team, monthly_budget_usd=args.budget)
            db.add(team)
            db.flush()  # assigns team.id without committing yet

        raw_key = generate_api_key()
        db.add(
            ApiKey(
                team_id=team.id,
                key_hash=hash_api_key(raw_key),
                label=args.label,
                rate_limit_rpm=args.rpm,
            )
        )
        db.commit()

        print(f"Team:  {team.name} (id={team.id})")
        print(f"Key:   {raw_key}")
        print("Save this key now. It is not stored anywhere and cannot be shown again.")


if __name__ == "__main__":
    main()
