from __future__ import annotations

from typing import List, Dict

APP_SEEDS: List[Dict[str, object]] = [
    {
        "app_id": "youtube",
        "display_name": "YouTube",
        "category": "video",
        "icon_url": "https://cdn.simpleicons.org/youtube/ff0000",
        "aliases": [
            {"namespace": "web", "ident": "youtube.com"},
            {"namespace": "android", "ident": "com.google.android.youtube"},
            {"namespace": "windows", "ident": "youtube.exe"},
        ],
    },
    {
        "app_id": "google-chrome",
        "display_name": "Google Chrome",
        "category": "productivity",
        "icon_url": "https://cdn.simpleicons.org/googlechrome/4c8bf5",
        "aliases": [
            {"namespace": "windows", "ident": "chrome.exe"},
            {"namespace": "web", "ident": "chrome.google.com"},
            {"namespace": "android", "ident": "com.android.chrome"},
        ],
    },
    {
        "app_id": "instagram",
        "display_name": "Instagram",
        "category": "social",
        "icon_url": "https://cdn.simpleicons.org/instagram/E4405F",
        "aliases": [
            {"namespace": "web", "ident": "instagram.com"},
            {"namespace": "android", "ident": "com.instagram.android"},
        ],
    },
    {
        "app_id": "tiktok",
        "display_name": "TikTok",
        "category": "social",
        "icon_url": "https://cdn.simpleicons.org/tiktok/000000",
        "aliases": [
            {"namespace": "web", "ident": "tiktok.com"},
            {"namespace": "android", "ident": "com.zhiliaoapp.musically"},
        ],
    },
    {
        "app_id": "spotify",
        "display_name": "Spotify",
        "category": "other",
        "icon_url": "https://cdn.simpleicons.org/spotify/1DB954",
        "aliases": [
            {"namespace": "web", "ident": "open.spotify.com"},
            {"namespace": "windows", "ident": "spotify.exe"},
            {"namespace": "android", "ident": "com.spotify.music"},
        ],
    },
    {
        "app_id": "steam",
        "display_name": "Steam",
        "category": "gaming",
        "icon_url": "https://cdn.simpleicons.org/steam/1b2838",
        "aliases": [
            {"namespace": "windows", "ident": "steam.exe"},
        ],
    },
    {
        "app_id": "netflix",
        "display_name": "Netflix",
        "category": "video",
        "icon_url": "https://cdn.simpleicons.org/netflix/E50914",
        "aliases": [
            {"namespace": "web", "ident": "netflix.com"},
            {"namespace": "windows", "ident": "netflix.exe"},
            {"namespace": "android", "ident": "com.netflix.mediaclient"},
        ],
    },
]
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import App
from backend.app_directory import add_alias


async def load_app_seeds(db: AsyncSession) -> None:
    """Upsert canonical app seeds into the directory."""
    for seed in APP_SEEDS:
        app = await db.get(App, seed["app_id"])
        if app is None:
            app = App(
                app_id=seed["app_id"],
                display_name=seed["display_name"],
                category=seed.get("category"),
                icon_url=seed.get("icon_url"),
                icon_b64=None,
            )
            db.add(app)
            await db.flush()
        else:
            updated = False
            if not app.icon_url and seed.get("icon_url"):
                app.icon_url = seed["icon_url"]
                updated = True
            if seed.get("category") and app.category != seed["category"]:
                app.category = seed["category"]
                updated = True
            if updated:
                await db.flush()

        for alias in seed.get("aliases", []):
            await add_alias(
                db,
                app_id=app.app_id,
                namespace=alias["namespace"],
                ident=alias["ident"],
            )

    await db.commit()


