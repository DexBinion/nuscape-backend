from typing import Optional
import base64
from pydantic import BaseModel
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.auth import verify_device_jwt_auth, create_device_jwt  # keep auth imports for dependency pattern if needed

router = APIRouter(prefix="/api/v1/apps/alias", tags=["apps"])


class AliasUpsert(BaseModel):
    packageName: str
    label: str
    versionName: Optional[str] = None
    versionCode: Optional[int] = None
    iconBase64: Optional[str] = None
    iconHash: Optional[str] = None


@router.post("/upsert", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_alias(
    body: AliasUpsert,
    credentials = Depends(),  # leave for route protection via middleware; verify explicitly below
    db: AsyncSession = Depends(get_db),
):
    """
    Upsert an app alias by package name. Auth: caller must be a registered device (JWT).
    """
    # Try to authenticate device (reuse existing auth helpers)
    try:
        # verify_device_jwt_auth expects db and token; use credentials if provided by HTTPBearer
        # If credentials is not an HTTPAuthorizationCredentials object, skip (route can be adjusted)
        token = None
        if hasattr(credentials, "credentials"):
            token = credentials.credentials
        device = await verify_device_jwt_auth(db, token) if token else None
        if not device:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing device token")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing device token")

    icon_bytes = None
    if body.iconBase64:
        try:
            icon_bytes = base64.b64decode(body.iconBase64)
        except Exception:
            icon_bytes = None

    sql = text(
        """
        INSERT INTO app_aliases_package
            (package_name, label, version_name, version_code, icon_hash, icon_png, updated_at)
        VALUES (:package_name, :label, :version_name, :version_code, :icon_hash, :icon_png, now())
        ON CONFLICT (package_name) DO UPDATE SET
            label = EXCLUDED.label,
            version_name = EXCLUDED.version_name,
            version_code = EXCLUDED.version_code,
            icon_hash = COALESCE(EXCLUDED.icon_hash, app_aliases_package.icon_hash),
            icon_png  = COALESCE(EXCLUDED.icon_png,  app_aliases_package.icon_png),
            updated_at = now()
        """
    )

    params = {
        "package_name": body.packageName,
        "label": body.label,
        "version_name": body.versionName,
        "version_code": body.versionCode,
        "icon_hash": body.iconHash,
        "icon_png": icon_bytes,
    }

    try:
        await db.execute(sql, params)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"DB error: {e}")