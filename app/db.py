from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# pool_timeout: fail fast (5 s) instead of hanging a request for 30 s when the pool is exhausted
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_timeout=5)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db
