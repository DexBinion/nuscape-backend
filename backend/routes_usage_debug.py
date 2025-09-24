from typing import List, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.auth import verify_device_jwt_auth
from datetime import datetime

router = APIRouter(prefix="/api/v1/usage", tags=["debug"])
security = HTTPBearer()


@router.post("/debug")
async def usage_debug(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """
    Debug endpoint: parse incoming mobile-format items[] and return the parsed representation.
    Requires device JWT auth (same as /usage/batch).
    Useful to verify exact JSON shape the server sees.
    """
    # Authenticate device
    device = await verify_device_jwt_auth(db, credentials.credentials)
    if not device:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired device token")

    try:
        body_data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {e}")

    raw_items = body_data.get("items") or []
    parsed: List[Dict] = []

    for i, item in enumerate(raw_items):
        info = {"index": i, "raw": item}
        if not isinstance(item, dict):
            info["error"] = "item not an object"
            parsed.append(info)
            continue

        pkg = item.get("package")
        totalMs = item.get("totalMs")
        ws = item.get("windowStart")
        we = item.get("windowEnd")

        # Basic required checks
        if not pkg:
            info["error"] = "missing package"
            parsed.append(info); continue
        if totalMs is None:
            info["error"] = "missing totalMs"
            parsed.append(info); continue
        if not ws or not we:
            info["error"] = "missing windowStart/windowEnd"
            parsed.append(info); continue

        # Parse timestamps
        try:
            start_dt = datetime.fromisoformat(ws.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(we.replace("Z", "+00:00"))
        except Exception as e:
            info["error"] = f"invalid ISO timestamp: {e}"
            parsed.append(info); continue

        if end_dt <= start_dt:
            info["error"] = "windowEnd must be > windowStart"
            parsed.append(info); continue

        # Cap check (8 hours)
        if (end_dt - start_dt).total_seconds() > 8 * 3600:
            info["error"] = "session exceeds 8 hour maximum"
            parsed.append(info); continue

        info.update({
            "package": pkg,
            "totalMs": int(totalMs),
            "windowStart": start_dt.isoformat(),
            "windowEnd": end_dt.isoformat(),
            "duration_ms": int((end_dt - start_dt).total_seconds() * 1000),
        })
        parsed.append(info)

    return {"parsed_items": parsed, "count": len(parsed)}