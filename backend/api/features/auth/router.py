from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.auth.jwt_handler import create_access_token
from backend.api.features.auth.schemas import LoginRequest, TokenResponse
from backend.api.features.auth.service import (
    InvalidCredentialsError,
    authenticate_admin,
)
from backend.core.database_async import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


def db_dep() -> AsyncIOMotorDatabase:
    return get_db()


DbDep = Annotated[AsyncIOMotorDatabase, Depends(db_dep)]


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbDep) -> TokenResponse:
    """JSON body, not OAuth2 form-encoded. docs/openapi.yaml declares an
    application/json body with {username, password}, and the contract is the
    source of truth — using FastAPI's OAuth2PasswordRequestForm here would
    silently change the wire format the frontend is generated against."""
    try:
        admin = await authenticate_admin(db, payload.username, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return TokenResponse(access_token=create_access_token(admin))
