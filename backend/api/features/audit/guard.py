"""
backend/api/features/audit/guard.py

The bearer-token dependency every audit endpoint depends on. Lives under
audit/ rather than auth/ because it is the audit domain's entry condition;
auth/ owns issuing tokens, this owns refusing requests without one.

Verification is signature-only — no admin_users read per request. That is the
tradeoff ADR-002 records for choosing JWT over a session store: a token stays
valid until it expires, so deactivating an admin takes effect within at most
JWT_EXPIRE_HOURS rather than instantly.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.api.features.auth.jwt_handler import (
    InvalidTokenError,
    decode_access_token,
)
from backend.api.features.auth.schemas import CurrentAdmin

logger = logging.getLogger(__name__)

# auto_error=False so a MISSING header reaches our handler and becomes a 401.
# HTTPBearer's own auto_error raises 403 for that case, which contradicts
# docs/openapi.yaml — every audit endpoint documents 401 for a missing JWT.
_bearer_scheme = HTTPBearer(auto_error=False)


def require_admin(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
) -> CurrentAdmin:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        # Reason is logged, never returned — see InvalidTokenError's docstring.
        logger.info("rejected admin token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


AdminDep = Annotated[CurrentAdmin, Depends(require_admin)]
