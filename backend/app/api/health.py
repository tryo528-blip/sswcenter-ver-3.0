from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.settings import Settings, get_settings
from app.db.session import application_is_ready

router = APIRouter(prefix="/health", tags=["health"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def health_ready(
    response: Response,
    settings: SettingsDependency,
) -> dict[str, str]:
    ready, reason = application_is_ready(settings)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": reason or "database_unavailable"}

    return {"status": "ok"}
