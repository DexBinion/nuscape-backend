import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv
import sqlalchemy

# Ensure repository-root .env is loaded before any settings or DB modules import it
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Set up logger
logger = logging.getLogger(__name__)
from fastapi import FastAPI, Depends, HTTPException, status, Request, Header, Query, APIRouter
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.openapi.utils import get_openapi
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, engine, AsyncSessionLocal
from backend import models, schemas, crud, auth, policy_store
from backend.app_directory import resolve_app, infer_alias_context
from backend.settings import settings
from backend.routes_usage_desktop import router as desktop_usage_router
from backend.routes_apps_alias import router as apps_alias_router
from backend.routes_usage_summary import router as usage_summary_router
from backend.routes_usage_debug import router as usage_debug_router
from backend.metrics import metrics
from backend.redis_client import redis_client
from backend.app_seeds import load_app_seeds
from backend.rollups import run_daily_rollups, SESSION_GAP_SECONDS
from pydantic import ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Environment variables - hardcode for debugging
API_BASE_PATH = "/api/v1"  # Force correct API base path
logging.error(f"🔍 DEBUG: API_BASE_PATH set to: '{API_BASE_PATH}'")

CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)
MAX_SESSION_DURATION = timedelta(hours=8)
MIN_FOREGROUND_DURATION_MS = 5000

ROLLUP_CRON_KEY = os.environ.get("ROLLUP_CRON_KEY") or settings.jwt_secret_key


def _add_batch_error(errors: list[schemas.BatchItemError], index: int, message: str, code: str) -> None:
    errors.append(schemas.BatchItemError(index=index, error=message, code=code))


def _extract_raw_usage_items(body: dict) -> list:
    raw_items = (
        body.get("items")
        or body.get("entries")
        or body.get("sessions")
        or []
    )
    if not isinstance(raw_items, list):
        raise ValueError("Payload must include an array of items")
    return raw_items


