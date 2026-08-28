"""
backend/api/features/auth/jwt_handler.py

Pure token encode/decode. No DB, no FastAPI — so it is unit-testable without a
database and reusable by the audit guard, which must verify a token without
re-reading admin_users on every request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from backend.api.features.auth.schemas import CurrentAdmin
from backend.core.config import APISettings, api_settings


class InvalidTokenError(Exception):
    """Raised for every rejection reason — bad signature, expired, malformed,
    missing claim. The router maps this to a single 401 with one message: a
    caller who learns *why* a token failed learns whether a secret guess was
    close, so the reasons stay in the log, not in the response."""


def _require_secret(settings: APISettings) -> str:
    if not settings.JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is unset — refusing to sign or verify tokens. "
            "Set it in .env; there is no default because a shared default "
            "secret is a forgeable admin token."
        )
    return settings.JWT_SECRET_KEY


def create_access_token(
    admin: CurrentAdmin,
    settings: APISettings = api_settings,
    now: datetime | None = None,
) -> str:
    """`now` is injectable so expiry can be tested without sleeping."""
    issued_at = now or datetime.now(UTC)
    payload = {
        # 'sub' is the registered claim for subject; admin_id is the identity
        # audit_log denormalises, so that is what belongs in it.
        "sub": admin.admin_id,
        "username": admin.username,
        "display_name": admin.display_name,
        "iat": issued_at,
        "exp": issued_at + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _require_secret(settings), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(
    token: str, settings: APISettings = api_settings
) -> CurrentAdmin:
    try:
        payload = jwt.decode(
            token,
            _require_secret(settings),
            # A list, and never including 'none': passing the algorithm the
            # *token* names would let an attacker set alg=none and be believed.
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        return CurrentAdmin(
            admin_id=payload["sub"],
            username=payload["username"],
            display_name=payload["display_name"],
        )
    except KeyError as exc:
        # A token signed with our secret but missing our custom claims is still
        # unusable — an audit write needs display_name and cannot invent one.
        raise InvalidTokenError(f"token missing claim: {exc}") from exc
