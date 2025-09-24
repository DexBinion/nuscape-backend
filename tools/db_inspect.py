#!/usr/bin/env python3
"""
Simple DB inspector for NuScape dev environment.

Reads DATABASE_URL from repo .env, normalizes it for asyncpg, connects,
and prints counts / a few rows from devices and rollup tables.
"""
import asyncio
import os
from urllib.parse import urlparse, urlunparse, parse_qs
import asyncpg

# Load .env (very small, explicit)
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): 
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k not in os.environ:
                    os.environ[k] = v

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL not found in environment or .env")

# Normalize DSN for asyncpg: remove +asyncpg and strip query (handle sslmode)
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

    async def q_one(q, *args):
        try:
            return await conn.fetch(q, *args)
        except Exception as e:
            print("Query failed:", q, "->", e)
            return None

    print("\n-- devices (latest 10) --")
    rows = await q_one("SELECT id, platform, name, device_key, last_seen_at, created_at FROM devices ORDER BY created_at DESC LIMIT 10")
    if rows is not None:
        for r in rows:
            print(dict(r))

    print("\n-- counts --")
    for t in ("usage_1m","usage_5m","usage_60m"):
        res = await q_one(f"SELECT count(*) as c FROM {t}")
        if res:
            print(f"{t}: {res[0]['c']}")
        else:
            print(f"{t}: (query failed or table missing)")

    print("\n-- recent usage_1m rows (10) --")
    rows = await q_one("SELECT account_id, device_id, bucket_start, kind, key, secs_sum, events_count, last_ts FROM usage_1m ORDER BY bucket_start DESC LIMIT 10")
    if rows is not None:
        for r in rows:
            print(dict(r))

    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())