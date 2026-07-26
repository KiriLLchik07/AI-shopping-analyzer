from fastapi import FastAPI
from backend.app.api.auth_login import router as auth_router

app = FastAPI()
app.include_router(auth_router)
