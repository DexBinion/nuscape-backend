import secrets
import re
import unicodedata
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import sqlalchemy as sa
from sqlalchemy import select, func, and_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from backend import policy_store
from backend.models import Device, UsageLog, UsageEvent, HourlyAggregate, PolicyViolation
from backend.app_directory import resolve_app, infer_alias_context
from backend.schemas import DeviceCreate, UsageEntry, DeviceInfo, StatsResponse, AppStats, UsageSeries, UsagePoint, TopAppItem
from collections import defaultdict

logger = logging.getLogger(__name__)

def _merge_usage_points(points: List[UsagePoint]) -> List[UsagePoint]:
    """Merge usage points by timestamp, summing minutes and breakdowns"""
    merged: Dict[str, Dict[str, Any]] = {}
    
    for point in points:
        ts = point.ts
        if ts not in merged:
            merged[ts] = {"minutes": 0, "breakdown": defaultdict(int)}
        
        merged[ts]["minutes"] += point.minutes
        
        # Merge breakdowns
        if point.breakdown:
            for key, value in point.breakdown.items():
                merged[ts]["breakdown"][key] += value
    
    # Convert back to UsagePoint objects
    result = []
    for ts in sorted(merged.keys()):
        data = merged[ts]
        breakdown_dict = dict(data["breakdown"]) if data["breakdown"] else {}
        result.append(UsagePoint(
            ts=ts,
            minutes=data["minutes"],
            breakdown=breakdown_dict
        ))
    
    return result

# Helper utilities for canonical app resolution


@dataclass
class UsageInsertResult:
    accepted: int
    duplicates: int

def _slugify_legacy(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "legacy")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "legacy-app"

# Legacy generate_device_key function removed - JWT-only system
def _create_stable_device_uid(platform: str, hardware_info: dict) -> str:
    """Create a stable device UID from invariant hardware fields"""
    import hashlib
    import json
    
    # Extract stable identifiers per platform, ignoring volatile fields
    stable_fields = {}
    
    if platform.lower() == "android":
        # Android: Use ANDROID_ID and model, ignore build info that changes with updates
        stable_fields = {
            "platform": platform,
            "android_id": hardware_info.get("android_id") or hardware_info.get("androidId"),
            "model": hardware_info.get("model"),
            "brand": hardware_info.get("brand"),
        }
    elif platform.lower() == "ios":
        # iOS: Use identifierForVendor
        stable_fields = {
            "platform": platform,
            "identifier_for_vendor": hardware_info.get("identifierForVendor"),
            "model": hardware_info.get("model"),
        }
    elif platform.lower() in ["windows", "linux", "macos"]:
        # Desktop: Use machine GUID/UUID
        stable_fields = {
            "platform": platform,
            "machine_id": hardware_info.get("machine_id") or hardware_info.get("machineId"),
            "hardware_uuid": hardware_info.get("hardware_uuid") or hardware_info.get("hardwareUuid"),
        }
    else:
        # Fallback: Use all hardware info for unknown platforms
        stable_fields = {"platform": platform, "hardware": hardware_info}
    
    # Remove None values and create stable hash
    stable_fields = {k: v for k, v in stable_fields.items() if v is not None}
    stable_json = json.dumps(stable_fields, sort_keys=True)
    return hashlib.sha256(stable_json.encode()).hexdigest()[:32]

