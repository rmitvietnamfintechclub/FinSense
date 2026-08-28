"""
backend/api/tests/unit/test_jwt_handler.py

Token issuance/verification and credential checking for the admin audit panel.

Follows test_ticker.py's convention: no pytest-asyncio in this repo, so async
service functions are driven with asyncio.run() from plain sync tests. bcrypt
and PyJWT are exercised for real — mocking them would assert the mock.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from backend.api.features.auth.jwt_handler import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)
from backend.api.features.auth.schemas import CurrentAdmin
from backend.api.features.auth.service import (
    InvalidCredentialsError,
    authenticate_admin,
    hash_password,
    verify_password,
)
from backend.core.config import APISettings

ADMIN = CurrentAdmin(admin_id="adm_minh", username="minh", display_name="Minh Chen")


def settings(**overrides) -> APISettings:
    base = {"JWT_SECRET_KEY": "test-secret", "JWT_ALGORITHM": "HS256", "JWT_EXPIRE_HOURS": 8}
    return APISettings(**{**base, **overrides})


class FakeAdminCollection:
    def __init__(self, row: dict | None):
        self._row = row
        self.queries: list[dict] = []

    async def find_one(self, query: dict) -> dict | None:
        self.queries.append(query)
        if self._row is None:
            return None
        return self._row if self._row["username"] == query.get("username") else None


class FakeDb:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        assert name == "admin_users"
        return self._collection


def admin_row(password: str = "correct-horse", **overrides) -> dict:
    row = {
        "admin_id": "adm_minh",
        "username": "minh",
        "display_name": "Minh Chen",
        "password_hash": hash_password(password),
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    return {**row, **overrides}


# ============================================================
# jwt_handler
# ============================================================


class TestTokenRoundTrip:
    def test_decodes_back_to_the_same_admin(self):
        cfg = settings()
        decoded = decode_access_token(create_access_token(ADMIN, cfg), cfg)
        assert decoded == ADMIN

    def test_display_name_rides_in_the_token(self):
        """audit_log needs admin_name; if it were not a claim, every audit write
        would need a second admin_users read."""
        cfg = settings()
        payload = jwt.decode(
            create_access_token(ADMIN, cfg), "test-secret", algorithms=["HS256"]
        )
        assert payload["sub"] == "adm_minh"
        assert payload["display_name"] == "Minh Chen"

    def test_expired_token_is_rejected(self):
        cfg = settings(JWT_EXPIRE_HOURS=1)
        issued = datetime.now(UTC) - timedelta(hours=2)
        token = create_access_token(ADMIN, cfg, now=issued)
        with pytest.raises(InvalidTokenError):
            decode_access_token(token, cfg)

    def test_token_signed_with_another_secret_is_rejected(self):
        token = create_access_token(ADMIN, settings(JWT_SECRET_KEY="other-secret"))
        with pytest.raises(InvalidTokenError):
            decode_access_token(token, settings())

    def test_alg_none_token_is_rejected(self):
        """The classic JWT forgery: an unsigned token claiming alg=none. Rejected
        because decode passes an explicit algorithms list."""
        forged = jwt.encode({"sub": "adm_minh", "exp": 9999999999}, key="", algorithm="none")
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged, settings())

    def test_valid_signature_but_missing_custom_claims_is_rejected(self):
        token = jwt.encode(
            {"sub": "adm_minh", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "test-secret",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(token, settings())

    def test_garbage_string_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            decode_access_token("not-a-token", settings())

    def test_unset_secret_raises_rather_than_signing(self):
        """An empty secret must fail loudly — signing with '' would let anyone
        forge an admin token."""
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            create_access_token(ADMIN, settings(JWT_SECRET_KEY=""))


# ============================================================
# password hashing
# ============================================================


class TestPasswordHashing:
    def test_verify_accepts_the_original_and_rejects_others(self):
        digest = hash_password("correct-horse")
        assert verify_password("correct-horse", digest) is True
        assert verify_password("wrong-horse", digest) is False

    def test_hash_is_salted(self):
        assert hash_password("same") != hash_password("same")

    def test_password_over_72_bytes_is_refused_not_truncated(self):
        with pytest.raises(ValueError, match="truncate"):
            hash_password("a" * 73)

    def test_byte_length_not_char_length_is_the_limit(self):
        """Vietnamese text is multibyte — 30 chars can exceed bcrypt's 72 bytes."""
        with pytest.raises(ValueError):
            hash_password("đ" * 40)

    def test_malformed_stored_hash_fails_closed(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False


# ============================================================
# authenticate_admin
# ============================================================


class TestAuthenticateAdmin:
    def test_valid_credentials_return_the_admin(self):
        db = FakeDb(FakeAdminCollection(admin_row()))
        admin = asyncio.run(authenticate_admin(db, "minh", "correct-horse"))
        assert admin == ADMIN

    def test_username_lookup_is_case_insensitive(self):
        collection = FakeAdminCollection(admin_row())
        admin = asyncio.run(authenticate_admin(FakeDb(collection), "  MINH  ", "correct-horse"))
        assert admin.admin_id == "adm_minh"
        assert collection.queries == [{"username": "minh"}]

    def test_wrong_password_raises(self):
        db = FakeDb(FakeAdminCollection(admin_row()))
        with pytest.raises(InvalidCredentialsError):
            asyncio.run(authenticate_admin(db, "minh", "wrong"))

    def test_unknown_username_raises_the_same_error_message(self):
        """Identical message to the wrong-password case — a different one would
        tell an attacker which usernames exist."""
        known = FakeDb(FakeAdminCollection(admin_row()))
        unknown = FakeDb(FakeAdminCollection(None))

        with pytest.raises(InvalidCredentialsError) as wrong_password:
            asyncio.run(authenticate_admin(known, "minh", "wrong"))
        with pytest.raises(InvalidCredentialsError) as no_such_user:
            asyncio.run(authenticate_admin(unknown, "ghost", "wrong"))

        assert str(wrong_password.value) == str(no_such_user.value)

    def test_deactivated_admin_cannot_log_in(self):
        db = FakeDb(FakeAdminCollection(admin_row(is_active=False)))
        with pytest.raises(InvalidCredentialsError):
            asyncio.run(authenticate_admin(db, "minh", "correct-horse"))

    def test_unknown_user_still_performs_a_hash_comparison(self):
        """Guards the timing-attack defence: if the dummy hash were skipped, an
        unknown username would return far faster than a real one."""
        collection = FakeAdminCollection(None)
        with pytest.raises(InvalidCredentialsError):
            asyncio.run(authenticate_admin(FakeDb(collection), "ghost", "pw"))
        assert collection.queries == [{"username": "ghost"}]
