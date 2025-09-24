from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from backend.database import get_db
from backend.schemas import UsageSeries

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


@router.get("/summary")
async def usage_summary(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a snapshot with:
      - attention_minutes: global overlap-collapsed minutes
      - device_minutes: array of { device_id, minutes } (per-device, overlaps collapsed per device)
      - app_minutes: array of { app_package, minutes } (raw app totals)
    Query params:
      ?from=ISO&to=ISO
    """
    try:
        sql = text(
            """
WITH bounds AS (
  SELECT :d0::timestamptz AS d0,
         :d1::timestamptz AS d1
),
w AS (
  SELECT u.device_id, u.app_package, u."start", u."end"
  FROM usage_logs u, bounds b
  WHERE u."start" >= b.d0 AND u."end" <= b.d1
),

-- App totals (raw)
app_totals AS (
  SELECT app_package,
         SUM(EXTRACT(EPOCH FROM ("end" - "start"))) AS seconds
  FROM w GROUP BY app_package
),

-- Device time (overlap-collapsed per device)
dev_ordered AS (
  SELECT device_id, "start", "end",
         LAG("end") OVER (PARTITION BY device_id ORDER BY "start") AS prev_end
  FROM w
),
dev_islands AS (
  SELECT device_id, "start", "end",
         SUM(CASE WHEN prev_end IS NULL OR "start" > prev_end THEN 1 ELSE 0 END)
           OVER (PARTITION BY device_id ORDER BY "start") AS island_id
  FROM dev_ordered
),
dev_merged AS (
  SELECT device_id, MIN("start") AS m_start, MAX("end") AS m_end
  FROM dev_islands GROUP BY device_id, island_id
),

-- Attention time (global overlap-collapsed)
glob_ordered AS (
  SELECT "start", "end",
         LAG("end") OVER (ORDER BY "start") AS prev_end
  FROM w
),
glob_islands AS (
  SELECT "start", "end",
         SUM(CASE WHEN prev_end IS NULL OR "start" > prev_end THEN 1 ELSE 0 END)
           OVER (ORDER BY "start") AS island_id
  FROM glob_ordered
),
glob_merged AS (
  SELECT MIN("start") AS m_start, MAX("end") AS m_end
  FROM glob_islands GROUP BY island_id
)

SELECT
  -- attention time (global)
  (SELECT ROUND(COALESCE(SUM(EXTRACT(EPOCH FROM (m_end - m_start))),0)/60.0, 1) FROM glob_merged) AS attention_minutes,

  -- device time (per device) as jsonb
  (SELECT COALESCE(jsonb_agg(jsonb_build_object('device_id', device_id, 'minutes',
    ROUND(SUM(EXTRACT(EPOCH FROM (m_end - m_start)))/60.0, 1)) ORDER BY SUM(EXTRACT(EPOCH FROM (m_end - m_start))) DESC), '[]'::jsonb)
   FROM dev_merged GROUP BY device_id) AS device_minutes_json,

  -- app totals as jsonb
  (SELECT COALESCE(jsonb_agg(jsonb_build_object('app_package', app_package, 'minutes', ROUND(seconds/60.0, 1)) ORDER BY seconds DESC), '[]'::jsonb)
   FROM app_totals) AS app_minutes_json
LIMIT 1;
            """
        )

        params = {"d0": from_date, "d1": to_date}
        result = await db.execute(sql, params)
        row = result.fetchone()
        if not row:
            return {
                "attention_minutes": 0.0,
                "device_minutes": [],
                "app_minutes": [],
            }

        attention_minutes = float(row[0]) if row[0] is not None else 0.0

        # device_minutes_json may be repeated per-device group; coerce to a single array
        device_json = row[1]
        app_json = row[2]

        # Ensure we return consistent shapes
        return {
            "attention_minutes": attention_minutes,
            "device_minutes": device_json or [],
            "app_minutes": app_json or [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute usage summary: {e}")