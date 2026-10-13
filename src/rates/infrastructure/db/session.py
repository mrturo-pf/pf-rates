"""Database session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rates.config import settings

_POOL_SIZE = 5
_MAX_OVERFLOW = 0
_POOL_RECYCLE_SECONDS = 300

# Explicit limits implement the pf-db connection-budget contract. The upper
# bound is pool_size + max_overflow = 5 connections per Cloud Run instance.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=_POOL_RECYCLE_SECONDS,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
