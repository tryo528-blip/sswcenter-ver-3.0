import copy

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.recipient import router as recipient_router
from app.api.staff import router as staff_router
from app.api.w1a_errors import install_w1a_error_contract
from app.api.w1c import router as w1c_router
from app.api.w1d import router as w1d_router
from app.api.w1e import router as w1e_router
from app.api.w2 import router as w2_router
from app.core.logging import configure_logging
from app.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    application = FastAPI(title="SSWCenter API", version=settings.app_version)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(staff_router)
    # FastAPI 0.139 stores included routers lazily.  Keep non-schema mirrors
    # directly discoverable for the existing API contract while leaving the
    # lazy router first for normal request handling and OpenAPI generation.
    if (
        application.router.routes
        and getattr(application.router.routes[-1], "original_router", None) is staff_router
    ):
        mirrors = []
        for route in staff_router.routes:
            mirror = copy.copy(route)
            mirror.include_in_schema = False
            if hasattr(mirror, "dependency_overrides_provider"):
                mirror.dependency_overrides_provider = application
            mirrors.append(mirror)
        application.router.routes.extend(mirrors)
    application.include_router(recipient_router)
    application.include_router(w1c_router)
    application.include_router(w1d_router)
    application.include_router(w1e_router)
    application.include_router(w2_router)
    install_w1a_error_contract(application)
    return application


app = create_app()
