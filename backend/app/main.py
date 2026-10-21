from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from backend.app.api.analytics import router as analytics_router
from backend.app.api.auth import router as auth_router
from backend.app.api.categories import router as category_router
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.health import router as health_router
from backend.app.api.llm import router as llm_router
from backend.app.api.processing_metrics import router as processing_metrics_router
from backend.app.api.receipts import router as receipts_router
from backend.app.core.config import cors_settings
from backend.app.core.logging import configure_logging, normalize_correlation_id
from backend.app.middleware.request_logging import RequestLoggingMiddleware

configure_logging()


app = FastAPI()

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(cors_settings.allow_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Correlation-ID"],
    expose_headers=["X-Correlation-ID", "Retry-After"],
)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(processing_metrics_router)
app.include_router(receipts_router)
app.include_router(category_router)
app.include_router(analytics_router)
app.include_router(llm_router)

register_exception_handlers(app)


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    error: Exception,
) -> PlainTextResponse:
    correlation_id = normalize_correlation_id(
        getattr(request.state, "correlation_id", None)
    )

    headers = {"X-Correlation-ID": correlation_id}
    # Unhandled errors are returned outside the application's middleware stack.
    origin = request.headers.get("origin")
    if origin in cors_settings.allow_origins:
        headers.update(
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Expose-Headers": "X-Correlation-ID, Retry-After",
                "Vary": "Origin",
            }
        )

    return PlainTextResponse(
        "Internal Server Error",
        status_code=500,
        headers=headers,
    )