def _collect_usage_entries(
    raw_items: list, *, now: datetime
) -> tuple[list[schemas.UsageEntry], list[schemas.BatchItemError]]:
    """Normalize incoming usage payload items and capture validation errors."""

    entries: list[schemas.UsageEntry] = []
    errors: list[schemas.BatchItemError] = []

    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            _add_batch_error(errors, idx, "Item must be a JSON object", "invalid_type")
            continue

        if "package" in item:
            package = item.get("package")
            total_ms = item.get("totalMs")
            start_raw = item.get("windowStart")
            end_raw = item.get("windowEnd")

            if not package:
                _add_batch_error(errors, idx, "Missing package", "missing_field")
                continue
            if total_ms is None:
                _add_batch_error(errors, idx, "Missing totalMs", "missing_field")
                continue
            if not isinstance(total_ms, (int, float)):
                _add_batch_error(errors, idx, "totalMs must be numeric", "invalid_duration")
                continue
            if total_ms <= 0:
                _add_batch_error(errors, idx, "totalMs must be > 0", "non_positive_duration")
                continue

            fg_flag = bool(item.get("fg", True))
            screen_on_flag = bool(item.get("screen_on", True))
            if not fg_flag or not screen_on_flag:
                _add_batch_error(errors, idx, "Session ignored: app not in foreground with screen on", "background_event")
                continue
            if total_ms < MIN_FOREGROUND_DURATION_MS:
                _add_batch_error(errors, idx, f"Session ignored: duration {total_ms}ms below threshold", "duration_below_threshold")
                continue

            if not start_raw or not end_raw:
                _add_batch_error(errors, idx, "windowStart/windowEnd required", "missing_field")
                continue
            if not str(start_raw).endswith("Z") or not str(end_raw).endswith("Z"):
                _add_batch_error(errors, idx, "Timestamps must be UTC with Z suffix", "timezone")
                continue

            try:
                start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
            except Exception as exc:
                _add_batch_error(errors, idx, f"Invalid ISO timestamp: {exc}", "invalid_iso")
                continue

            if end_dt <= start_dt:
                _add_batch_error(errors, idx, "windowEnd must be after windowStart", "end_not_after_start")
                continue

            if end_dt - start_dt > MAX_SESSION_DURATION:
                _add_batch_error(errors, idx, "Session duration exceeds 8 hour limit", "window_too_long")
                continue

            if end_dt > now + CLOCK_SKEW_TOLERANCE:
                _add_batch_error(errors, idx, "windowEnd is too far in the future", "clock_skew")
                continue

            duration_seconds = max(1, int((int(total_ms) + 999) // 1000))

            entries.append(
                schemas.UsageEntry(
                    app_name=str(package),
                    domain=None,
                    start=start_dt,
                    end=end_dt,
                    duration=duration_seconds,
                )
            )
            continue

        if "app_name" in item:
            try:
                entry = schemas.UsageEntry(**item)
            except ValidationError as exc:
                _add_batch_error(errors, idx, f"Invalid entry payload: {exc}", "invalid_entry")
                continue

            if entry.end <= entry.start:
                _add_batch_error(errors, idx, "end must be after start", "end_not_after_start")
                continue
            if entry.duration <= 0:
                _add_batch_error(errors, idx, "duration must be > 0", "non_positive_duration")
                continue
            if entry.end - entry.start > MAX_SESSION_DURATION:
                _add_batch_error(errors, idx, "Session duration exceeds 8 hour limit", "window_too_long")
                continue
            if entry.end > now + CLOCK_SKEW_TOLERANCE:
                _add_batch_error(errors, idx, "end timestamp is too far in the future", "clock_skew")
                continue

            entries.append(entry)
            continue

        _add_batch_error(errors, idx, "Unsupported item format", "unsupported_item")

    return entries, errors

# Path setup for proper static file serving
BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "dist"

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="NuScape Usage Tracker", 
    version="1.1.0",
    description="Cross-platform usage tracking with JWT-based device authentication",
    openapi_tags=[
        {"name": "auth", "description": "JWT device authentication (register, refresh, revoke)"},
        {"name": "usage", "description": "Usage data collection and analytics"},
        {"name": "devices", "description": "Device management and heartbeats"},
        {"name": "stats", "description": "Usage statistics and analytics"},
    ]
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # Type issue is a slowapi library quirk

# Custom OpenAPI configuration for JWT Bearer security
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add JWT Bearer security scheme
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    openapi_schema["components"]["securitySchemes"]["HTTPBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Use 'Authorization: Bearer {access_token}' for API authentication"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Global JSON fallback so crashes never return an empty body
@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.exception("UNHANDLED %s %s", request.method, request.url.path)
    return JSONResponse({"error": type(exc).__name__, "detail": str(exc)}, status_code=500)

# Include desktop usage router with JWT authentication
app.include_router(desktop_usage_router)

# Register dashboard API routes FIRST with highest priority  
dashboard_router = APIRouter(prefix=f"{API_BASE_PATH}/dashboard", tags=["dashboard"])

@dashboard_router.get("/devices", response_model=List[schemas.DeviceInfo])
async def get_devices_public(db: AsyncSession = Depends(get_db)):
    """Get all devices (public dashboard endpoint)"""
    devices = await crud.get_devices(db)
    return devices

@dashboard_router.get("/stats/today", response_model=schemas.StatsResponse)
async def get_today_stats_public(db: AsyncSession = Depends(get_db)):
    """Get today's usage stats (public dashboard endpoint)"""
    try:
        stats = await crud.get_today_stats(db)
        return stats
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get today's stats: {str(e)}"
        )

@dashboard_router.get("/apps/top", response_model=schemas.TopAppsResponse)
async def get_top_apps_public(
    db: AsyncSession = Depends(get_db),
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"), 
    limit: int = Query(default=5),
    device_id: Optional[str] = Query(default=None)
):
    """Get top apps (public dashboard endpoint)"""
    try:
        from datetime import datetime, timezone
        start_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        
        top_apps = await crud.get_top_apps(db, start_dt, end_dt, limit, device_id)
        return {"items": top_apps}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get top apps: {str(e)}"
        )

@dashboard_router.get("/usage", response_model=schemas.UsageSeries)
async def get_usage_analytics_public(
    db: AsyncSession = Depends(get_db),
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    group_by: str = Query(default="hour"),
    device_id: Optional[str] = Query(default=None)
):
    """Get usage analytics (public dashboard endpoint)"""
    try:
        from datetime import datetime, timezone
        start_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        
        usage_data = await crud.get_usage_analytics(db, start_dt, end_dt, group_by, device_id)
        return usage_data.model_dump(by_alias=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get usage analytics: {str(e)}"
        )

# Include the dashboard router with highest priority
logging.error(f"🔍 DEBUG: Including dashboard router with {len(dashboard_router.routes)} routes")
app.include_router(dashboard_router)
logging.error(f"🔍 DEBUG: Dashboard router included successfully")
# Register apps alias router for client-provided package metadata (labels + icons)
app.include_router(apps_alias_router)
# Register usage summary endpoints (attention/device/app totals)
app.include_router(usage_summary_router)
# Register debug endpoint to echo/validate incoming mobile items (dev only)
app.include_router(usage_debug_router)

# DIRECT ROUTE TEST - bypass router completely
@app.get(f"{API_BASE_PATH}/dashboard/test", tags=["test"])
async def dashboard_test_direct():
    """Direct dashboard test route (bypass router)"""
    logging.error("🎯 DIRECT ROUTE HIT: /api/v1/dashboard/test")
    return {"success": True, "message": "Direct dashboard route works!", "timestamp": "2025-09-18"}

# CORS configuration - open to Replit frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount React app build files - ALL static folders
app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")
if (DIST_DIR / "brand").exists():
    app.mount("/brand", StaticFiles(directory=str(DIST_DIR / "brand")), name="brand")
if (DIST_DIR / "static").exists():  # legacy if you keep it
    app.mount("/static", StaticFiles(directory=str(DIST_DIR / "static")), name="static")

# Security scheme
security = HTTPBearer()

@app.on_event("startup")
async def startup():
    """Create database tables and seed canonical app directory on startup"""
    # Initialize DB engine in a reload-safe way (defers engine creation to backend.database.init_engine)
    import backend.database as database
    database.init_engine()
    if database.engine:
        async with database.engine.begin() as conn:
            await conn.run_sync(models.Base.metadata.create_all)
        async with database.AsyncSessionLocal() as session:
            await load_app_seeds(session)

# Token refresh endpoint
@app.post(
    f"{API_BASE_PATH}/devices/refresh",
    response_model=schemas.TokenPair,
    tags=["auth"],
    summary="Refresh Access Token",
    description=(
        "Issue new JWT tokens using a valid refresh token.\n\n"
        "**Authentication:** Send refresh token in `Authorization: Bearer {refresh_token}`\n\n"
        "**Returns:** New access_token and refresh_token pair"
    ),
    dependencies=[Depends(security)],
    responses={
        200: {
            "description": "Tokens successfully refreshed",
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",
                        "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",
                        "token_type": "bearer",
                        "expires_in": 86400
                    }
                }
            }
        },
        401: {"description": "Invalid or expired refresh token"}
    }
)
async def refresh_device_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Refresh device JWT tokens using refresh token"""
    device = await auth.verify_device_refresh_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    # Create new access token with extended expiration
    new_token = auth.create_device_jwt(str(device.id), str(device.jwt_secret), expires_hours=24)
    new_refresh_token = auth.create_refresh_token(str(device.id), str(device.jwt_secret))
    
    return {
        "access_token": new_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": 86400  # 24 hours in seconds
    }

# Device revocation endpoint
@app.post(
    f"{API_BASE_PATH}/devices/revoke",
    response_model=schemas.RevokeResponse,
    tags=["auth"],
    summary="Revoke Device Tokens",
    description=(
        "Revoke all JWT tokens for the current device by regenerating the JWT secret.\n\n"
        "**Authentication:** Send refresh token in `Authorization: Bearer {refresh_token}`\n\n"
        "**Effect:** All existing access and refresh tokens become invalid"
    ),
    dependencies=[Depends(security)],
    responses={
        200: {
            "description": "Tokens successfully revoked",
            "content": {
                "application/json": {
                    "example": {
                        "revoked": True,
                        "message": "All tokens for this device have been invalidated"
                    }
                }
            }
        },
        401: {"description": "Invalid or expired refresh token"}
    }
)
async def revoke_device(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Revoke all tokens for the authenticated device"""
    device = await auth.verify_device_refresh_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    # Regenerate JWT secret to invalidate all existing tokens
    setattr(device, 'jwt_secret', auth.generate_device_secret())
    await db.commit()
    
    return schemas.RevokeResponse(
        revoked=True,
        message="All tokens for this device have been invalidated"
    )

