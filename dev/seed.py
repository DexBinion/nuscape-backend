#!/usr/bin/env python3
"""
Seed script to insert dummy device and usage logs for testing the dashboard
Run with: python dev/seed.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Add parent directory to path so we can import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from backend.database import AsyncSessionLocal, engine
from backend.models import Base, Device
from backend.schemas import UsageEntry
from backend.app_seeds import load_app_seeds
from backend import crud


async def create_seed_data():
    """Create seed data for testing."""
    async with engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)

    # Ensure canonical app directory has baseline entries
    async with AsyncSessionLocal() as seed_session:
        await load_app_seeds(seed_session)

    async with AsyncSessionLocal() as db:
        try:
            print("Creating seed data...")

            existing_devices = await db.execute(
                select(Device).where(Device.device_key.in_(["test_device_key_1", "test_device_key_2"]))
            )
            existing_count = len(existing_devices.scalars().all())

            if existing_count > 0:
                print(f"Found {existing_count} existing test devices. Skipping device creation.")
                return

            # Create dummy devices with JWT secrets for the new auth model
            device1 = Device(
                id=uuid.uuid4(),
                platform="android",
                name="Pixel 7",
                device_key="test_device_key_1",
                jwt_secret=str(uuid.uuid4()),
                last_seen_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc) - timedelta(days=5),
            )

            device2 = Device(
                id=uuid.uuid4(),
                platform="ios",
                name="iPhone 14",
                device_key="test_device_key_2",
                jwt_secret=str(uuid.uuid4()),
                last_seen_at=datetime.now(timezone.utc) - timedelta(hours=2),
                created_at=datetime.now(timezone.utc) - timedelta(days=3),
            )

            db.add_all([device1, device2])
            await db.flush()  # Flush to assign primary keys prior to usage creation

            today = datetime.now(timezone.utc)

            device1_entries = [
                UsageEntry(
                    app_name="YouTube",
                    domain="youtube.com",
                    start=today.replace(hour=9, minute=0, second=0, microsecond=0),
                    end=today.replace(hour=9, minute=25, second=30, microsecond=0),
                    duration=1530,
                ),
                UsageEntry(
                    app_name="TikTok",
                    domain="tiktok.com",
                    start=today.replace(hour=12, minute=0, second=0, microsecond=0),
                    end=today.replace(hour=12, minute=15, second=10, microsecond=0),
                    duration=910,
                ),
                UsageEntry(
                    app_name="Instagram",
                    domain="instagram.com",
                    start=today.replace(hour=14, minute=30, second=0, microsecond=0),
                    end=today.replace(hour=14, minute=50, second=0, microsecond=0),
                    duration=1200,
                ),
                UsageEntry(
                    app_name="Chrome",
                    domain="github.com",
                    start=today.replace(hour=16, minute=0, second=0, microsecond=0),
                    end=today.replace(hour=17, minute=30, second=0, microsecond=0),
                    duration=5400,
                ),
            ]

            device2_entries = [
                UsageEntry(
                    app_name="Safari",
                    domain="apple.com",
                    start=today.replace(hour=10, minute=0, second=0, microsecond=0),
                    end=today.replace(hour=10, minute=45, second=0, microsecond=0),
                    duration=2700,
                ),
                UsageEntry(
                    app_name="TikTok",
                    domain="tiktok.com",
                    start=today.replace(hour=13, minute=0, second=0, microsecond=0),
                    end=today.replace(hour=13, minute=30, second=0, microsecond=0),
                    duration=1800,
                ),
                UsageEntry(
                    app_name="YouTube",
                    domain="youtube.com",
                    start=today.replace(hour=15, minute=0, second=0, microsecond=0),
                    end=today.replace(hour=15, minute=20, second=0, microsecond=0),
                    duration=1200,
                ),
            ]

            yesterday = today - timedelta(days=1)
            device1_entries.append(
                UsageEntry(
                    app_name="YouTube",
                    domain="youtube.com",
                    start=yesterday.replace(hour=20, minute=0, second=0, microsecond=0),
                    end=yesterday.replace(hour=21, minute=30, second=0, microsecond=0),
                    duration=5400,
                )
            )
            device2_entries.append(
                UsageEntry(
                    app_name="Instagram",
                    domain="instagram.com",
                    start=yesterday.replace(hour=18, minute=0, second=0, microsecond=0),
                    end=yesterday.replace(hour=18, minute=45, second=0, microsecond=0),
                    duration=2700,
                )
            )

            created_1 = await crud.create_usage_logs(db, device1, device1_entries)
            created_2 = await crud.create_usage_logs(db, device2, device2_entries)

            print(f" - Created {len([device1, device2])} devices")
            print(f" - Logged {created_1 + created_2} usage entries")
            print("\nDevices:")
            print(f"  - {device1.name} ({device1.platform}) - Key: {device1.device_key}")
            print(f"  - {device2.name} ({device2.platform}) - Key: {device2.device_key}")
            print("\nSeed data created successfully!")
            print("\nYou can now test the API:")
            print("  - GET /health")
            print("  - GET /api/v1/dashboard/devices")
            print("  - GET /api/v1/dashboard/apps/top")
            print("  - GET /api/v1/dashboard/stats/today")

        except Exception as exc:
            await db.rollback()
            print(f"Error creating seed data: {exc}")
            raise


if __name__ == "__main__":
    asyncio.run(create_seed_data())
