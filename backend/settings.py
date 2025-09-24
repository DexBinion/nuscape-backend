from pathlib import Path
from typing import Optional
import os

# Attempt to ensure environment variables from the repository .env are loaded
# early so subprocesses (uvicorn reload children) see them during import time.
REPO_ROOT = Path(__file__).resolve().parent.parent  # .../NuScape Replit
_env_path = REPO_ROOT / ".env"

# Prefer python-dotenv if available, otherwise fall back to a simple parser.
try:
    from dotenv import load_dotenv

    # load_dotenv accepts a path-like object
    load_dotenv(dotenv_path=_env_path, override=False)
except Exception:
    if _env_path.exists():
        for raw_line in _env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            # do not overwrite existing environment variables
            if k and k not in os.environ:
                os.environ[k] = v

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pydantic v2 config: load .env from repo root (kept for developer ergonomics)
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379"
    require_redis: bool = False

    # JWT
    jwt_secret_key: str = "dev-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24 * 30

    # API
    api_base_path: str = "/api/v1"
    rate_limit_rps: int = 50

    # Queue
    queue_stream_name: str = "nuscape:events"
    queue_dlq_name: str = "nuscape:dlq"
    queue_consumer_group: str = "proc-1"
    queue_maxlen: int = 1_000_000


settings = Settings()

# Debug helper: print minimal info at import time so devs can see whether
# the repository .env was loaded into the process that imports backend.settings.
# We avoid printing the full DATABASE_URL to prevent leaking secrets into logs;
# instead print whether it is present and whether the .env file exists.
try:
    _dbg_db = os.environ.get("DATABASE_URL")
    print(
        f"[DEBUG settings] REPO_ROOT={REPO_ROOT}, .env_exists={_env_path.exists()}, DATABASE_URL_present={'yes' if _dbg_db else 'no'}"
    )
except Exception as _e:
    # Print an explicit debug line if anything goes wrong here.
    print(f"[DEBUG settings] error while checking DATABASE_URL: {_e}")