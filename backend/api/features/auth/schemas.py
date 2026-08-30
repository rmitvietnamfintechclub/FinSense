from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Shape is fixed by docs/openapi.yaml /auth/login — access_token +
    token_type only. No refresh token: the contract defines no /auth/refresh,
    so an admin re-logs in after JWT_EXPIRE_HOURS."""

    access_token: str
    token_type: str = "bearer"


class CurrentAdmin(BaseModel):
    """The authenticated caller, decoded from the JWT. What audit endpoints
    stamp onto audit_log as admin_id / admin_name — which is why display_name
    rides in the token: the audit write must not need a second DB lookup to
    name the actor."""

    admin_id: str
    username: str
    display_name: str
