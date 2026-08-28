# backend/core/schemas/admin_user.py
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdminUser(BaseModel):
    """A row of the `admin_users` collection.

    Deliberately includes password_hash: this is the DB-shape model, used by the
    seed script and by the login lookup. It is NEVER a response model — the auth
    router returns TokenResponse, and the guard returns CurrentAdmin, neither of
    which carries the hash.
    """

    admin_id: str = Field(min_length=1)
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    password_hash: str = Field(min_length=1)
    is_active: bool = True
    created_at: datetime
