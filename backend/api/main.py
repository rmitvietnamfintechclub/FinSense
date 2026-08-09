from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.features.ticker.router import router as ticker_router
from backend.core.config import database_settings
from backend.core.database_async import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(database_settings.MONGODB_URI, database_settings.MONGODB_DB_NAME)
    yield
    close_db()

app = FastAPI(title="Fin-Sense API", lifespan=lifespan)

app.include_router(ticker_router)

from backend.api.features.dashboard.router import router as dashboard_router

# from backend.api.features.events.router import router as events_router
# from backend.api.features.history.router import router as history_router
# from backend.api.features.audit.router import router as audit_router
# from backend.api.features.auth.router import router as auth_router
# from backend.api.features.internal.router import router as internal_router
app.include_router(dashboard_router)
# app.include_router(events_router)
# app.include_router(history_router)
# app.include_router(audit_router)
# app.include_router(auth_router)
# app.include_router(internal_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}