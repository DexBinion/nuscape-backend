#!/usr/bin/env python3
"""
Quick DB query helper — prints usage_logs counts and a few sample rows per device.

Run from repository root:
python tools/query_usage_logs.py
"""
import asyncio
import os
from urllib.parse import urlparse, urlunparse, parse_qs
import asyncpg
from pathlib import Path

# Load .env if present (simple parser like tools/db_inspect.py)
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf8").splitlines():
        ln = line.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL not found in environment or .env")

# Normalize for asyncpg
_parsed = urlparse(DATABASE_URL)
_query = parse_qs(_parsed.query or "")
_use_ssl = False
if "sslmode" in _query:
    sslmode_val = _query.get("sslmode", [""])[0].lower()
    if sslmode_val and sslmode_val != "disable":
        _use_ssl = True

_scheme = _parsed.scheme
if "+asyncpg" in _scheme:
    _scheme = _scheme.replace("+asyncpg", "")
_clean = _parsed._replace(scheme=_scheme, query="")
DSN = urlunparse(_clean)

async def run():
    ssl_arg = True if _use_ssl else None
    print("Connecting to DB:", DSN)
    try:
        conn = await asyncpg.connect(dsn=DSN, ssl=ssl_arg)
    except Exception as e:
        print("Failed to connect to DB:", e)
        return

    try:
        print("\n-- devices (latest 20) --")
        devices = await conn.fetch("SELECT id, name, platform, created_at, last_seen_at FROM devices ORDER BY created_at DESC LIMIT 20")
        if not devices:
            print("No devices found.")
        for d in devices:
            print(dict(d))

        print("\n-- usage_logs counts --")
        total = await conn.fetchval("SELECT count(*) FROM usage_logs")
        print("usage_logs total:", total)

        print("\n-- usage_logs counts per recent device --")
        for d in devices[:5]:
            dev_id = d["id"]
            cnt = await conn.fetchval("SELECT count(*) FROM usage_logs WHERE device_id = $1", dev_id)
            print(f"device {dev_id}: {cnt}")

            if cnt and cnt > 0:
                print("  Sample rows:")
                rows = await conn.fetch("SELECT id, app_id, app_name, app_package, start, end, duration FROM usage_logs WHERE device_id = $1 ORDER BY start DESC LIMIT 5", dev_id)
                for r in rows:
                    print("   ", dict(r))
            else:
                print("  (no usage_logs rows)")

        print("\n-- recent usage_events (5) --")
        ue = await conn.fetch("SELECT id, device_id, app_id, event_type, event_timestamp FROM usage_events ORDER BY event_timestamp DESC LIMIT 5")
        if ue:
            for r in ue:
                print(dict(r))
        else:
            print("(no usage_events rows)")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run())