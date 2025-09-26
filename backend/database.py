from typing import Optional
import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from backend.settings import settings
from urllib.parse import urlparse, urlunparse, parse_qs
import os

logger = logging.getLogger(__name__)

# Read database URL from settings (may be None during import-time in some reload scenarios)
DATABASE_URL = settings.database_url or os.environ.get("DATABASE_URL")

# Defer engine/session creation until init_engine() is called to avoid raising at import time.
# Uvicorn's --reload spawns child processes which may import modules before the environment
# is fully populated; raising during import time causes noisy reloader errors.
engine = None  # type: Optional[object]
AsyncSessionLocal: Optional[async_sessionmaker] = None

Base = declarative_base()

def _normalize_db_url(raw_url: str) -> (str, dict):
    """Normalize a raw DATABASE_URL for SQLAlchemy + asyncpg and extract connect_args."""
    _parsed = urlparse(raw_url)
    _query = parse_qs(_parsed.query or "")
    _use_ssl = False
    if "sslmode" in _query:
        sslmode_val = _query.get("sslmode", [""])[0].lower()
        # treat any non-disable value as requiring SSL
        if sslmode_val and sslmode_val != "disable":
            _use_ssl = True

    # Ensure asyncpg scheme
    _scheme = _parsed.scheme
    if _scheme in ("postgres", "postgresql"):
        _scheme = "postgresql+asyncpg"

    _clean_parsed = _parsed._replace(scheme=_scheme, query="")
    CLEAN_DATABASE_URL = urlunparse(_clean_parsed)
    _connect_args = {"ssl": "require"} if _use_ssl else {}
    return CLEAN_DATABASE_URL, _connect_args

def init_engine(database_url: Optional[str] = None):
    """
    Initialize the async engine and session factory.
    Call this early in application startup (e.g., in FastAPI startup event)
    to create the database engine. This avoids import-time errors when
    environment variables are not yet available.
    """
    global engine, AsyncSessionLocal, DATABASE_URL

    DATABASE_URL = database_url or DATABASE_URL or settings.database_url
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is required to initialize the database engine")

    CLEAN_DATABASE_URL, _connect_args = _normalize_db_url(DATABASE_URL)

    # Async engine/session configuration - tune pool settings as needed
    _connect_kwargs = {
        "echo": False,
        "future": True,
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
    }

    # Explicitly assign to globals to avoid creating local variables
    if _connect_args:
        engine = create_async_engine(CLEAN_DATABASE_URL, connect_args=_connect_args, **_connect_kwargs)
    else:
        engine = create_async_engine(CLEAN_DATABASE_URL, **_connect_kwargs)

    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    logger.info(f"Database engine initialized: {type(engine)} with driver {getattr(engine.dialect, 'driver', None)}")

async def get_db():
    """
    FastAPI dependency that yields an async DB session.
    init_engine() must have been called before this is used.
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Database engine is not initialized. Call init_engine() during application startup.")
    async with AsyncSessionLocal() as session:
        yield session
