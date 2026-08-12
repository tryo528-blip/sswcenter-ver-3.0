from fastapi.testclient import TestClient

from app.core.settings import Settings, get_settings
from app.main import app


def test_health_live() -> None:
    client = TestClient(app)
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_reports_missing_database_configuration() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=None)
    try:
        client = TestClient(app)
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "database_not_configured",
    }
