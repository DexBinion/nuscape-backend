import os, asyncio, asyncpg

async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    rows = await conn.fetch("SELECT DISTINCT app_id FROM app_aliases ORDER BY app_id")
    for row in rows:
        print(row['app_id'])
    await conn.close()

asyncio.run(main())
