from __future__ import annotations

from fastapi import FastAPI

from backend.api.features.ticker.router import router as ticker_router

app = FastAPI(title="Fin-Sense API")

app.include_router(ticker_router)

# from backend.api.features.dashboard.router import router as dashboard_router
# from backend.api.features.events.router import router as events_router
# from backend.api.features.history.router import router as history_router
# from backend.api.features.audit.router import router as audit_router
# from backend.api.features.auth.router import router as auth_router
# from backend.api.features.internal.router import router as internal_router
# app.include_router(dashboard_router)
# app.include_router(events_router)
# app.include_router(history_router)
# app.include_router(audit_router)
# app.include_router(auth_router)
# app.include_router(internal_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}