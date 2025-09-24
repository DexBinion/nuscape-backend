import os
import sys
import traceback

def main():
    try:
        import psycopg2
    except Exception:
        print("ERROR: psycopg2 not installed. Install with: .venv\\Scripts\\pip.exe install psycopg2-binary", file=sys.stderr)
        sys.exit(2)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL env var not set.", file=sys.stderr)
        sys.exit(2)

    print("Connecting to DB...")
    try:
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        print("Deleting duplicate usage_logs rows (keeping lowest id) ...")
        cur.execute('''
WITH duplicates AS (
  SELECT id, ROW_NUMBER() OVER (PARTITION BY device_id, app_package, start, "end" ORDER BY id) AS rn
  FROM usage_logs
)
DELETE FROM usage_logs WHERE id IN (SELECT id FROM duplicates WHERE rn > 1);
''')
        deleted = cur.rowcount
        conn.commit()
        print(f"DELETE executed; rowcount reported: {deleted}")
        cur.execute('SELECT COUNT(*) FROM usage_logs')
        total = cur.fetchone()[0]
        print(f"Remaining usage_logs rows: {total}")
        cur.close()
        conn.close()
    except Exception:
        print("ERROR during DB operation:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()