# Health endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint with Redis connectivity status"""
    redis_status = redis_client.get_connection_status()
    
    # Determine overall health status
    overall_status = "ok"
    if redis_status["require_redis"] and not redis_status["available_for_storage"]:
        overall_status = "degraded"  # Redis required but not available
    elif not redis_status["connected"]:
        overall_status = "warning"   # Redis not connected but not required
    
    return {
        "status": overall_status,
        "redis": redis_status,
        "timestamp": datetime.now().isoformat()
    }

# Metrics endpoint
@app.get("/metrics-lite")
async def get_metrics():
    """Simple metrics endpoint for monitoring"""
    try:
        queue_info = redis_client.get_queue_info()
        metrics.set_gauge("queue_length", queue_info["length"])
        return metrics.get_metrics()
    except Exception as e:
        return {"error": str(e), "uptime_seconds": metrics.get_metrics()["uptime_seconds"]}

# NEW MVP BATCH EVENTS ENDPOINT
@app.post(
    f"{API_BASE_PATH}/events/batch", 
    response_model=schemas.EventBatchResponse,
    tags=["usage"],
    summary="Upload Usage Events",
    description=(
        "Upload usage events in batch format.\n\n"
        "**Authentication:** Required - use `Authorization: Bearer {access_token}`"
    ),
    dependencies=[Depends(security)]
)
@limiter.limit("50/minute")
async def batch_events(
    request: Request,
    batch_data: schemas.EventBatchRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """MVP Batch events endpoint - enqueue and acknowledge"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        metrics.increment("ingest_errors_total", labels={"reason": "auth_failed"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Verify device_id matches authenticated device
    if str(device.id) != batch_data.device_id:
        metrics.increment("ingest_errors_total", labels={"reason": "device_mismatch"})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device ID mismatch"
        )
    
    # CRITICAL: Check if Redis is available for durable storage
    if not redis_client.is_available():
        metrics.increment("ingest_errors_total", labels={"reason": "redis_unavailable"})
        logger.error(f"Redis unavailable - rejecting batch from device {batch_data.device_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event storage service temporarily unavailable. Please retry later."
        )
    
    # Extract event IDs for acknowledgment
    event_ids = []
    for event in batch_data.events:
        if "event_id" in event:
            event_ids.append(event["event_id"])
    
    # Check queue lag for backoff
    backoff_seconds = 0
    try:
        queue_info = redis_client.get_queue_info()
        queue_length = queue_info.get("length", 0)
        
        # Apply backoff if queue is getting backed up
        if queue_length > 50000:
            backoff_seconds = 30
        elif queue_length > 10000:
            backoff_seconds = 15
        elif queue_length > 5000:
            backoff_seconds = 5
            
    except Exception:
        # If we can't check queue, don't apply backoff
        pass
    
    # Enqueue batch into Redis Streams
    try:
        success = redis_client.enqueue_events(
            account_id="default",  # Single tenant for MVP
            device_id=batch_data.device_id,
            events_data={
                "events": batch_data.events,
                "sequence_start": batch_data.sequence_start,
                "client_version": batch_data.client_version
            }
        )
        
        if success:
            metrics.increment("ingest_requests_total")
            metrics.increment("queue_enqueue_total", len(event_ids))
            
            # Return acknowledgment with backoff hint
            return schemas.EventBatchResponse(
                acknowledged_ids=event_ids,
                backoff_seconds=backoff_seconds
            )
        else:
            metrics.increment("ingest_errors_total", labels={"reason": "queue_failed"})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to enqueue events"
            )
            
    except Exception as e:
        logging.error(f"Batch events error: {e}")
        metrics.increment("ingest_errors_total", labels={"reason": "internal_error"})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

# Device registration endpoint
@app.post(
    f"{API_BASE_PATH}/devices/register",
    response_model=schemas.RegisterResponse,
    tags=["auth"],
    summary="Register Device",
    description=(
        "Register a new device and receive JWT tokens for authentication.\n\n"
        "**Returns:**\n"
        "- `device_id`: Unique device identifier\n"
        "- `access_token`: JWT for API authentication (24h expiry)\n"
        "- `refresh_token`: JWT for token renewal (30d expiry)\n"
        "- `token_type`: Always 'bearer'\n"
        "- `expires_in`: Token expiry in seconds"
    ),
    status_code=201,
    responses={
        201: {
            "description": "Device successfully registered",
            "content": {
                "application/json": {
                    "example": {
                        "device_id": "123e4567-e89b-12d3-a456-426614174000",
                        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",
                        "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGci...",
                        "token_type": "bearer",
                        "expires_in": 86400
                    }
                }
            }
        }
    }
)
async def register_device(
    request: Request,
    device_data: schemas.DeviceCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register a new device and return JWT tokens for unified authentication"""
    # Debug logging for Android app
    logging.warning("== /api/v1/devices/register ==")
    logging.warning("Headers: %s", dict(request.headers))
    logging.warning("Device data:\n%s", json.dumps(device_data.model_dump(), indent=2, ensure_ascii=False))
    logging.warning("Hardware info: %s", device_data.hardware)
    
    try:
        device = await crud.create_device(db, device_data)
        
        # Generate JWT tokens for unified authentication
        access_token = auth.create_device_jwt(str(device.id), str(device.jwt_secret), expires_hours=24)
        refresh_token = auth.create_refresh_token(str(device.id), str(device.jwt_secret))
        
        # Return JWT tokens only - pure unified authentication
        return schemas.RegisterResponse(
            device_id=str(device.id),
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=86400  # 24 hours in seconds
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register device: {str(e)}"
        )

# Add version endpoint for debugging
@app.get("/__version")
def version():
    """Version info for debugging"""
    import os, time
    return {"pid": os.getpid(), "ts": int(time.time())}

# Tolerant usage batch endpoint (accepts both mobile and server formats)
@app.post(f"{API_BASE_PATH}/usage/batch", response_model=schemas.BatchResponse)
async def create_usage_batch_tolerant(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Accept usage batch in both mobile (items) and server (entries) formats"""
    # Parse request body to handle both formats
    try:
        body_data = await request.json()
        logging.warning("== /api/v1/usage/batch (TOLERANT) ==")
        auth_status = "Bearer [REDACTED]" if credentials else "None"
        logging.warning("Auth: %s", auth_status)
        logging.warning("Body:\n%s", json.dumps(body_data, indent=2, ensure_ascii=False))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {str(e)}"
        )
    
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )

    try:
        raw_items = _extract_raw_usage_items(body_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    now = datetime.now(timezone.utc)
    usage_entries, validation_errors = _collect_usage_entries(raw_items, now=now)

    accepted_count = 0
    duplicate_count = 0

    if db.in_transaction():
        await db.commit()

    try:
        async with db.begin():
            if usage_entries:
                insert_result = await crud.create_usage_logs(
                    db,
                    device,
                    usage_entries,
                )
                accepted_count = insert_result.accepted
                duplicate_count = insert_result.duplicates
                logging.warning(
                    "Accepted %s usage entries (duplicates=%s) for device %s",
                    accepted_count,
                    duplicate_count,
                    getattr(device, "name", "<unknown>"),
                )
                if accepted_count:
                    await crud.update_device_last_seen(
                        db,
                        device.id,
                    )
            else:
                logging.warning("Usage batch contained zero entries after validation")
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to persist usage batch")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process usage batch: {exc}",
        )

    rejected_count = len(validation_errors)
    if rejected_count:
        logging.warning(
            "Rejected %s usage items for device %s", rejected_count, device.id
        )

    logging.warning(
        "Usage batch processed: accepted=%s duplicates=%s rejected=%s for device %s",
        accepted_count,
        duplicate_count,
        rejected_count,
        device.id,
    )

    return schemas.BatchResponse(
        accepted=accepted_count,
        duplicates=duplicate_count,
        rejected=rejected_count,
        errors=validation_errors,
    )


@app.post(f"{API_BASE_PATH}/usage/validate", response_model=schemas.BatchResponse)
async def validate_usage_batch(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Validate a usage payload without persisting it."""

    try:
        body_data = await request.json()
        logging.debug("== /api/v1/usage/validate ==")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {exc}",
        )

    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token",
        )

    try:
        raw_items = _extract_raw_usage_items(body_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    entries, errors = _collect_usage_entries(raw_items, now=datetime.now(timezone.utc))
    rejected_count = len(errors)

    if rejected_count:
        logging.debug(
            "Validation rejected %s items for device %s", rejected_count, device.id
        )

    return schemas.BatchResponse(
        accepted=len(entries),
        duplicates=0,
        rejected=rejected_count,
        errors=errors,
    )


@app.post(f"{API_BASE_PATH}/usage/rollups/run")
async def trigger_rollup_job(
    date_str: Optional[str] = Query(None, alias="date"),
    account_id: str = Query("default"),
    gap_seconds: int = Query(SESSION_GAP_SECONDS, ge=30, le=600),
    cron_key: Optional[str] = Header(None, alias="X-Cron-Key"),
    db: AsyncSession = Depends(get_db),
):
    if ROLLUP_CRON_KEY and cron_key != ROLLUP_CRON_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid rollup key",
        )

    target_date = None
    if date_str:
        try:
            target_date = datetime.fromisoformat(date_str).date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format; use YYYY-MM-DD",
            )

    result = await run_daily_rollups(
        db,
        target_date=target_date,
        account_id=account_id,
        gap_seconds=gap_seconds,
    )
    return {"ok": True, "result": result}


