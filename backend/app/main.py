from fastapi import FastAPI
from backend.app.api.auth_login import router as auth_router
from backend.app.api.health import router as health_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(health_router)
