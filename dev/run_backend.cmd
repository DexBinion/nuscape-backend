@echo off
REM Run backend from repository root, activate local venv, load .env via python-dotenv, then start uvicorn

REM Change directory to the repo root (script is located in dev\ so go up one level)
cd /d "%~dp0\.."

REM Activate venv if present
if exist ".venv\Scripts\activate.bat" (
  call .\.venv\Scripts\activate.bat
) else (
  echo WARNING: Virtual environment not found at .venv. Create it with: python -m venv .venv
)

REM Ensure python-dotenv is available in the venv (safe no-op if already installed)
python -m pip install --upgrade pip setuptools wheel
python -m pip install python-dotenv

REM Start uvicorn while loading environment from .env
python -c "import os, sys
try:
    # Try to load dotenv if available
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.getcwd(), '.env'), override=False)
except Exception:
    # If python-dotenv isn't available, fall back to manual parsing
    env_path = os.path.join(os.getcwd(), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('\"').strip(\"'\")
                if k and k not in os.environ:
                    os.environ[k] = v
# Exec uvicorn in this process so child reloads inherit the same environment
os.execvp(sys.executable, [sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '5001', '--reload'])"
