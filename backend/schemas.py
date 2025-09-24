from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, model_validator
from uuid import UUID
import uuid

# Device schemas
class DeviceCreate(BaseModel):
    platform: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    hardware: Optional[dict] = Field(None)  # Mobile app sends hardware info

# JWT Authentication Response Models
class TokenPair(BaseModel):
    """Base JWT token pair response"""
    access_token: str = Field(..., description="JWT access token for API authentication")
    refresh_token: str = Field(..., description="JWT refresh token for token renewal")
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(86400, description="Seconds until access token expiry")

class RegisterResponse(TokenPair):
    """Device registration response with JWT tokens"""
    device_id: str = Field(..., description="Unique device identifier")

class RevokeResponse(BaseModel):
    """Device revocation response"""
    revoked: bool = True
    message: str = Field(..., description="Revocation confirmation message")

class DeviceInfo(BaseModel):
    id: str
    name: str
    platform: str
    last_seen: Optional[datetime] = Field(alias="lastSeen")
    status: str = "active"  # Default status
    
    # Keep original fields for compatibility
    last_seen_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True

# Usage log schemas
class UsageEntry(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=255)
    domain: Optional[str] = Field(None, max_length=255)
    start: datetime
    end: datetime
    duration: int = Field(..., ge=0)  # Duration in seconds, must be >= 0

# Mobile app usage format
class MobileUsageItem(BaseModel):
    package: str = Field(..., min_length=1, max_length=255)
    totalMs: int = Field(..., ge=0)
    windowStart: str
    windowEnd: str

class UsageBatch(BaseModel):
    device_id: str
    entries: List[UsageEntry]

# Mobile app format
class MobileUsageBatch(BaseModel):
    items: List[MobileUsageItem]

class BatchResponse(BaseModel):
    accepted: int

# Desktop usage entry schemas (per attached fix)
class DesktopUsageEntry(BaseModel):
    app_name: str
    start: datetime
    end: datetime
    duration: int
    window_title: Optional[str] = None
    categories: Optional[List[str]] = None
    breakdown: Optional[Dict[str, int]] = None

class DesktopUsageBatch(BaseModel):
    device_id: UUID
    entries: List[DesktopUsageEntry]

# Stats schemas
class AppStats(BaseModel):
    app_name: str
    total_duration: int  # Total duration in seconds
    session_count: int

class StatsResponse(BaseModel):
    total_duration: int  # Total duration in seconds
    total_sessions: int
    top_apps: List[AppStats]
    period: str  # "today" or "week"

# New MVP batch events schema per spec

class EventBatchRequest(BaseModel):
    device_id: str
    sequence_start: int = 0
    events: List[Dict[str, Any]]
    client_version: str = "unknown"

class EventBatchResponse(BaseModel):
    acknowledged_ids: List[str]
    backoff_seconds: int = 0

# New schemas for React UI endpoints
class UsagePoint(BaseModel):
    ts: str  # ISO timestamp
    minutes: int
    breakdown: Dict[str, int] = {}

class UsageSeries(BaseModel):
    from_date: str = Field(alias="from")
    to_date: str = Field(alias="to") 
    points: List[UsagePoint]
    
    class Config:
        populate_by_name = True

class TopAppItem(BaseModel):
    app_id: str
    display_name: str
    category: str = "other"
    icon_url: Optional[str] = None
    icon_b64: Optional[str] = None
    total_seconds: int
    wifi_bytes: int = 0
    cell_bytes: int = 0
    breakdown: Dict[str, int] = Field(default_factory=dict)
    primary_namespace: Optional[str] = None
    primary_identifier: Optional[str] = None


class TopAppsResponse(BaseModel):
    items: List[TopAppItem]


class Rule(BaseModel):
    id: str
    category: str
    limit_minutes_per_day: Optional[int] = Field(None, alias="limitMinutesPerDay")
    block: Optional[bool] = None
    schedule: Optional[List[Dict[str, str]]] = None

class FocusMode(BaseModel):
    active: bool
    until: Optional[str] = None

    class Config:
        populate_by_name = True


class ControlsState(BaseModel):
    rules: List[Rule] = []
    focus_mode: FocusMode = Field(default_factory=lambda: FocusMode(active=False), alias="focusMode")
    blocked_app_ids: List[str] = Field(default_factory=list, alias="blockedAppIds")

    @model_validator(mode="before")
    @classmethod
    def _normalize_blocked_app_ids(cls, values: Dict[str, Any]):
        blocked = values.get("blockedAppIds") or values.get("blocked_app_ids")
        if blocked is None:
            blocked = values.get("blockedApps")
        values["blockedAppIds"] = blocked or []
        return values

    class Config:
        populate_by_name = True


# Previous enhanced API schemas (keeping for compatibility)

class HeartbeatRequest(BaseModel):
    timestamp: datetime
    status: str = "active"
    metadata: Optional[Dict[str, Any]] = None

class HeartbeatResponse(BaseModel):
    received: bool = True
    server_time: datetime
    next_heartbeat_in: int = 300  # seconds

class UsageEventCreate(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=50)
    app_name: str = Field(..., min_length=1, max_length=255)
    app_package: Optional[str] = Field(None, max_length=255)
    domain: Optional[str] = Field(None, max_length=255)
    window_title: Optional[str] = Field(None, max_length=500)
    duration_ms: Optional[int] = Field(None, ge=0)
    event_timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None

class EventsBatchRequest(BaseModel):
    events: List[UsageEventCreate]

class EventsBatchResponse(BaseModel):
    accepted: int
    rejected: int
    errors: List[str] = []

class DevicePolicy(BaseModel):
    version: int = 1
    time_limits: Dict[str, int] = {}
    blocked_app_ids: List[str] = Field(default_factory=list, alias="blockedAppIds")
    blocked_domains: List[str] = []
    content_filters: Dict[str, Any] = {}
    enforcement_level: str = "warning"
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize_blocked_ids(cls, values: Dict[str, Any]):
        blocked = values.get("blockedAppIds") or values.get("blocked_app_ids")
        if blocked is None:
            blocked = values.get("blocked_apps") or values.get("blockedApps")
        values["blockedAppIds"] = blocked or []
        return values

    class Config:
        populate_by_name = True


class PolicyViolationCreate(BaseModel):
    violation_type: str = Field(..., min_length=1, max_length=50)
    app_id: Optional[str] = Field(None, alias="appId")
    app_name: Optional[str] = Field(None, max_length=255)
    app_package: Optional[str] = Field(None, max_length=255)
    domain: Optional[str] = Field(None, max_length=255)
    violation_details: Optional[Dict[str, Any]] = None
    violation_timestamp: datetime


class ViolationResponse(BaseModel):
    violation_id: str
    app_id: Optional[str] = Field(None, alias="appId")
    received: bool = True
    action_taken: str = "logged"

    class Config:
        populate_by_name = True


# Apply config to all schemas - use model_config for Pydantic v2
for model_class in [DeviceCreate, DeviceInfo, UsageEntry, UsageBatch, BatchResponse, AppStats, StatsResponse,
                   HeartbeatRequest, HeartbeatResponse, UsageEventCreate, EventsBatchRequest, EventsBatchResponse,
                   DevicePolicy, PolicyViolationCreate, ViolationResponse]:
    if not hasattr(model_class, 'model_config'):
        model_class.model_config = {
            "from_attributes": True,
            "json_encoders": {
                datetime: lambda v: v.isoformat()
            }
        }






