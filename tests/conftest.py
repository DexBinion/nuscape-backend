import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from backend import models, policy_store


def _make_engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture
async def session():
    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as sess:
        policy_store.reset()
        yield sess

    await engine.dispose()
