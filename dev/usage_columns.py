import os, asyncio, asyncpg
async def main():
    conn=await asyncpg.connect(os.environ['DATABASE_URL'])
    rows=await conn.fetch(os.environ['SQL'])
    for r in rows:
        print(r['column_name'])
    await conn.close()
asyncio.run(main())
