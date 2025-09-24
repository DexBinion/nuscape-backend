import os, asyncio, asyncpg
async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    rows = await conn.fetch("SELECT app_id, display_name FROM apps WHERE display_name ILIKE '%musically%'")
    for row in rows:
        print(dict(row))
    await conn.close()
asyncio.run(main())
