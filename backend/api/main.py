from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.features.audit.router import router as audit_router
from backend.api.features.auth.jwt_handler import verify_secret_configured
from backend.api.features.auth.router import router as auth_router
from backend.api.features.dashboard.router import router as dashboard_router
from backend.api.features.ticker.router import (
    directory_router as ticker_directory_router,
)
from backend.api.features.ticker.router import router as ticker_router
from backend.core.config import api_settings, database_settings
from backend.core.database_async import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before the DB, so a misconfigured deploy dies on boot rather than
    # serving every endpoint happily and 500ing on the first login.
    verify_secret_configured()
    await init_db(database_settings.MONGODB_URI, database_settings.MONGODB_DB_NAME)
    yield
    close_db()


app = FastAPI(title="Fin-Sense API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=api_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(dashboard_router)
app.include_router(ticker_router)
app.include_router(ticker_directory_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
