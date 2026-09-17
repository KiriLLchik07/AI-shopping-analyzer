import logging
from time import perf_counter

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.logging import (
    log_context,
    normalize_correlation_id,
)


logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        correlation_id = normalize_correlation_id(
            headers.get("X-Correlation-ID")
        )

        scope.setdefault("state", {})["correlation_id"] = correlation_id

        status_code = 500
        started_at = perf_counter()

        async def send_with_correlation_id(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]

                response_headers = MutableHeaders(scope=message)
                response_headers["X-Correlation-ID"] = correlation_id

            await send(message)

        with log_context(
            correlation_id=correlation_id,
            job_id="-",
            receipt_id="-",
            processing_version="-",
        ):
            logger.info(
                "HTTP request started method=%s",
                scope["method"],
            )

            try:
                await self.app(scope, receive, send_with_correlation_id)
            except Exception:
                logger.exception("Unhandled HTTP request error")
                raise
            finally:
                duration_ms = (perf_counter() - started_at) * 1000

                route = scope.get("route")
                route_path = getattr(route, "path", "<unmatched>")

                logger.info(
                    "HTTP request finished "
                    "method=%s route=%s status=%s duration_ms=%.2f",
                    scope["method"],
                    route_path,
                    status_code,
                    duration_ms,
                )
