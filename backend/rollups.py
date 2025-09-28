from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SESSION_GAP_SECONDS = 120
EXCLUDED_LAUNCHER_PACKAGES = {
    "com.google.android.apps.nexuslauncher",
    "com.android.launcher",
    "com.android.launcher3",
    "com.samsung.android.launcher",
    "com.miui.home",
    "com.microsoft.launcher",
}


def _resolve_target_date(target_date: Optional[date]) -> date:
    if target_date is None:
        return (datetime.now(timezone.utc) - timedelta(days=1)).date()
    return target_date


def _day_bounds(target_date: date) -> Tuple[datetime, datetime]:
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def ensure_rollup_tables(db: AsyncSession) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS device_sessions_daily (
            id BIGSERIAL PRIMARY KEY,
            account_id TEXT NOT NULL,
            session_date DATE NOT NULL,
            device_id UUID NOT NULL,
            app_id TEXT,
            app_package TEXT,
            app_name TEXT,
            session_start TIMESTAMPTZ NOT NULL,
            session_end TIMESTAMPTZ NOT NULL,
            duration_seconds INTEGER NOT NULL,
            fragment_count INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_device_sessions_daily
        ON device_sessions_daily (account_id, session_date, device_id, app_package, session_start);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_device_sessions_daily_date
        ON device_sessions_daily (session_date, device_id);
        """,
        """
        CREATE TABLE IF NOT EXISTS attention_sessions_daily (
            id BIGSERIAL PRIMARY KEY,
            account_id TEXT NOT NULL,
            session_date DATE NOT NULL,
            session_start TIMESTAMPTZ NOT NULL,
            session_end TIMESTAMPTZ NOT NULL,
            duration_seconds INTEGER NOT NULL,
            device_count INTEGER NOT NULL,
            devices JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_attention_sessions_daily
        ON attention_sessions_daily (account_id, session_date, session_start);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_attention_sessions_daily_date
        ON attention_sessions_daily (session_date);
        """,
        """
        CREATE TABLE IF NOT EXISTS usage_daily_totals (
            id BIGSERIAL PRIMARY KEY,
            account_id TEXT NOT NULL,
            session_date DATE NOT NULL,
            total_attention_sec INTEGER NOT NULL,
            device_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb,
            top_apps JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (account_id, session_date)
        );
        """,
    ]
    for stmt in statements:
        await db.execute(text(stmt))


async def _build_device_sessions(
    db: AsyncSession,
    *,
    account_id: str,
    session_date: date,
    day_start: datetime,
    day_end: datetime,
    gap_seconds: int,
) -> int:
    params = {
        "account_id": account_id,
        "session_date": session_date,
        "day_start": day_start,
        "day_end": day_end,
        "gap_seconds": gap_seconds,
    }

    await db.execute(
        text(
            """
            DELETE FROM device_sessions_daily
            WHERE account_id = :account_id AND session_date = :session_date;
            """
        ),
        params,
    )

    insert_sql = text(
        """
        WITH bounds AS (
            SELECT
                CAST(:account_id AS text) AS account_id,
                CAST(:session_date AS date) AS session_date,
                CAST(:day_start AS timestamptz) AS day_start,
                CAST(:day_end AS timestamptz) AS day_end,
                CAST(:gap_seconds AS integer) AS gap_seconds
        ),
        base AS (
            SELECT
                b.account_id,
                b.session_date,
                ul.device_id,
                COALESCE(ul.app_package, ul.app_id, ul.app_name) AS app_key,
                ul.app_id,
                ul.app_package,
                ul.app_name,
                GREATEST(ul.start, b.day_start) AS start_ts,
                LEAST(ul."end", b.day_end) AS end_ts,
                b.gap_seconds
            FROM usage_logs ul
            JOIN bounds b ON TRUE
            WHERE ul."end" > b.day_start
              AND ul.start < b.day_end
              AND ul.duration > 0
        ),
        ordered AS (
            SELECT
                *,
                LAG(end_ts) OVER (PARTITION BY device_id, app_key ORDER BY start_ts) AS prev_end
            FROM base
        ),
        grouped AS (
            SELECT
                *,
                SUM(
                    CASE
                        WHEN prev_end IS NULL THEN 1
                        WHEN start_ts <= prev_end + (gap_seconds * INTERVAL '1 second') THEN 0
                        ELSE 1
                    END
                ) OVER (PARTITION BY device_id, app_key ORDER BY start_ts) AS grp
            FROM ordered
        ),
        merged AS (
            SELECT
                account_id,
                session_date,
                device_id,
                MAX(app_id) FILTER (WHERE app_id IS NOT NULL) AS app_id,
                MAX(app_package) FILTER (WHERE app_package IS NOT NULL) AS app_package,
                MAX(app_name) FILTER (WHERE app_name IS NOT NULL) AS app_name,
                MIN(start_ts) AS session_start,
                MAX(end_ts) AS session_end,
                COUNT(*) AS fragment_count
            FROM grouped
            GROUP BY account_id, session_date, device_id, app_key, grp
        )
        INSERT INTO device_sessions_daily (
            account_id,
            session_date,
            device_id,
            app_id,
            app_package,
            app_name,
            session_start,
            session_end,
            duration_seconds,
            fragment_count,
            created_at,
            updated_at
        )
        SELECT
            account_id,
            session_date,
            device_id,
            app_id,
            app_package,
            app_name,
            session_start,
            session_end,
            GREATEST(1, CAST(EXTRACT(EPOCH FROM (session_end - session_start)) AS INTEGER)),
            fragment_count,
            NOW(),
            NOW()
        FROM merged
        WHERE session_end > session_start;
        """
    )

    result = await db.execute(insert_sql, params)
    return result.rowcount or 0


async def _build_attention_sessions(
    db: AsyncSession,
    *,
    account_id: str,
    session_date: date,
    gap_seconds: int,
) -> int:
    params = {
        "account_id": account_id,
        "session_date": session_date,
        "gap_seconds": gap_seconds,
    }

    await db.execute(
        text(
            """
            DELETE FROM attention_sessions_daily
            WHERE account_id = :account_id AND session_date = :session_date;
            """
        ),
        params,
    )

    insert_sql = text(
        """
        WITH base AS (
            SELECT
                ds.account_id,
                ds.session_date,
                ds.session_start,
                ds.session_end,
                ds.device_id,
                CAST(:gap_seconds AS integer) AS gap_seconds
            FROM device_sessions_daily ds
            WHERE ds.account_id = :account_id
              AND ds.session_date = :session_date
        ),
        ordered AS (
            SELECT
                *,
                LAG(session_end) OVER (ORDER BY session_start) AS prev_end
            FROM base
        ),
        grouped AS (
            SELECT
                *,
                SUM(
                    CASE
                        WHEN prev_end IS NULL THEN 1
                        WHEN session_start <= prev_end + (gap_seconds * INTERVAL '1 second') THEN 0
                        ELSE 1
                    END
                ) OVER (ORDER BY session_start) AS grp
            FROM ordered
        ),
        merged AS (
            SELECT
                account_id,
                session_date,
                MIN(session_start) AS session_start,
                MAX(session_end) AS session_end,
                COUNT(DISTINCT device_id) AS device_count,
                ARRAY_AGG(DISTINCT device_id::text) AS device_ids
            FROM grouped
            GROUP BY account_id, session_date, grp
        )
        INSERT INTO attention_sessions_daily (
            account_id,
            session_date,
            session_start,
            session_end,
            duration_seconds,
            device_count,
            devices,
            created_at,
            updated_at
        )
        SELECT
            account_id,
            session_date,
            session_start,
            session_end,
            GREATEST(1, CAST(EXTRACT(EPOCH FROM (session_end - session_start)) AS INTEGER)),
            GREATEST(device_count, 1),
            to_jsonb(coalesce(device_ids, ARRAY[]::text[])),
            NOW(),
            NOW()
        FROM merged
        WHERE session_end > session_start;
        """
    )

    result = await db.execute(insert_sql, params)
    return result.rowcount or 0


async def _write_daily_totals(
    db: AsyncSession,
    *,
    account_id: str,
    session_date: date,
) -> Dict[str, int]:
    params = {"account_id": account_id, "session_date": session_date}

    total_result = await db.execute(
        text(
            """
            SELECT COALESCE(SUM(duration_seconds), 0) AS total_seconds
            FROM attention_sessions_daily
            WHERE account_id = :account_id AND session_date = :session_date;
            """
        ),
        params,
    )
    total_attention = int(total_result.scalar_one() or 0)

    device_rows = await db.execute(
        text(
            """
            SELECT device_id::text AS device_id,
                   SUM(duration_seconds)::int AS seconds
            FROM device_sessions_daily
            WHERE account_id = :account_id AND session_date = :session_date
            GROUP BY device_id
            ORDER BY seconds DESC;
            """
        ),
        params,
    )
    device_breakdown: List[Dict[str, int]] = [
        {"device_id": row.device_id, "seconds": int(row.seconds or 0)}
        for row in device_rows
    ]

    app_rows = await db.execute(
        text(
            """
            SELECT
                COALESCE(app_package, app_id, app_name) AS app_key,
                MAX(app_package) FILTER (WHERE app_package IS NOT NULL) AS app_package,
                MAX(app_id) FILTER (WHERE app_id IS NOT NULL) AS app_id,
                MAX(app_name) FILTER (WHERE app_name IS NOT NULL) AS app_name,
                SUM(duration_seconds)::int AS seconds
            FROM device_sessions_daily
            WHERE account_id = :account_id AND session_date = :session_date
            GROUP BY app_key
            ORDER BY seconds DESC;
            """
        ),
        params,
    )

    excluded_packages = {pkg.lower() for pkg in EXCLUDED_LAUNCHER_PACKAGES}
    top_apps: List[Dict[str, object]] = []
    for row in app_rows:
        package = (row.app_package or "").lower()
        name = (row.app_name or "").lower()
        if package and package in excluded_packages:
            continue
        if not package and "launcher" in name:
            continue
        top_apps.append(
            {
                "app_package": row.app_package,
                "app_id": row.app_id,
                "app_name": row.app_name,
                "seconds": int(row.seconds or 0),
            }
        )

    insert_params = {
        "account_id": account_id,
        "session_date": session_date,
        "total_attention_sec": total_attention,
        "device_breakdown": json.dumps(device_breakdown),
        "top_apps": json.dumps(top_apps),
    }

    await db.execute(
        text(
            """
            INSERT INTO usage_daily_totals (
                account_id,
                session_date,
                total_attention_sec,
                device_breakdown,
                top_apps,
                created_at,
                updated_at
            )
            VALUES (
                :account_id,
                :session_date,
                :total_attention_sec,
                CAST(:device_breakdown AS jsonb),
                CAST(:top_apps AS jsonb),
                NOW(),
                NOW()
            )
            ON CONFLICT (account_id, session_date) DO UPDATE
            SET total_attention_sec = EXCLUDED.total_attention_sec,
                device_breakdown = EXCLUDED.device_breakdown,
                top_apps = EXCLUDED.top_apps,
                updated_at = NOW();
            """
        ),
        insert_params,
    )

    return {
        "total_attention_sec": total_attention,
        "device_count": len(device_breakdown),
        "top_apps_count": len(top_apps),
    }


async def run_daily_rollups(
    db: AsyncSession,
    *,
    target_date: Optional[date] = None,
    account_id: str = "default",
    gap_seconds: int = SESSION_GAP_SECONDS,
) -> Dict[str, int]:
    target = _resolve_target_date(target_date)
    day_start, day_end = _day_bounds(target)

    await ensure_rollup_tables(db)
    if db.in_transaction():
        await db.commit()

    async with db.begin():
        device_count = await _build_device_sessions(
            db,
            account_id=account_id,
            session_date=target,
            day_start=day_start,
            day_end=day_end,
            gap_seconds=gap_seconds,
        )
        attention_count = await _build_attention_sessions(
            db,
            account_id=account_id,
            session_date=target,
            gap_seconds=gap_seconds,
        )
        totals = await _write_daily_totals(
            db,
            account_id=account_id,
            session_date=target,
        )

    return {
        "session_date": int(target.strftime("%Y%m%d")),
        "device_sessions": device_count,
        "attention_sessions": attention_count,
        **totals,
    }


__all__ = [
    "ensure_rollup_tables",
    "run_daily_rollups",
    "SESSION_GAP_SECONDS",
]
