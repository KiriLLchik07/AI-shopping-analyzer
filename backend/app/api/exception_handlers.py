from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.core.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    LlmReportInputError,
    LlmReportStorageUnavailableError,
    NotFoundError,
    ReceiptDeletionUnavailableError,
    ReceiptImageUnavailableError,
    ReceiptUploadUnavailableError,
    TooManyRequestsError,
    UploadTooLargeError,
)
from backend.app.llm.exceptions import (
    LlmProviderError,
    LlmResponseValidationError,
    LlmTimeoutError,
    NoConfirmedPurchasesError,
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


def receipt_image_unavailable_handler(
    _request: Request,
    error: ReceiptImageUnavailableError,
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": error.detail},
        headers={"Cache-Control": "no-store"},
    )


def receipt_deletion_unavailable_handler(
    _request: Request, error: ReceiptDeletionUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": error.detail})


def llm_provider_handler(_request: Request, error: LlmProviderError) -> JSONResponse:
    if isinstance(error, LlmTimeoutError):
        status = 504
    elif isinstance(error, LlmResponseValidationError):
        status = 502
    else:
        status = 503
    return JSONResponse(
        status_code=status,
        content={"detail": type(error).message, "code": error.code},
        headers={"Cache-Control": "no-store"},
    )


def llm_no_purchases_handler(
    _request: Request, _error: NoConfirmedPurchasesError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "detail": "За выбранный месяц нет подтверждённых покупок.",
            "code": "llm_no_confirmed_purchases",
        },
        headers={"Cache-Control": "no-store"},
    )


def llm_input_handler(_request: Request, _error: LlmReportInputError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": LlmReportInputError.default_detail,
            "code": "llm_invalid_input",
        },
        headers={"Cache-Control": "no-store"},
    )


def llm_storage_handler(
    _request: Request, _error: LlmReportStorageUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": LlmReportStorageUnavailableError.default_detail,
            "code": "llm_storage_unavailable",
        },
        headers={"Cache-Control": "no-store"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LlmProviderError, llm_provider_handler)
    app.add_exception_handler(NoConfirmedPurchasesError, llm_no_purchases_handler)
    app.add_exception_handler(LlmReportInputError, llm_input_handler)
    app.add_exception_handler(LlmReportStorageUnavailableError, llm_storage_handler)
    app.add_exception_handler(
        ReceiptDeletionUnavailableError, receipt_deletion_unavailable_handler
    )
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(AuthenticationError, authentication_handler)
    app.add_exception_handler(ConflictError, conflict_handler)
    app.add_exception_handler(BusinessRuleError, business_rule_handler)
    app.add_exception_handler(TooManyRequestsError, too_many_requests_handler)
    app.add_exception_handler(UploadTooLargeError, upload_too_large_handler)
    app.add_exception_handler(
        ReceiptUploadUnavailableError, receipt_upload_unavailable_handler
    )
    app.add_exception_handler(
        ReceiptImageUnavailableError,
        receipt_image_unavailable_handler,
    )
