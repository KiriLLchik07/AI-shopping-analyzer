from fastapi import FastAPI

from backend.app.api.auth import router as auth_router
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.health import router as health_router
from backend.app.api.receipts import router as receipts_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(receipts_router)

register_exception_handlers(app)
