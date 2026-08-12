from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.domains.recipient.errors import RecipientDomainError
from app.domains.staff.errors import StaffDomainError
from app.domains.staff.schemas import ErrorBody, ErrorEnvelope, ErrorField

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> UUID:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, UUID) else uuid4()


def _headers(request: Request) -> dict[str, str]:
    headers = {"X-Request-ID": str(_request_id(request))}
    if request.url.path.endswith("/sensitive-identity/reveal"):
        headers["Cache-Control"] = "no-store"
    return headers


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field_errors: list[dict[str, str]] | None = None,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(code=code, message=message),
        field_errors=[ErrorField.model_validate(item) for item in field_errors or []],
        details=details or {},
        request_id=str(_request_id(request)),
    )
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(envelope.model_dump(by_alias=True)),
        headers=_headers(request),
    )


def install_w1a_error_contract(application: FastAPI) -> None:
    @application.middleware("http")
    async def assign_request_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        supplied = request.headers.get("X-Request-ID")
        try:
            request.state.request_id = UUID(supplied) if supplied else uuid4()
        except ValueError:
            request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        if request.url.path.endswith("/sensitive-identity/reveal"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(StaffDomainError)
    async def staff_domain_error_handler(
        request: Request,
        exc: StaffDomainError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            field_errors=exc.field_errors,
            details=exc.details,
        )

    @application.exception_handler(RecipientDomainError)
    async def recipient_domain_error_handler(
        request: Request,
        exc: RecipientDomainError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            field_errors=exc.field_errors,
            details=exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> Response:
        if not request.url.path.startswith("/api/v1/"):
            return await request_validation_exception_handler(request, exc)
        fields = []
        for item in exc.errors():
            error_type = item.get("type")
            raw_location = tuple(item.get("loc", ()))
            if error_type == "extra_forbidden" and raw_location:
                raw_location = raw_location[:-1]
            location = [str(part) for part in raw_location if part not in {"body"}]
            field = ".".join(location)
            if error_type == "extra_forbidden" and not field:
                field = "body"
            fields.append(
                {
                    "field": field,
                    "message": "입력값을 확인하세요.",
                }
            )
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="입력값을 확인하세요.",
            field_errors=fields,
        )

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> Response:
        if not request.url.path.startswith("/api/v1/"):
            return await http_exception_handler(request, exc)
        detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
        raw_code = str(detail.get("code", "HTTP_ERROR"))
        code = raw_code.upper()
        messages = {
            "PERMISSION_REQUIRED": "이 작업을 수행할 권한이 없습니다.",
            "SESSION_REQUIRED": "로그인이 필요합니다.",
            "INVALID_SESSION": "로그인이 필요합니다.",
            "CSRF_REQUIRED": "요청 검증에 실패했습니다.",
            "CSRF_INVALID": "요청 검증에 실패했습니다.",
        }
        message = messages.get(code, "요청을 처리할 수 없습니다.")
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details={key: value for key, value in detail.items() if key not in {"code", "message"}},
        )

    @application.exception_handler(Exception)
    async def unexpected_api_error_handler(request: Request, exc: Exception) -> JSONResponse:
        if not request.url.path.startswith("/api/v1/"):
            raise exc
        del exc
        logger.error("unexpected API error request_id=%s", _request_id(request))
        return _error_response(
            request,
            status_code=500,
            code="UNEXPECTED_SERVER_ERROR",
            message="요청을 처리하지 못했습니다.",
        )
