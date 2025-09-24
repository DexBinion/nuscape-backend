import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.models import Device
# Removed legacy import: get_device_by_key
from backend.database import get_db

# Device authentication constants
DEFAULT_TOKEN_EXPIRY_HOURS = 24
REFRESH_TOKEN_EXPIRY_DAYS = 30

def generate_device_secret() -> str:
    """Generate a secure random secret for JWT signing"""
    return secrets.token_urlsafe(32)

def create_device_jwt(device_id: str, device_secret: str, expires_hours: int = DEFAULT_TOKEN_EXPIRY_HOURS) -> str:
    """Create a JWT token for device authentication"""
    payload = {
        "device_id": device_id,
        "exp": datetime.utcnow() + timedelta(hours=expires_hours),
        "iat": datetime.utcnow(),
        "type": "device_auth"
    }
    return jwt.encode(payload, device_secret, algorithm="HS256")

def verify_device_jwt(token: str, device_secret: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a device JWT token"""
    try:
        payload = jwt.decode(token, device_secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Legacy device_key authentication function removed - JWT-only system

async def verify_device_jwt_auth(db: AsyncSession, token: str) -> Optional[Device]:
    """Verify JWT token and return device if valid"""
    if not token:
        return None
    
    # Extract device_id from token without verifying (to get the secret)
    try:
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        device_id = unverified_payload.get("device_id")
        if not device_id:
            return None
    except jwt.InvalidTokenError:
        return None
    
    # Get device to access its JWT secret
    from backend.crud import get_device_by_id
    device = await get_device_by_id(db, device_id)
    if not device or not hasattr(device, 'jwt_secret') or not device.jwt_secret:
        return None
    
    # Verify the token with the device's secret
    payload = verify_device_jwt(token, str(device.jwt_secret))
    if not payload:
        return None
    
    # Enforce token type - only accept access tokens
    if payload.get("type") != "device_auth":
        return None
    
    return device

# Unified device authentication
security = HTTPBearer(auto_error=True)

async def require_device(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Device:
    """Unified device authentication dependency - JWT only"""
    device = await verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired device token"
        )
    return device

def create_refresh_token(device_id: str, device_secret: str) -> str:
    """Create a long-lived refresh token for device"""
    payload = {
        "device_id": device_id,
        "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS),
        "iat": datetime.utcnow(),
        "type": "device_refresh"
    }
    return jwt.encode(payload, device_secret, algorithm="HS256")

def verify_refresh_token(token: str, device_secret: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a refresh token"""
    try:
        payload = jwt.decode(token, device_secret, algorithms=["HS256"])
        if payload.get("type") != "device_refresh":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

async def verify_device_refresh_auth(db: AsyncSession, token: str) -> Optional[Device]:
    """Verify refresh token and return device if valid"""
    if not token:
        return None
    
    # Extract device_id from token without verifying (to get the secret)
    try:
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        device_id = unverified_payload.get("device_id")
        if not device_id:
            return None
    except jwt.InvalidTokenError:
        return None
    
    # Get device to access its JWT secret
    from backend.crud import get_device_by_id
    device = await get_device_by_id(db, device_id)
    if not device or not hasattr(device, 'jwt_secret') or not device.jwt_secret:
        return None
    
    # Verify the refresh token with the device's secret
    payload = verify_refresh_token(token, str(device.jwt_secret))
    if not payload:
        return None
    
    return device
