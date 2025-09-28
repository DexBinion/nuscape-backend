#!/usr/bin/env python3
"""Utility to run daily rollup aggregation from the CLI."""

import argparse
import asyncio
from datetime import datetime
from typing import Optional

from backend import database
from backend.rollups import run_daily_rollups, SESSION_GAP_SECONDS


def _parse_date(date_str: Optional[str]):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except ValueError as exc:
        raise SystemExit(f"Invalid date format '{date_str}'; expected YYYY-MM-DD") from exc


async def _run(date_str: Optional[str], account: str, gap: int) -> None:
    target_date = _parse_date(date_str)

    if database.AsyncSessionLocal is None:
        raise SystemExit("Database engine is not initialized; call init_engine() first")

    async with database.AsyncSessionLocal() as session:
        result = await run_daily_rollups(
            session,
            target_date=target_date,
            account_id=account,
            gap_seconds=gap,
        )
    print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NuScape daily rollups")
    parser.add_argument("--date", help="Target date (YYYY-MM-DD). Defaults to yesterday.")
    parser.add_argument("--account", default="default", help="Account identifier (default: default)")
    parser.add_argument(
        "--gap",
        type=int,
        default=SESSION_GAP_SECONDS,
        help=f"Gap in seconds between fragments to merge (default: {SESSION_GAP_SECONDS})",
    )
    args = parser.parse_args()

    database.init_engine()
    asyncio.run(_run(args.date, args.account, args.gap))


if __name__ == "__main__":
    main()
