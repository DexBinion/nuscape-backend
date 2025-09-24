import os
import sys
import traceback

def main():
    try:
        import psycopg2
    except Exception:
        print("ERROR: psycopg2 is not installed in the venv.", file=sys.stderr)
        print("Install with: .venv\\Scripts\\pip.exe install psycopg2-binary", file=sys.stderr)
        sys.exit(2)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(2)

    try:
        con = psycopg2.connect(url)
        cur = con.cursor()
        cur.execute("select table_name from information_schema.tables where table_schema='public' order by 1")
        rows = [r[0] for r in cur.fetchall()]
        print("tables:", rows)
        cur.close()
        con.close()
    except Exception:
        print("ERROR connecting/querying the database:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()