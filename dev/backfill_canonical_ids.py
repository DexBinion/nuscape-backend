#!/usr/bin/env python3
"""Backfill canonical app_id values for legacy usage rows."""
import asyncio
import os
import sys
from typing import Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import UsageLog, UsageEvent, Device
from backend.app_directory import resolve_app, infer_alias_context


async def backfill_usage_logs(session) -> int:
    batch_size = 200
    total = 0
    while True:
        result = await session.execute(
            select(UsageLog, Device)
            .join(Device, UsageLog.device_id == Device.id)
            .where(UsageLog.app_id.is_(None))
            .order_by(UsageLog.created_at)
            .limit(batch_size)
        )
        rows = result.all()
        if not rows:
            break
        for log, device in rows:
            namespace, raw_ident, display_name = infer_alias_context(
                device.platform,
                app_name=log.app_package or log.app_name,
                domain=log.domain,
            )
            resolution = await resolve_app(
                session,
                namespace=namespace,
                ident=raw_ident,
                display_name=display_name,
            )
            log.app_id = resolution.app.app_id
            log.app_name = resolution.app.display_name
            log.alias_namespace = namespace
            log.alias_ident = resolution.alias.ident
            if namespace == "android" and not log.app_package:
                log.app_package = raw_ident
            if log.domain:
                log.domain = log.domain.strip().lower()
        await session.commit()
        total += len(rows)
    return total


async def backfill_usage_events(session) -> int:
    batch_size = 200
    total = 0
    while True:
        result = await session.execute(
            select(UsageEvent, Device)
            .join(Device, UsageEvent.device_id == Device.id)
            .where(UsageEvent.app_id.is_(None))
            .order_by(UsageEvent.created_at)
            .limit(batch_size)
        )
        rows = result.all()
        if not rows:
            break
        for event, device in rows:
            namespace, raw_ident, display_name = infer_alias_context(
                device.platform,
                app_name=event.app_package or event.app_name,
                domain=event.domain,
            )
            resolution = await resolve_app(
                session,
                namespace=namespace,
                ident=raw_ident,
                display_name=display_name,
            )
            event.app_id = resolution.app.app_id
            event.app_name = resolution.app.display_name
            event.alias_namespace = namespace
            event.alias_ident = resolution.alias.ident
            if namespace == "android" and not event.app_package:
                event.app_package = raw_ident
            if event.domain:
                event.domain = event.domain.strip().lower()
        await session.commit()
        total += len(rows)
    return total


async def main():
    async with AsyncSessionLocal() as session:
        log_count = await backfill_usage_logs(session)
        event_count = await backfill_usage_events(session)
        print(f"Backfilled usage_logs: {log_count}")
        print(f"Backfilled usage_events: {event_count}")


if __name__ == "__main__":
    asyncio.run(main())
