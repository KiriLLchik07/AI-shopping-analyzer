from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from backend.app.api.auth import router as auth_router
from backend.app.api.categories import router as category_router
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.health import router as health_router
from backend.app.api.receipts import router as receipts_router
from backend.app.core.logging import configure_logging, normalize_correlation_id
from backend.app.middleware.request_logging import RequestLoggingMiddleware

configure_logging()


app = FastAPI()

app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(receipts_router)
app.include_router(category_router)

register_exception_handlers(app)

@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    error: Exception,
) -> PlainTextResponse:
    correlation_id = normalize_correlation_id(
        getattr(request.state, "correlation_id", None)
    )

    return PlainTextResponse(
        "Internal Server Error",
        status_code=500,
        headers={"X-Correlation-ID": correlation_id},
    )