# Old desktop endpoint removed - now handled by routes_usage_desktop.py

# Device self-lookup endpoint (mobile app needs this)
@app.get(f"{API_BASE_PATH}/devices/me")
async def get_device_me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Get current device info and entitlements"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Return device info with basic entitlements
    return {
        "device_id": str(device.id),
        "name": device.name,
        "platform": device.platform,
        "entitlements": {
            "tier": "free",  # Default tier for now
            "features": ["basic_tracking"]
        }
    }

# Policy endpoint (mobile app needs this)
@app.get(f"{API_BASE_PATH}/policy")
async def get_policy(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Get device policy/restrictions"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Return basic policy (empty for now)
    return {
        "version": 1,
        "rules": [],
        "restrictions": {},
        "updated_at": datetime.now().isoformat()
    }

# Events endpoint (mobile app needs this for heartbeats)
@app.post(f"{API_BASE_PATH}/events")
async def create_event(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Accept device events like heartbeats"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Parse event data
    try:
        event_data = await request.json()
        logging.warning("== /api/v1/events ==")
        logging.warning("Device: %s", device.name)
        logging.warning("Event:\n%s", json.dumps(event_data, indent=2, ensure_ascii=False))
        
        # Update device last_seen_at
        async with db.begin():
            await crud.update_device_last_seen(db, device.id)
        
        return {"status": "ok", "received": True}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event data: {str(e)}"
        )

# Stats endpoints
@app.get(
    f"{API_BASE_PATH}/stats/today", 
    response_model=schemas.StatsResponse,
    tags=["stats"],
    summary="Get Today's Usage Statistics",
    description="Get usage statistics for today - requires JWT authentication",
    dependencies=[Depends(security)],
    responses={401: {"description": "Invalid or expired access token"}}
)
async def get_today_stats(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Get usage statistics for today (JWT protected)"""
    # Verify JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    try:
        stats = await crud.get_today_stats(db)
        return stats
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get today's stats: {str(e)}"
        )

@app.get(
    f"{API_BASE_PATH}/stats/week", 
    response_model=schemas.StatsResponse,
    tags=["stats"],
    summary="Get Weekly Usage Statistics",
    description="Get usage statistics for the current week - requires JWT authentication",
    dependencies=[Depends(security)],
    responses={401: {"description": "Invalid or expired access token"}}
)
async def get_week_stats(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Get usage statistics for the current week (JWT protected)"""
    # Verify JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    try:
        stats = await crud.get_week_stats(db)
        return stats
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get week's stats: {str(e)}"
        )

# Duplicate dashboard endpoints removed - using dashboard_router instead

# Devices list endpoint
@app.get(
    f"{API_BASE_PATH}/devices", 
    response_model=List[schemas.DeviceInfo],
    tags=["devices"],
    summary="Get Registered Devices",
    description="Get list of registered devices - requires JWT authentication",
    dependencies=[Depends(security)],
    responses={401: {"description": "Invalid or expired access token"}}
)
async def get_devices(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Get list of registered devices (JWT protected)"""
    # Verify JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    try:
        devices = await crud.get_devices(db)
        return devices
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get devices: {str(e)}"
        )

# NEW REACT UI ENDPOINTS

# Usage analytics endpoint with flexible date ranges
@app.get(
    f"{API_BASE_PATH}/usage", 
    response_model=schemas.UsageSeries, 
    response_model_by_alias=True,
    tags=["usage"],
    summary="Get Usage Analytics",
    description="Get usage analytics data - requires JWT authentication",
    dependencies=[Depends(security)],
    responses={401: {"description": "Invalid or expired access token"}}
)
async def get_usage_analytics(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    group_by: str = Query(default="hour"),
    device_id: Optional[str] = Query(default=None)
):
    """Get usage analytics with flexible date ranges (JWT protected)"""
    # Verify JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    try:
        # Convert string dates to datetime objects
        from datetime import datetime, timezone
        start_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        
        # Get usage data from database
        usage_data = await crud.get_usage_analytics(
            db, start_dt, end_dt, group_by, device_id
        )
        
        return usage_data.model_dump(by_alias=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get usage analytics: {str(e)}"
        )

# Top apps endpoint
@app.get(
    f"{API_BASE_PATH}/apps/top", 
    response_model=schemas.TopAppsResponse,
    tags=["stats"],
    summary="Get Top Apps by Usage",
    description="Get top apps and sites by usage - requires JWT authentication",
    dependencies=[Depends(security)],
    responses={401: {"description": "Invalid or expired access token"}}
)
async def get_top_apps(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
    limit: int = Query(default=5),
    device_id: Optional[str] = Query(default=None)
):
    """Get top apps and sites by usage (JWT protected)"""
    # Verify JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    try:
        # Convert string dates to datetime objects
        from datetime import datetime, timezone
        start_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        
        # Get top apps data
        top_apps = await crud.get_top_apps(
            db, start_dt, end_dt, limit, device_id
        )
        
        return {"items": top_apps}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get top apps: {str(e)}"
        )

# Controls endpoint - get current controls state
@app.get(f"{API_BASE_PATH}/controls", response_model=schemas.ControlsState)
async def get_controls():
    """Get current usage controls and focus mode state"""
    return policy_store.get_controls()

# Controls endpoint - save controls state
@app.post(f"{API_BASE_PATH}/controls", response_model=schemas.ControlsState)
async def save_controls(controls: schemas.ControlsState):
    """Save usage controls and focus mode state"""
    return policy_store.set_controls(controls)

# Focus mode endpoint
@app.post(f"{API_BASE_PATH}/controls/focus", response_model=schemas.ControlsState)
async def activate_focus_mode(focus_request: dict):
    """Activate focus mode for specified duration"""
    from datetime import datetime, timezone, timedelta

    minutes = focus_request.get("minutes", 30)
    until_dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    focus_mode = schemas.FocusMode(active=True, until=until_dt.isoformat())
    return policy_store.update_focus_mode(focus_mode)

# Downloads endpoints
@app.get("/downloads/nuscape-windows.exe")
async def download_windows_app():
    """Download Windows executable"""
    # Build instructions: Run build_simple.bat in python-tracker folder
    # Then upload the dist/NuScapeTracker.exe to object storage
    raise HTTPException(
        status_code=status.HTTP_200_OK,
        detail={
            "message": "Windows app ready for download!",
            "build_instructions": "Run 'python-tracker/build_simple.bat' to create NuScapeTracker.exe",
            "requirements": "Python 3.7+ required on build machine",
            "output": "dist/NuScapeTracker.exe"
        }
    )

@app.get("/downloads/nuscape-macos.dmg")
async def download_macos_app():
    """Download macOS application"""
    # Build instructions: Run build_macos.sh in python-tracker folder
    # Then upload the dist/NuScapeTracker to object storage
    raise HTTPException(
        status_code=status.HTTP_200_OK,
        detail={
            "message": "macOS app ready for download!",
            "build_instructions": "Run 'python-tracker/build_macos.sh' to create NuScapeTracker",
            "requirements": "Python 3.7+ and Xcode Command Line Tools required on build machine",
            "output": "dist/NuScapeTracker"
        }
    )

@app.get("/mobile")
async def mobile_redirect():
    """Redirect mobile users to the main dashboard"""
    return {"message": "Use the main dashboard - it's mobile-friendly!", "dashboard_url": "/"}

# NEW ENHANCED ENDPOINTS

# Heartbeat endpoint
@app.post(f"{API_BASE_PATH}/devices/heartbeat", response_model=schemas.HeartbeatResponse)
@limiter.limit("60/minute")
async def device_heartbeat(
    request: Request,
    heartbeat_data: schemas.HeartbeatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Device heartbeat endpoint for active connection tracking"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Update device heartbeat timestamp
    from sqlalchemy import update
    await db.execute(
        update(models.Device)
        .where(models.Device.id == device.id)
        .values(
            last_heartbeat_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc)
        )
    )
    await db.commit()

    return schemas.HeartbeatResponse(
        received=True,
        server_time=datetime.now(timezone.utc),
        next_heartbeat_in=300
    )

# Bulk events endpoint  
@app.post(f"{API_BASE_PATH}/devices/{{device_id}}/events", response_model=schemas.EventsBatchResponse)
@limiter.limit("120/minute")
async def create_device_events(
    device_id: str,
    request: Request,
    events_data: schemas.EventsBatchRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Bulk events upload endpoint for usage tracking"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Verify device_id matches authenticated device
    if str(device.id) != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device ID mismatch"
        )
    
    accepted = 0
    rejected = 0
    errors = []
    
    # Process each event
    for event in events_data.events:
        try:
            candidate_name = event.app_package or event.app_name
            namespace, raw_ident, display_name = infer_alias_context(
                device.platform, app_name=candidate_name, domain=event.domain
            )
            resolution = await resolve_app(
                db,
                namespace=namespace,
                ident=raw_ident,
                display_name=display_name,
            )
            alias_ident = resolution.alias.ident
            domain_value = event.domain.strip().lower() if event.domain else None
            usage_event = models.UsageEvent(
                device_id=device.id,
                app_id=resolution.app.app_id,
                event_type=event.event_type,
                app_name=resolution.app.display_name,
                app_package=event.app_package or (event.app_name if namespace == "android" else event.app_package),
                domain=domain_value,
                window_title=event.window_title,
                alias_namespace=namespace,
                alias_ident=alias_ident,
                duration_ms=event.duration_ms,
                event_timestamp=event.event_timestamp,
                event_metadata=json.dumps(event.metadata) if event.metadata else None
            )
            db.add(usage_event)
            await db.commit()
            accepted += 1
        except Exception as e:
            await db.rollback()
            rejected += 1
            errors.append(f"Event rejected: {str(e)}")

    # Update device last_seen_at
    async with db.begin():
        await crud.update_device_last_seen(db, device.id)

    return schemas.EventsBatchResponse(
        accepted=accepted,
        rejected=rejected,
        errors=errors
    )

# Enhanced policy endpoint
@app.get(f"{API_BASE_PATH}/devices/{{device_id}}/policy", response_model=schemas.DevicePolicy)
async def get_device_policy(
    device_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Get device-specific policy and restrictions"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Verify device_id matches authenticated device
    if str(device.id) != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device ID mismatch"
        )
    
    state = policy_store.get_controls()
    return schemas.DevicePolicy(
        version=1,
        time_limits={},
        blocked_app_ids=list(state.blocked_app_ids or []),
        blocked_domains=[],
        content_filters={},
        enforcement_level="warning",
        updated_at=datetime.now(timezone.utc)
    )

# Violations endpoint
@app.post(f"{API_BASE_PATH}/devices/{{device_id}}/violations", response_model=schemas.ViolationResponse)
@limiter.limit("30/minute")
async def create_policy_violation(
    device_id: str,
    request: Request,
    violation_data: schemas.PolicyViolationCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Report policy violations from device"""
    # Unified device JWT authentication
    device = await auth.verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    
    # Verify device_id matches authenticated device
    if str(device.id) != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device ID mismatch"
        )
    
    # Create violation record
    violation = models.PolicyViolation(
        device_id=device.id,
        app_id=violation_data.app_id,
        violation_type=violation_data.violation_type,
        app_name=violation_data.app_name,
        app_package=violation_data.app_package,
        domain=violation_data.domain,
        violation_details=json.dumps(violation_data.violation_details) if violation_data.violation_details else None,
        violation_timestamp=violation_data.violation_timestamp
    )
    
    db.add(violation)
    await db.commit()
    await db.refresh(violation)
    
    return schemas.ViolationResponse(
        violation_id=str(violation.id),
        received=True,
        action_taken="logged"
    )

# Development token endpoint (for React UI auth testing)
@app.post(f"{API_BASE_PATH}/dev/token")
async def create_dev_token(db: AsyncSession = Depends(get_db)):
    """Create a temporary development token for React UI testing"""
    # Create or get existing dev device
    from backend.crud import get_device_by_name
    from backend.auth import create_device_jwt
    
    dev_device = await get_device_by_name(db, "dev-react-ui")
    
    if not dev_device:
        # Create a dev device
        from backend.crud import create_device
        dev_device_data = schemas.DeviceCreate(
            platform="web",
            name="dev-react-ui",
            hardware={"browser": "dev"}
        )
        dev_device = await create_device(db, dev_device_data)
    
    # Generate JWT token
    token = create_device_jwt(str(dev_device.id), str(dev_device.jwt_secret), expires_hours=168)  # 1 week
    
    return {
        "token": token,
        "device_id": dev_device.id,
        "device_name": dev_device.name,
        "expires_in": "7 days"
    }

# Serve frontend at root
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(str(DIST_DIR / "index.html"))

# TEMPORARILY DISABLED SPA fallback to test dashboard routes
# Serve React app for all frontend routes (SPA routing)
# SPA fallback: serve index.html for any unknown GET path (after API routes!)
# @app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback_disabled(request: Request, full_path: str):
    # DEBUG: Log all requests to see what's happening
    logging.error(f"🔍 SPA FALLBACK HIT: full_path='{full_path}', request.url.path='{request.url.path}', API_BASE_PATH='{API_BASE_PATH}'")
    
    # Skip ALL API paths - let them return proper 404s instead of HTML
    if full_path.startswith("api/") or full_path.startswith("api") or request.url.path.startswith("/api"):
        logging.error(f"🚫 SPA fallback SHOULD SKIP API path: {full_path} (URL: {request.url.path})")
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    logging.warning(f"SPA fallback serving: {full_path}")
    file_path = DIST_DIR / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return FileResponse(str(DIST_DIR / "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, reload=True)



