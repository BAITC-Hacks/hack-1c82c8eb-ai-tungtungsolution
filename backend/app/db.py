from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

DATABASE_URL = make_url(settings.database_url).set(drivername="postgresql+asyncpg")

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


type SessionDep = Annotated[AsyncSession, Depends(get_session)]
