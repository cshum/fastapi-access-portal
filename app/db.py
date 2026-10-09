from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base. Every model inherits from this."""


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """A request-scoped session, yielded as a FastAPI dependency.

    This is FastAPI's answer to NestJS request-scoped providers: the function
    *is* the provider, and `Depends(get_db)` is the injection point. Because it
    is a generator, the `finally` runs after the response is sent, which is what
    closes the session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
