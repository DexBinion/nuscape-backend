#!/usr/bin/env python3
"""Recreate DB schema from models (DESTRUCTIVE). Drops all tables then creates them."""
import asyncio
import sys
from backend import models
from backend.database import engine

async def run():
    try:
        async with engine.begin() as conn:
            print("Dropping all tables...")
            await conn.run_sync(models.Base.metadata.drop_all)
            print("Creating all tables...")
            await conn.run_sync(models.Base.metadata.create_all)
        print("Schema recreated successfully.")
    except Exception as e:
        print("Error recreating schema:", e, file=sys.stderr)
        raise

if __name__ == "__main__":
    asyncio.run(run())