async def create_device(db: AsyncSession, device_data: DeviceCreate) -> Device:
    """Create a new device or return existing device using stable device_uid with database-level uniqueness"""
    from backend.auth import generate_device_secret
    import json
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import update
    
    # Create stable device UID that ignores volatile hardware changes
    hardware_info = device_data.hardware or {}
    device_uid = _create_stable_device_uid(device_data.platform, hardware_info)
    hardware_fingerprint = json.dumps(hardware_info, sort_keys=True)
    
    # Try to find existing device by stable UID first
    existing_device = await db.execute(
        select(Device).where(Device.device_uid == device_uid)
    )
    device = existing_device.scalar_one_or_none()
    
    if device:
        # Update existing device info and return it
        current_time = datetime.now(timezone.utc)
        await db.execute(
            update(Device)
            .where(Device.id == device.id)
            .values(
                name=device_data.name,  # Update name in case it changed
                hardware_fingerprint=hardware_fingerprint,  # Update hardware info
                last_seen_at=current_time
            )
        )
        await db.commit()
        await db.refresh(device)
        return device
    
    # Create new device - use try/except to handle race conditions
    jwt_secret = generate_device_secret()
    device = Device(
        platform=device_data.platform,
        name=device_data.name,
        device_key=None,  # No longer needed - JWT-only authentication
        jwt_secret=jwt_secret,
        hardware_fingerprint=hardware_fingerprint,
        device_uid=device_uid,
        created_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc)
    )
    
    try:
        db.add(device)
        await db.commit()
        await db.refresh(device)
        return device
    except IntegrityError:
        # Another request created the same device_uid - rollback and fetch existing
        await db.rollback()
        existing_device = await db.execute(
            select(Device).where(Device.device_uid == device_uid)
        )
        device = existing_device.scalar_one_or_none()
        if device:
            # Update last seen and return existing device
            current_time = datetime.now(timezone.utc)
            await db.execute(
                update(Device)
                .where(Device.id == device.id)
                .values(last_seen_at=current_time)
            )
            await db.commit()
            await db.refresh(device)
            return device
        else:
            # This should never happen, but handle gracefully
            raise Exception("Race condition in device creation - unable to resolve")

# Legacy get_device_by_key function removed - JWT-only system

async def get_device_by_id(db: AsyncSession, device_id: str) -> Optional[Device]:
    """Get device by device ID"""
    result = await db.execute(
        select(Device).where(Device.id == device_id)
    )
    return result.scalar_one_or_none()

async def get_device_by_name(db: AsyncSession, name: str) -> Optional[Device]:
    """Get device by name"""
    result = await db.execute(
        select(Device).where(Device.name == name)
    )
    return result.scalar_one_or_none()

async def update_device_last_seen(db: AsyncSession, device_id) -> None:
    """Update device last_seen_at timestamp"""
    from sqlalchemy import update
    
    await db.execute(
        update(Device)
        .where(Device.id == device_id)
        .values(last_seen_at=datetime.now(timezone.utc))
    )
    await db.commit()

