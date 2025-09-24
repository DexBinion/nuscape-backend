import os
from fastapi.testclient import TestClient

# Ensure the backend loads with a predictable database URL during tests
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")

from backend.main import app

client = TestClient(app)

def test_health_endpoint_returns_valid_payload():
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ok", "warning", "degraded"}
    assert "timestamp" in payload

    redis_info = payload["redis"]
    assert set(redis_info.keys()) >= {"connected", "client_type", "require_redis", "available_for_storage"}
    assert redis_info["client_type"] in {"redis", "mock", "none"}
