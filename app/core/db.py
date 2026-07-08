from collections.abc import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _sync_database_url() -> str:
    # Celery workers use the prefork pool by default and are sync by nature;
    # a sync SQLAlchemy engine avoids running a second event loop inside a
    # worker process just to persist job status.
    return settings.database_url.replace("+asyncpg", "+psycopg")


sync_engine = create_engine(_sync_database_url(), pool_pre_ping=True)
SyncSessionLocal: sessionmaker[Session] = sessionmaker(bind=sync_engine, expire_on_commit=False)
