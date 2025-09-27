from fastapi import APIRouter, Depends, HTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY, HTTP_403_FORBIDDEN
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.schemas import DesktopUsageBatch, UsageEntry, BatchResponse
from backend.auth import require_device
from backend import crud
import logging

router = APIRouter()
log = logging.getLogger("usage")


@router.post("/api/v1/usage/batch/desktop")
async def usage_batch_desktop(
    batch: DesktopUsageBatch,
    device=Depends(require_device),
    db: AsyncSession = Depends(get_db)
):
    """Accept desktop batch usage logs with unified device JWT authentication."""
    log.info("desktop batch device=%s entries=%d", device.id, len(batch.entries))

    # Validate device_id matches authenticated device
    if str(device.id) != str(batch.device_id):
        raise HTTPException(HTTP_403_FORBIDDEN, "Device ID mismatch")

    entries: list[UsageEntry] = []
    for entry in batch.entries:
        if entry.duration < 0 or entry.end < entry.start:
            raise HTTPException(HTTP_422_UNPROCESSABLE_ENTITY, "Invalid duration or timestamps")

        entries.append(
            UsageEntry(
                app_name=entry.app_name,
                domain=None,
                start=entry.start,
                end=entry.end,
                duration=entry.duration,
            )
        )

    accepted = 0
    duplicates = 0
    if entries:
        if db.in_transaction():
            await db.rollback()

        try:
            async with db.begin():
                result = await crud.create_usage_logs(db, device, entries)
                accepted = result.accepted
                duplicates = result.duplicates
                if accepted:
                    await crud.update_device_last_seen(db, device.id)
        except Exception as exc:
            log.exception("desktop usage batch failed")
            raise HTTPException(status_code=500, detail=f"Failed to persist usage: {exc}")

        total_duration_mins = sum(e.duration for e in entries) // 60
        log.info(
            "desktop accepted=%d duplicates=%d device=%s total_mins=%d",
            accepted,
            duplicates,
            device.id,
            total_duration_mins,
        )

    return BatchResponse(accepted=accepted, duplicates=duplicates)