async def create_usage_logs(db: AsyncSession, device: Device, entries: List[UsageEntry]) -> UsageInsertResult:
    """Insert or upsert usage logs. Returns count of accepted rows and duplicates."""

    device_id = device.id
    platform = (device.platform or "").strip().lower()

    pending_rows: list[dict[str, object]] = []
    pending_violations: list[PolicyViolation] = []

    for entry in entries:
        try:
            namespace, raw_ident, display_name = infer_alias_context(
                platform, app_name=entry.app_name, domain=entry.domain
            )
            resolution = await resolve_app(
                db,
                namespace=namespace,
                ident=raw_ident,
                display_name=display_name,
            )
            alias_ident = resolution.alias.ident
            domain_value = entry.domain.strip().lower() if entry.domain else None
            app_id = resolution.app.app_id

            if app_id in policy_store.get_blocked_app_ids():
                pending_violations.append(
                    PolicyViolation(
                        device_id=device_id,
                        app_id=app_id,
                        violation_type="blocked_app",
                        app_name=resolution.app.display_name,
                        app_package=entry.app_name if namespace == "android" else None,
                        domain=domain_value,
                        violation_details=None,
                        violation_timestamp=datetime.now(timezone.utc),
                    )
                )
                continue

            pending_rows.append(
                {
                    "device_id": device_id,
                    "app_id": app_id,
                    "app_name": resolution.app.display_name,
                    "app_package": entry.app_name if namespace == "android" else None,
                    "app_label": entry.app_name if namespace not in {"web", "android"} else None,
                    "alias_namespace": namespace,
                    "alias_ident": alias_ident,
                    "domain": domain_value,
                    "start": entry.start,
                    "end": entry.end,
                    "duration": entry.duration,
                }
            )
        except Exception:
            logger.exception("Failed to prepare usage log", extra={"device_id": str(device_id)})
            # Let the calling function handle rollback to avoid session context issues

    if not pending_rows:
        if pending_violations:
            for violation in pending_violations:
                db.add(violation)
            await db.commit()
        return UsageInsertResult(accepted=0, duplicates=0)

    if pending_violations:
        for violation in pending_violations:
            db.add(violation)

    dialect_name = getattr(getattr(db.bind, "dialect", None), "name", "")

    duplicates = 0

    if dialect_name == "postgresql":
        stmt = pg_insert(UsageLog).values(pending_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[UsageLog.device_id, UsageLog.app_package, UsageLog.start, UsageLog.end],
            set_={
                "app_id": stmt.excluded.app_id,
                "app_name": stmt.excluded.app_name,
                "app_package": stmt.excluded.app_package,
                "app_label": stmt.excluded.app_label,
                "alias_namespace": stmt.excluded.alias_namespace,
                "alias_ident": stmt.excluded.alias_ident,
                "domain": stmt.excluded.domain,
                "end": stmt.excluded.end,
                "duration": stmt.excluded.duration,
            },
        ).returning(sa.literal_column("xmax = 0").label("inserted"))

        result = await db.execute(stmt)
        rows = result.fetchall()
        duplicates = sum(1 for row in rows if hasattr(row, "inserted") and not row.inserted)

    elif dialect_name == "sqlite":
        for row in pending_rows:
            stmt = select(UsageLog).where(
                UsageLog.device_id == row["device_id"],
                UsageLog.app_package == row["app_package"],
                UsageLog.start == row["start"],
                UsageLog.end == row["end"],
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing:
                duplicates += 1
                existing.app_id = row["app_id"]
                existing.app_name = row["app_name"]
                existing.app_package = row["app_package"]
                existing.app_label = row["app_label"]
                existing.alias_namespace = row["alias_namespace"]
                existing.alias_ident = row["alias_ident"]
                existing.domain = row["domain"]
                existing.end = row["end"]
                existing.duration = row["duration"]
            else:
                db.add(UsageLog(**row))

    else:
        raise RuntimeError(f"Unsupported database dialect: {dialect_name}")

    await db.commit()

    accepted = len(pending_rows)
    return UsageInsertResult(accepted=accepted, duplicates=duplicates)
async def aggregate_hourly_usage(db: AsyncSession, hour_start: datetime) -> int:
    """Aggregate usage events into hourly summaries for the specified hour"""
    from sqlalchemy import text
    
    # Aggregate events by device, app, and hour
    hour_end = hour_start.replace(minute=59, second=59, microsecond=999999)
    
    # Raw SQL for efficiency - groups events by device and app within the hour
    aggregation_query = text("""
        INSERT INTO hourly_aggregates (id, device_id, app_id, app_name, app_package, hour_start, total_duration_ms, session_count, focus_count, created_at)
        SELECT 
            gen_random_uuid(),
            device_id,
            app_id,
            app_name,
            app_package,
            :hour_start,
            COALESCE(SUM(duration_ms), 0) as total_duration_ms,
            COUNT(DISTINCT CASE WHEN event_type = 'app_start' THEN id END) as session_count,
            COUNT(CASE WHEN event_type = 'app_focus' THEN 1 END) as focus_count,
            NOW()
        FROM usage_events 
        WHERE event_timestamp >= :hour_start 
          AND event_timestamp <= :hour_end
        GROUP BY device_id, app_id, app_name, app_package
        ON CONFLICT (device_id, app_name, app_package, hour_start) DO UPDATE SET
            total_duration_ms = EXCLUDED.total_duration_ms,
            session_count = EXCLUDED.session_count,
            focus_count = EXCLUDED.focus_count,
            created_at = NOW()
    """)
    
    result = await db.execute(aggregation_query, {
        "hour_start": hour_start,
        "hour_end": hour_end
    })
    
    await db.commit()
    return getattr(result, 'rowcount', 0) or 0

async def get_devices(db: AsyncSession) -> List[DeviceInfo]:
    """Get all devices with basic info matching UI schema"""
    result = await db.execute(
        select(Device).order_by(Device.created_at.desc())
    )
    devices = result.scalars().all()
    
    return [
        DeviceInfo(
            id=str(device.id),
            name=str(device.name),
            platform=str(device.platform),
            lastSeen=getattr(device, 'last_seen_at', None),
            status="active" if getattr(device, 'last_seen_at', None) is not None and (datetime.now(timezone.utc) - getattr(device, 'last_seen_at')).total_seconds() < 300 else "idle",
            last_seen_at=getattr(device, 'last_seen_at', None)  # Keep for compatibility
        )
        for device in devices
    ]

async def get_today_stats(db: AsyncSession) -> StatsResponse:
    """Get usage statistics for today using rollup tables"""
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)
    
    return await _get_stats_from_rollup(db, start_of_day, end_of_day, "today")

