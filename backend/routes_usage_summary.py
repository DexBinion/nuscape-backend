from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


def _parse_date(value: str):
    try:
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format '{value}'; use YYYY-MM-DD",
        ) from exc


@router.get("/summary")
async def usage_summary(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    account_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Return rollup-backed attention metrics for the requested date range."""

    start_date = _parse_date(from_date)
    end_date = _parse_date(to_date)
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="`to` must be on or after `from`")

    params = {
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    try:
        attention_stmt = text(
            """
            SELECT COALESCE(SUM(duration_seconds), 0) AS total_seconds
            FROM attention_sessions_daily
            WHERE account_id = :account_id
              AND session_date BETWEEN :start_date AND :end_date
            """
        )
        attention_seconds = (await db.execute(attention_stmt, params)).scalar_one()

        device_stmt = text(
            """
            SELECT device_id::text AS device_id,
                   SUM(duration_seconds) AS seconds
            FROM device_sessions_daily
            WHERE account_id = :account_id
              AND session_date BETWEEN :start_date AND :end_date
            GROUP BY device_id
            ORDER BY seconds DESC
            """
        )
        device_rows = await db.execute(device_stmt, params)
        device_minutes = [
            {
                "device_id": row.device_id,
                "minutes": round((row.seconds or 0) / 60.0, 1),
            }
            for row in device_rows
        ]

        app_stmt = text(
            """
            SELECT
                COALESCE(app_package, app_id, app_name, 'unknown') AS app_key,
                MAX(app_package) AS app_package,
                MAX(app_id) AS app_id,
                MAX(app_name) AS app_name,
                SUM(duration_seconds) AS seconds
            FROM device_sessions_daily
            WHERE account_id = :account_id
              AND session_date BETWEEN :start_date AND :end_date
            GROUP BY app_key
            ORDER BY seconds DESC
            """
        )
        app_rows = await db.execute(app_stmt, params)
        app_minutes = []
        for row in app_rows:
            label = row.app_package or row.app_id or row.app_name or row.app_key
            app_minutes.append(
                {
                    "app_package": label,
                    "minutes": round((row.seconds or 0) / 60.0, 1),
                }
            )

        return {
            "attention_minutes": round((attention_seconds or 0) / 60.0, 1),
            "device_minutes": device_minutes,
            "app_minutes": app_minutes,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to compute usage summary: {exc}") from exc
