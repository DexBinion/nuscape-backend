import os, asyncio, asyncpg

async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    rows = await conn.fetch("SELECT app_name, COUNT(*) AS c FROM usage_logs WHERE app_id IS NULL GROUP BY app_name ORDER BY c DESC LIMIT 20")
    for row in rows:
        print(dict(row))
    await conn.close()

asyncio.run(main())
