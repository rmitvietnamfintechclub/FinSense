"""
backend/api/tests/unit/test_guard.py

The bearer guard audit endpoints depend on, plus the POST /auth/login route.
Wired through TestClient against a throwaway FastAPI app so dependency
overrides stand in for the database — same pattern as test_ticker.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.features.audit.guard import AdminDep, require_admin
from backend.api.features.auth.jwt_handler import create_access_token
from backend.api.features.auth.router import db_dep, router
from backend.api.features.auth.schemas import CurrentAdmin
from backend.api.features.auth.service import hash_password
from backend.core.config import api_settings

from .test_jwt_handler import ADMIN, FakeAdminCollection, FakeDb, admin_row

REPO_ROOT = Path(__file__).resolve().parents[4]
OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.yaml"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    """The real api_settings singleton is what the router and guard read, and it
    has no default secret — set one for the duration of each test."""
    monkeypatch.setattr(api_settings, "JWT_SECRET_KEY", "test-secret")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)

    @app.get("/api/audit/probe")
    def probe(admin: AdminDep) -> dict:
        return {"admin_id": admin.admin_id, "display_name": admin.display_name}

    app.dependency_overrides[db_dep] = lambda: FakeDb(FakeAdminCollection(admin_row()))
    return TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# POST /auth/login
# ============================================================


class TestLoginRoute:
    def test_valid_login_returns_a_bearer_token(self, client):
        response = client.post(
            "/api/auth/login", json={"username": "minh", "password": "correct-horse"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    def test_token_from_login_opens_a_guarded_route(self, client):
        token = client.post(
            "/api/auth/login", json={"username": "minh", "password": "correct-horse"}
        ).json()["access_token"]

        response = client.get("/api/audit/probe", headers=bearer(token))
        assert response.status_code == 200
        assert response.json() == {"admin_id": "adm_minh", "display_name": "Minh Chen"}

    def test_wrong_password_is_401_not_403(self, client):
        response = client.post(
            "/api/auth/login", json={"username": "minh", "password": "nope"}
        )
        assert response.status_code == 401

    def test_login_response_never_leaks_the_password_hash(self, client):
        response = client.post(
            "/api/auth/login", json={"username": "minh", "password": "correct-horse"}
        )
        assert "password_hash" not in response.text
        assert "$2b$" not in response.text

    def test_missing_field_is_422(self, client):
        assert client.post("/api/auth/login", json={"username": "minh"}).status_code == 422


# ============================================================
# require_admin
# ============================================================


class TestRequireAdmin:
    def test_missing_header_is_401(self, client):
        """HTTPBearer's own auto_error would make this a 403, contradicting
        openapi.yaml, which documents 401 on every audit endpoint."""
        response = client.get("/api/audit/probe")
        assert response.status_code == 401

    def test_malformed_token_is_401(self, client):
        assert client.get("/api/audit/probe", headers=bearer("garbage")).status_code == 401

    def test_expired_token_is_401(self, client):
        token = create_access_token(
            ADMIN, api_settings, now=datetime.now(UTC) - timedelta(hours=99)
        )
        assert client.get("/api/audit/probe", headers=bearer(token)).status_code == 401

    def test_rejection_body_does_not_reveal_why(self, client):
        """Expired and forged must be indistinguishable to the caller."""
        expired = create_access_token(
            ADMIN, api_settings, now=datetime.now(UTC) - timedelta(hours=99)
        )
        forged = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1faGFjayJ9.bad"
        assert (
            client.get("/api/audit/probe", headers=bearer(expired)).json()
            == client.get("/api/audit/probe", headers=bearer(forged)).json()
        )

    def test_non_bearer_scheme_is_401(self, client):
        response = client.get(
            "/api/audit/probe", headers={"Authorization": "Basic bWluaDpwdw=="}
        )
        assert response.status_code == 401

    def test_guard_returns_the_admin_identity_audit_log_needs(self):
        token = create_access_token(ADMIN, api_settings)
        from fastapi.security import HTTPAuthorizationCredentials

        admin = require_admin(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )
        assert isinstance(admin, CurrentAdmin)
        assert (admin.admin_id, admin.display_name) == ("adm_minh", "Minh Chen")


# ============================================================
# contract
# ============================================================


class TestOpenApiContract:
    def test_login_route_matches_the_documented_contract(self, client):
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        documented = spec["paths"]["/auth/login"]["post"]

        body_schema = documented["requestBody"]["content"]["application/json"]["schema"]
        assert set(body_schema["required"]) == {"username", "password"}

        token_schema = documented["responses"]["200"]["content"]["application/json"]["schema"]
        response = client.post(
            "/api/auth/login", json={"username": "minh", "password": "correct-horse"}
        )
        assert set(response.json()) == set(token_schema["properties"])

    def test_hash_password_produces_a_bcrypt_hash(self):
        assert hash_password("pw").startswith("$2b$")
