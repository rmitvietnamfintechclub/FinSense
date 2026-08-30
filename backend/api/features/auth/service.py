"""
backend/api/features/auth/service.py

Credential verification against the `admin_users` collection. The collection is
read-only from the API's side — the sole writer is scripts/seed_admins.py.
"""

from __future__ import annotations

import logging

import bcrypt
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.auth.schemas import CurrentAdmin
from backend.core.config import APISettings, api_settings

logger = logging.getLogger(__name__)

ADMIN_USERS_COLLECTION = "admin_users"

# Verified against a real bcrypt hash of a value no one can log in with, so a
# request for an unknown username costs the same ~100ms as a wrong password for
# a real one. Without this, response time alone enumerates valid usernames.
_DUMMY_HASH = bcrypt.hashpw(b"finsense-nonexistent-account", bcrypt.gensalt())


class InvalidCredentialsError(Exception):
    """One exception for 'no such user', 'wrong password', and 'deactivated'.
    The router turns all three into the same 401 with the same message —
    distinguishing them tells an attacker which half of the pair was right."""


def hash_password(password: str, settings: APISettings = api_settings) -> str:
    """Used by the seed script, and here so hashing and verification cannot
    drift apart into two different cost factors."""
    encoded = password.encode("utf-8")
    if len(encoded) > settings.MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password exceeds {settings.MAX_PASSWORD_BYTES} bytes; bcrypt would "
            "silently truncate it, making the discarded tail meaningless."
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(
    password: str, password_hash: str, settings: APISettings = api_settings
) -> bool:
    encoded = password.encode("utf-8")
    # Over-long input is rejected rather than truncated — see hash_password.
    # Reads the injected settings, not the global, so an overridden limit cannot
    # make hashing and verification disagree about the boundary.
    if len(encoded) > settings.MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        # A malformed stored hash (hand-edited row, wrong column) must fail
        # closed as a rejected login, not 500 the endpoint.
        logger.warning("admin_users row has an unparseable password_hash")
        return False


async def authenticate_admin(
    db: AsyncIOMotorDatabase, username: str, password: str
) -> CurrentAdmin:
    """Raises InvalidCredentialsError on every failure path."""
    # Usernames are stored lowercased by the seed script; normalising here too
    # means 'Minh' and 'minh' are one account, not a silent login failure.
    lookup = username.strip().lower()
    row = await db[ADMIN_USERS_COLLECTION].find_one({"username": lookup})

    # Hash a dummy when the user is unknown so the timing is indistinguishable,
    # then fail — never skip straight to the exception.
    stored_hash = (row or {}).get("password_hash") or _DUMMY_HASH.decode("utf-8")
    password_ok = verify_password(password, stored_hash)

    if row is None or not password_ok:
        logger.info("failed admin login attempt for username=%r", lookup)
        raise InvalidCredentialsError("Incorrect username or password")

    if not row.get("is_active", True):
        # Deactivation is how an admin is removed: audit_log entries referencing
        # this admin_id must keep resolving, so the row is never deleted.
        logger.info("login attempt on deactivated admin username=%r", lookup)
        raise InvalidCredentialsError("Incorrect username or password")

    return CurrentAdmin(
        admin_id=row["admin_id"],
        username=row["username"],
        display_name=row["display_name"],
    )
