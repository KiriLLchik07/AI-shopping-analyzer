from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.core.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ReceiptUploadUnavailableError,
    TooManyRequestsError,
    UploadTooLargeError,
)


def not_found_handler(
    _request: Request,
    error: NotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": error.detail},
    )


def authentication_handler(
    _request: Request,
    error: AuthenticationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": error.detail},
    )


def conflict_handler(
    _request: Request,
    error: ConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": error.detail},
    )


def business_rule_handler(
    _request: Request,
    error: BusinessRuleError,
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": error.detail},
    )


def too_many_requests_handler(
    _request: Request,
    error: TooManyRequestsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": error.detail},
        headers={"Retry-After": str(error.retry_after)},
    )


def upload_too_large_handler(
    _request: Request,
    error: UploadTooLargeError,
) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": error.detail},
    )


def receipt_upload_unavailable_handler(
    _request: Request,
    error: ReceiptUploadUnavailableError,
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": error.detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(AuthenticationError, authentication_handler)
    app.add_exception_handler(ConflictError, conflict_handler)
    app.add_exception_handler(BusinessRuleError, business_rule_handler)
    app.add_exception_handler(TooManyRequestsError, too_many_requests_handler)
    app.add_exception_handler(UploadTooLargeError, upload_too_large_handler)
    app.add_exception_handler(
        ReceiptUploadUnavailableError, receipt_upload_unavailable_handler
    )
