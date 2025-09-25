from __future__ import annotations

import re
import unicodedata
import base64
from dataclasses import dataclass
from typing import Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from backend import models


def infer_alias_context(platform: str, *, app_name: Optional[str], domain: Optional[str]) -> tuple[str, str, str]:
    """Return namespace, identifier, and display label for a usage record."""
    platform_normalized = (platform or "").strip().lower()

    if domain:
        domain_normalized = domain.strip().lower()
        display = domain.strip() or domain_normalized
        return "web", domain_normalized, display

    app_name = (app_name or "").strip()

    if platform_normalized in {"android", "ios"}:
        ident = app_name.lower() or "unknown"
        display = app_name or ident
        return platform_normalized, ident, display

    if platform_normalized in {"windows", "linux", "macos"}:
        ident = app_name.lower() or "unknown"
        display = app_name or ident
        return platform_normalized, ident, display

    ident = app_name.lower() or "unknown"
    display = app_name or ident
    return platform_normalized or "generic", ident, display


@dataclass
class AppResolution:
    """Result of resolving an identifier to a canonical app."""

    app: models.App
    alias: models.AppAlias
    created_app: bool = False
    created_alias: bool = False


async def resolve_app(
    db: AsyncSession,
    *,
    namespace: str,
    ident: str,
    display_name: Optional[str] = None,
    category: Optional[str] = None,
    icon_url: Optional[str] = None,
    icon_b64: Optional[str] = None,
    match_kind: str = "equals",
) -> AppResolution:
    """Resolve an identifier into a canonical app, creating entries if needed."""

    namespace = namespace.strip().lower()
    ident = _normalise_identifier(namespace, ident)

    if not ident:
        ident = f"unknown-{namespace}"

    # Lookup existing alias
    alias_stmt = sa.select(models.AppAlias).where(
        models.AppAlias.namespace == namespace,
        models.AppAlias.ident == ident,
    )
    alias = (await db.execute(alias_stmt)).scalar_one_or_none()
    if alias:
        app = await db.get(models.App, alias.app_id)
        if app is None:
            raise RuntimeError(f"Alias {alias.id} points to missing app {alias.app_id}")
        return AppResolution(app=app, alias=alias, created_app=False, created_alias=False)

    # Create app if it does not exist.
    # First, consult package-level metadata (app_aliases_package) if present for mobile packages.
    # This restores previous behavior where devices could supply a friendly label/icon for a package.
    # Prefer package metadata label/icon over the raw display_name passed in (which is often the package).
    if namespace == "android":
        try:
            pkg_stmt = sa.text(
                "SELECT label, icon_png FROM app_aliases_package WHERE package_name = :pkg LIMIT 1"
            )
            pkg_row = (await db.execute(pkg_stmt, {"pkg": ident})).first()
            if pkg_row:
                pkg_label = getattr(pkg_row, "label", None) or (pkg_row[0] if len(pkg_row) > 0 else None)
                pkg_icon_png = getattr(pkg_row, "icon_png", None) or (pkg_row[1] if len(pkg_row) > 1 else None)
                if pkg_label:
                    display_name = pkg_label
                if pkg_icon_png and not icon_b64:
                    try:
                        # icon_png is binary bytes in the DB; convert to base64 string for storing on App
                        icon_b64 = base64.b64encode(pkg_icon_png).decode("ascii")
                    except Exception:
                        # best-effort: ignore icon encoding errors
                        pass
        except Exception:
            # Non-fatal: if the metadata table is missing or query fails, continue with fallback
            pass

    display_name = display_name or _fallback_display_name(namespace, ident)
    app_id = await _ensure_app_id(db, display_name)

    app = models.App(
        app_id=app_id,
        display_name=display_name,
        category=category,
        icon_url=icon_url,
        icon_b64=icon_b64,
    )
    db.add(app)
    await db.flush()

    alias = models.AppAlias(
        app_id=app.app_id,
        namespace=namespace,
        ident=ident,
        match_kind=match_kind,
    )
    db.add(alias)
    await db.flush()

    return AppResolution(app=app, alias=alias, created_app=True, created_alias=True)


async def add_alias(
    db: AsyncSession,
    *,
    app_id: str,
    namespace: str,
    ident: str,
    match_kind: str = "equals",
) -> models.AppAlias:
    """Attach a new alias to an existing app if it is not already present."""

    namespace = namespace.strip().lower()
    ident = _normalise_identifier(namespace, ident)

    alias_stmt = sa.select(models.AppAlias).where(
        models.AppAlias.namespace == namespace,
        models.AppAlias.ident == ident,
    )
    existing = (await db.execute(alias_stmt)).scalar_one_or_none()
    if existing:
        return existing

    alias = models.AppAlias(
        app_id=app_id,
        namespace=namespace,
        ident=ident,
        match_kind=match_kind,
    )
    db.add(alias)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # Alias was created concurrently; fetch it.
        alias = (await db.execute(alias_stmt)).scalar_one()
    return alias


async def _ensure_app_id(db: AsyncSession, base_name: str) -> str:
    """Generate a unique canonical app_id based on display name."""

    base_slug = _slugify(base_name)
    if not base_slug:
        base_slug = "app"

    # Try the base slug first then increment
    candidate = base_slug
    idx = 1
    while True:
        exists_stmt = sa.select(models.App.app_id).where(models.App.app_id == candidate)
        exists = (await db.execute(exists_stmt)).scalar_one_or_none()
        if exists is None:
            return candidate[:128]
        idx += 1
        candidate = f"{base_slug}-{idx}"


def _slugify(value: str) -> str:
    """Create a URL-safe identifier from the provided value."""

    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or ""


def _normalise_identifier(namespace: str, ident: str) -> str:
    ident = (ident or "").strip()
    if namespace in {"web", "android"}:
        return ident.lower()
    return ident


def _fallback_display_name(namespace: str, ident: str) -> str:
    ident = ident or "Unknown"
    if namespace == "web":
        core = ident.split("/")[0]
        if core.startswith("www."):
            core = core[4:]
        parts = core.split(".")
        if len(parts) > 1:
            core = parts[-2]
        return core.capitalize() or ident
    if namespace == "android":
        pkg_parts = ident.split(".")
        if pkg_parts:
            return pkg_parts[-1].replace("_", " ").title()
    return ident.title() if ident else "Unknown"


