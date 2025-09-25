import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import select

from backend import models, crud, policy_store
from backend.app_directory import resolve_app
from backend.app_seeds import load_app_seeds
from backend.schemas import UsageEntry, ControlsState


@pytest.mark.asyncio
async def test_resolve_app_creates_and_reuses_alias(session):
    result1 = await resolve_app(
        session,
        namespace="web",
        ident="example.com",
        display_name="Example",
    )
    await session.commit()

    result2 = await resolve_app(
        session,
        namespace="web",
        ident="example.com",
        display_name="Example Duplicate",
    )

    assert result1.app.app_id == result2.app.app_id
    assert result2.created_app is False
    assert result2.alias.app_id == result1.app.app_id


@pytest.mark.asyncio
async def test_get_top_apps_returns_platform_breakdown(session):
    await load_app_seeds(session)

    now = datetime.now(timezone.utc)

    android_device = models.Device(
        id=uuid.uuid4(),
        platform="android",
        name="Pixel",
        jwt_secret="secret-android",
        created_at=now,
        last_seen_at=now,
    )
    windows_device = models.Device(
        id=uuid.uuid4(),
        platform="windows",
        name="Laptop",
        jwt_secret="secret-windows",
        created_at=now,
        last_seen_at=now,
    )
    session.add_all([android_device, windows_device])
    await session.flush()

    entries_android = [
        UsageEntry(
            app_name="com.google.android.youtube",
            domain=None,
            start=now - timedelta(minutes=30),
            end=now - timedelta(minutes=20),
            duration=600,
        )
    ]
    entries_windows = [
        UsageEntry(
            app_name="YouTube",
            domain="youtube.com",
            start=now - timedelta(minutes=25),
            end=now - timedelta(minutes=5),
            duration=1200,
        )
    ]

    await crud.create_usage_logs(session, android_device, entries_android)
    await crud.create_usage_logs(session, windows_device, entries_windows)

    start = now - timedelta(hours=1)
    end = now
    top_apps = await crud.get_top_apps(session, start, end, limit=5, device_id=None)
    assert top_apps, "Expected at least one top app entry"
    first = top_apps[0]
    assert first.breakdown
    assert first.breakdown.get("android", 0) > 0
    assert first.breakdown.get("windows", 0) > 0


@pytest.mark.asyncio
async def test_blocked_app_produces_violation(session):
    now = datetime.now(timezone.utc)
    device = models.Device(
        id=uuid.uuid4(),
        platform="android",
        name="Pixel",
        jwt_secret="secret",
        created_at=now,
        last_seen_at=now,
    )
    session.add(device)
    await session.flush()

    resolution = await resolve_app(
        session,
        namespace="web",
        ident="blocked.example",
        display_name="Blocked",
    )
    await session.commit()

    blocked_state = ControlsState(blocked_app_ids=[resolution.app.app_id])
    policy_store.set_controls(blocked_state)

    entry = UsageEntry(
        app_name="Blocked",
        domain="blocked.example",
        start=now - timedelta(minutes=10),
        end=now - timedelta(minutes=5),
        duration=300,
    )

    result = await crud.create_usage_logs(session, device, [entry])
    assert result.accepted == 0

    violations = (await session.execute(select(models.PolicyViolation))).scalars().all()
    assert len(violations) == 1
    assert violations[0].app_id == resolution.app.app_id
