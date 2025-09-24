import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Integer,
    ForeignKey,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class App(Base):
    """Canonical directory entry for an application or site."""

    __tablename__ = "apps"

    app_id = Column(String(128), primary_key=True)
    display_name = Column(String(255), nullable=False)
    category = Column(String(64), nullable=True)
    icon_url = Column(Text, nullable=True)
    icon_b64 = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    aliases = relationship("AppAlias", back_populates="app", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="app")
    usage_events = relationship("UsageEvent", back_populates="app")
    hourly_usage = relationship("HourlyAggregate", back_populates="app")
    violations = relationship("PolicyViolation", back_populates="app")


class AppAlias(Base):
    """Namespace-specific identifier that maps to a canonical app."""

    __tablename__ = "app_aliases"
    __table_args__ = (
        UniqueConstraint("namespace", "ident", name="uq_app_alias_namespace_ident"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_id = Column(String(128), ForeignKey("apps.app_id", ondelete="CASCADE"), nullable=False, index=True)
    namespace = Column(String(50), nullable=False, index=True)
    ident = Column(String(255), nullable=False)
    match_kind = Column(String(32), nullable=False, default="equals")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    details = Column(Text, nullable=True)

    app = relationship("App", back_populates="aliases")


class Device(Base):
    """Device model for registered devices"""

    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    device_key = Column(String(255), unique=True, nullable=True, index=True)
    jwt_secret = Column(String(255), nullable=False, index=True)
    hardware_fingerprint = Column(Text, nullable=True, index=True)
    device_uid = Column(Text, nullable=True, unique=True, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    usage_logs = relationship("UsageLog", back_populates="device", cascade="all, delete-orphan")
    usage_events = relationship("UsageEvent", back_populates="device", cascade="all, delete-orphan")
    violations = relationship("PolicyViolation", back_populates="device", cascade="all, delete-orphan")
    app_sessions = relationship("AppSession", back_populates="device", cascade="all, delete-orphan")


class UsageLog(Base):
    """Usage log model for tracking app usage"""

    __tablename__ = "usage_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    app_id = Column(String(128), ForeignKey("apps.app_id"), nullable=True, index=True)
    app_name = Column(String(255), nullable=False)
    app_package = Column(String(255), nullable=True, index=True)
    app_label = Column(String(255), nullable=True)
    alias_namespace = Column(String(50), nullable=True)
    alias_ident = Column(String(255), nullable=True)
    domain = Column(String(255), nullable=True)
    start = Column(DateTime(timezone=True), nullable=False, index=True)
    end = Column(DateTime(timezone=True), nullable=False)
    duration = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    device = relationship("Device", back_populates="usage_logs")
    app = relationship("App", back_populates="usage_logs")


class AppMetadata(Base):
    """Latest metadata for apps/packages"""

    __tablename__ = "app_metadata"

    package = Column(String(255), primary_key=True)
    platform = Column(String(50), nullable=True)
    label = Column(String(255), nullable=True)
    icon_base64 = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UsageEvent(Base):
    """Raw usage events from devices before aggregation"""

    __tablename__ = "usage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    app_id = Column(String(128), ForeignKey("apps.app_id"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False)
    app_name = Column(String(255), nullable=False, index=True)
    app_package = Column(String(255), nullable=True)
    domain = Column(String(255), nullable=True)
    window_title = Column(String(500), nullable=True)
    alias_namespace = Column(String(50), nullable=True)
    alias_ident = Column(String(255), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    event_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    event_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    device = relationship("Device", back_populates="usage_events")
    app = relationship("App", back_populates="usage_events")
    
    
class AppSession(Base):
    """Per-app session reported from mobile devices (screen-time / engaged sessions)"""
    
    __tablename__ = "app_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    package = Column(String(255), nullable=False, index=True)
    start_ts = Column(DateTime(timezone=True), nullable=False, index=True)
    end_ts = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_ms = Column(Integer, nullable=False)
    engaged_ms = Column(Integer, nullable=True)
    interaction_count = Column(Integer, nullable=True)
    screen_on_only = Column(Boolean, nullable=False, default=True)
    source = Column(String(255), nullable=True)  # e.g. "usage_events+screen_state(+accessibility)"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    device = relationship("Device", back_populates="app_sessions")
    
    
class HourlyAggregate(Base):
    """Hourly aggregated usage statistics"""
    
    __tablename__ = "hourly_aggregates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    app_id = Column(String(128), ForeignKey("apps.app_id"), nullable=True, index=True)
    app_name = Column(String(255), nullable=False)
    app_package = Column(String(255), nullable=True)
    hour_start = Column(DateTime(timezone=True), nullable=False, index=True)
    total_duration_ms = Column(Integer, nullable=False)
    session_count = Column(Integer, nullable=False)
    focus_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    app = relationship("App", back_populates="hourly_usage")


class PolicyViolation(Base):
    """Policy violations for devices"""

    __tablename__ = "policy_violations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    app_id = Column(String(128), ForeignKey("apps.app_id"), nullable=True, index=True)
    violation_type = Column(String(50), nullable=False)
    app_name = Column(String(255), nullable=True)
    app_package = Column(String(255), nullable=True)
    domain = Column(String(255), nullable=True)
    violation_details = Column(Text, nullable=True)
    violation_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    device = relationship("Device", back_populates="violations")
    app = relationship("App", back_populates="violations")