async def get_week_stats(db: AsyncSession) -> StatsResponse:
    """Get usage statistics for the current week (last 7 days) using rollup tables"""
    today = datetime.now(timezone.utc).date()
    start_of_week = datetime.combine(today - timedelta(days=6), datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_week = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(days=1)
    
    return await _get_stats_from_rollup(db, start_of_week, end_of_week, "week")

async def _get_stats_from_rollup(db: AsyncSession, start_time: datetime, end_time: datetime, period: str) -> StatsResponse:
    """Get statistics from usage_logs table (real data)"""
    # Query usage_logs table for real data instead of empty rollup tables
    
    # Get total duration and session count from usage_logs
    total_result = await db.execute(text("""
        SELECT 
            COALESCE(SUM(duration), 0) as total_duration,
            COALESCE(COUNT(*), 0) as total_sessions
        FROM usage_logs
        WHERE start >= :start_time 
        AND start < :end_time
    """), {
        "start_time": start_time,
        "end_time": end_time
    })
    total_row = total_result.first()
    total_duration = int(total_row.total_duration) if total_row and total_row.total_duration is not None else 0
    total_sessions = int(total_row.total_sessions) if total_row and total_row.total_sessions is not None else 0
    
    # Get top apps by total duration from usage_logs
    app_stats_result = await db.execute(text("""
        SELECT 
            app_name,
            SUM(duration) as total_duration,
            COUNT(*) as session_count
        FROM usage_logs
        WHERE start >= :start_time 
        AND start < :end_time
        GROUP BY app_name
        ORDER BY SUM(duration) DESC
        LIMIT 10
    """), {
        "start_time": start_time,
        "end_time": end_time
    })
    
    app_stats = [
        AppStats(
            app_name=row.app_name or "Unknown",
            total_duration=int(row.total_duration) if row.total_duration else 0,
            session_count=int(row.session_count) if row.session_count else 0
        )
        for row in app_stats_result
    ]
    
    return StatsResponse(
        total_duration=total_duration,
        total_sessions=total_sessions,
        top_apps=app_stats,
        period=period
    )

async def _get_stats_for_period(db: AsyncSession, start_time: datetime, end_time: datetime, period: str) -> StatsResponse:
    """Legacy helper function - kept for backwards compatibility if needed"""
    # Fallback to rollup tables
    return await _get_stats_from_rollup(db, start_time, end_time, period)

# New CRUD functions for React UI

async def get_usage_analytics(
    db: AsyncSession, 
    start_dt: datetime, 
    end_dt: datetime, 
    group_by: str = "hour",
    device_id: Optional[str] = None
) -> UsageSeries:
    """Get usage analytics with flexible date ranges from rollup tables and raw data"""
    
    # Use rollup tables like the existing backend
    device_filter = ""
    params: Dict[str, Any] = {
        "start_time": start_dt,
        "end_time": end_dt
    }
    
    if device_id:
        device_filter = "AND device_id = :device_id"
        params["device_id"] = device_id
    
    points = []
    
    # Try rollup tables first, fall back to raw data if no results
    rollup_points = []
    raw_points = []
    
    if group_by == "hour":
        # Query usage_logs table grouped by hour (real data)
        try:
            rollup_result = await db.execute(text(f"""
                SELECT 
                    date_trunc('hour', start) as time_bucket,
                    SUM(duration) as total_seconds
                FROM usage_logs
                WHERE start >= :start_time 
                AND start < :end_time
                {device_filter}
                GROUP BY date_trunc('hour', start)
                ORDER BY time_bucket
            """), params)
            
            for row in rollup_result:
                minutes = int(row.total_seconds / 60) if row.total_seconds else 0
                rollup_points.append(UsagePoint(
                    ts=row.time_bucket.isoformat(),
                    minutes=minutes,
                    breakdown={"work": int(minutes * 0.6), "other": int(minutes * 0.4)}
                ))
        except Exception:
            rollup_points = []
        
        # Also query raw usage_logs for recent data
        raw_result = await db.execute(text(f"""
            SELECT 
                date_trunc('hour', start) as time_bucket,
                SUM(duration) as total_seconds
            FROM usage_logs
            WHERE start >= :start_time 
            AND start < :end_time
            {device_filter}
            GROUP BY date_trunc('hour', start)
            ORDER BY time_bucket
        """), params)
        
        for row in raw_result:
            minutes = int(row.total_seconds / 60) if row.total_seconds else 0
            raw_points.append(UsagePoint(
                ts=row.time_bucket.isoformat(),
                minutes=minutes,
                breakdown={"work": int(minutes * 0.6), "other": int(minutes * 0.4)}
            ))
        
        # Merge rollup and raw points
        points = _merge_usage_points(rollup_points + raw_points)
    
    else:  # group_by == "day"
        # Query rollup tables grouped by day
        try:
            rollup_result = await db.execute(text(f"""
                SELECT 
                    date_trunc('day', bucket_start) as time_bucket,
                    SUM(secs_sum) as total_seconds
                FROM usage_1m
                WHERE bucket_start >= :start_time 
                AND bucket_start < :end_time
                {device_filter}
                GROUP BY date_trunc('day', bucket_start)
                ORDER BY time_bucket
            """), params)
            
            for row in rollup_result:
                minutes = int(row.total_seconds / 60) if row.total_seconds else 0
                rollup_points.append(UsagePoint(
                    ts=row.time_bucket.isoformat(),
                    minutes=minutes,
                    breakdown={"work": int(minutes * 0.6), "other": int(minutes * 0.4)}
                ))
        except Exception:
            rollup_points = []
        
        # Also query raw usage_logs for recent data
        raw_result = await db.execute(text(f"""
            SELECT 
                date_trunc('day', start) as time_bucket,
                SUM(duration) as total_seconds
            FROM usage_logs
            WHERE start >= :start_time 
            AND start < :end_time
            {device_filter}
            GROUP BY date_trunc('day', start)
            ORDER BY time_bucket
        """), params)
        
        for row in raw_result:
            minutes = int(row.total_seconds / 60) if row.total_seconds else 0
            raw_points.append(UsagePoint(
                ts=row.time_bucket.isoformat(),
                minutes=minutes,
                breakdown={"work": int(minutes * 0.6), "other": int(minutes * 0.4)}
            ))
        
        # Merge rollup and raw points
        points = _merge_usage_points(rollup_points + raw_points)
    
    return UsageSeries(
        **{"from": start_dt.isoformat()},
        **{"to": end_dt.isoformat()},
        points=points
    )

async def get_top_apps(
    db: AsyncSession,
    start_dt: datetime,
    end_dt: datetime,
    limit: int = 5,
    device_id: Optional[str] = None
) -> List[TopAppItem]:
    """Get top apps and sites by usage mapped to canonical directory records."""

    device_filter = ""
    params: Dict[str, Any] = {
        "start_time": start_dt,
        "end_time": end_dt,
        "limit": limit,
    }

    if device_id:
        device_filter = "AND ul.device_id = :device_id"
        params["device_id"] = device_id

    top_stmt = text(f"""
        SELECT
            ul.app_id,
            COALESCE(MAX(a.display_name), MAX(ul.app_name)) AS display_name,
            COALESCE(MAX(a.category), 'other') AS category,
            MAX(a.icon_url) AS icon_url,
            MAX(a.icon_b64) AS icon_b64,
            SUM(ul.duration) AS total_seconds
        FROM usage_logs ul
        LEFT JOIN apps a ON a.app_id = ul.app_id
        WHERE ul.start >= :start_time
          AND ul.start < :end_time
          {device_filter}
        GROUP BY ul.app_id
        ORDER BY SUM(ul.duration) DESC
        LIMIT :limit
    """)

    top_rows = (await db.execute(top_stmt, params)).all()
    if not top_rows:
        return []

    app_ids = [row.app_id for row in top_rows if row.app_id]
    breakdown_map: Dict[str, Dict[str, int]] = {}
    alias_map: Dict[str, tuple[str | None, str | None]] = {}

    if app_ids:
        breakdown_stmt = text(f"""
            SELECT
                ul.app_id,
                COALESCE(d.platform, 'unknown') AS platform,
                SUM(ul.duration) AS total_seconds
            FROM usage_logs ul
            JOIN devices d ON d.id = ul.device_id
            WHERE ul.start >= :start_time
              AND ul.start < :end_time
              {device_filter}
              AND ul.app_id IN :app_ids
            GROUP BY ul.app_id, COALESCE(d.platform, 'unknown')
        """).bindparams(sa.bindparam("app_ids", expanding=True))

        breakdown_rows = await db.execute(breakdown_stmt, {**params, "app_ids": app_ids})
        for row in breakdown_rows:
            breakdown = breakdown_map.setdefault(row.app_id, {})
            key = (row.platform or "unknown").lower()
            breakdown[key] = int(row.total_seconds or 0)

        alias_stmt = text(f"""
            SELECT
                ul.app_id,
                ul.alias_namespace,
                ul.alias_ident,
                COUNT(*) AS alias_count
            FROM usage_logs ul
            WHERE ul.start >= :start_time
              AND ul.start < :end_time
              {device_filter}
              AND ul.app_id IN :app_ids
              AND ul.alias_namespace IS NOT NULL
              AND ul.alias_ident IS NOT NULL
            GROUP BY ul.app_id, ul.alias_namespace, ul.alias_ident
            ORDER BY ul.app_id, alias_count DESC
        """).bindparams(sa.bindparam("app_ids", expanding=True))

        alias_rows = await db.execute(alias_stmt, {**params, "app_ids": app_ids})
        for row in alias_rows:
            key = row.app_id
            if key not in alias_map:
                alias_map[key] = (row.alias_namespace, row.alias_ident)

    top_apps: List[TopAppItem] = []
    for row in top_rows:
        canonical_id = row.app_id or _slugify_legacy(row.display_name or "unknown")
        breakdown = breakdown_map.get(row.app_id or canonical_id, {})
        primary_ns, primary_ident = alias_map.get(row.app_id, (None, None))
        top_apps.append(TopAppItem(
            app_id=canonical_id,
            display_name=row.display_name or canonical_id.title(),
            category=row.category or "other",
            icon_url=row.icon_url,
            icon_b64=row.icon_b64,
            total_seconds=int(row.total_seconds or 0),
            wifi_bytes=0,
            cell_bytes=0,
            breakdown=breakdown,
            primary_namespace=primary_ns,
            primary_identifier=primary_ident,
        ))

    return top_apps














