"""
scripts/seed_admins.py

The ONLY writer of the `admin_users` collection. There is no signup endpoint and
no password-reset endpoint — the audit panel is internal to the dev team, so
accounts are provisioned here and nowhere else.

    python scripts/seed_admins.py --admin-id adm_minh --username minh --display-name "Minh Chen"

The password is read from stdin (getpass), never from an argv flag: argv lands in
shell history and in `ps` output for every user on the box.

Re-running for an existing admin_id updates the password and display name in
place. It never deletes a row — audit_log entries denormalise admin_id and must
keep resolving. Use --deactivate to revoke access instead.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, datetime

import certifi
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from backend.api.features.auth.service import hash_password
from backend.core.config import database_settings
from backend.core.log import setup_logging
from backend.core.schemas.admin_user import AdminUser

COLLECTION = "admin_users"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision an audit-panel admin.")
    parser.add_argument("--admin-id", required=True, help="Stable id, e.g. 'adm_minh'")
    parser.add_argument("--username", required=True, help="Login handle (stored lowercased)")
    parser.add_argument("--display-name", help="Shown in audit_log; defaults to the username")
    parser.add_argument(
        "--deactivate",
        action="store_true",
        help="Revoke this admin's access without deleting the row (keeps audit_log resolvable)",
    )
    return parser.parse_args()


def _read_password() -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match — nothing written.")
    if not password:
        sys.exit("Empty password refused.")
    return password


def main() -> None:
    logger = setup_logging()
    args = _parse_args()
    username = args.username.strip().lower()

    client = MongoClient(database_settings.MONGODB_URI, tlsCAFile=certifi.where())
    collection = client[database_settings.MONGODB_DB_NAME][COLLECTION]

    if args.deactivate:
        result = collection.update_one(
            {"admin_id": args.admin_id}, {"$set": {"is_active": False}}
        )
        if result.matched_count == 0:
            sys.exit(f"No admin with admin_id={args.admin_id!r}.")
        logger.info("Deactivated admin_id=%s", args.admin_id)
        client.close()
        return

    password_hash = hash_password(_read_password())

    # Validate the whole row through the shared model before touching Mongo, so
    # a blank display_name or admin_id fails here rather than becoming a row the
    # API later reads and rejects at login time.
    admin = AdminUser(
        admin_id=args.admin_id,
        username=username,
        display_name=args.display_name or username,
        password_hash=password_hash,
        is_active=True,
        created_at=datetime.now(UTC),
    )

    # created_at is $setOnInsert so re-seeding an existing admin to rotate a
    # password does not rewrite when the account was provisioned.
    # The filter is admin_id but username carries its own unique index, so a
    # username already held by a DIFFERENT admin_id is a DuplicateKeyError, not
    # an update. Surface it as an instruction rather than a traceback.
    try:
        collection.update_one(
            {"admin_id": args.admin_id},
            {
                "$set": {
                    "username": admin.username,
                    "display_name": admin.display_name,
                    "password_hash": admin.password_hash,
                    "is_active": admin.is_active,
                },
                "$setOnInsert": {
                    "admin_id": admin.admin_id,
                    "created_at": admin.created_at,
                },
            },
            upsert=True,
        )
    except DuplicateKeyError:
        sys.exit(
            f"Username {username!r} already belongs to a different admin_id. "
            "Pick another username, or re-run with that admin's --admin-id to "
            "rotate their password."
        )
    logger.info("Seeded admin_id=%s username=%s", args.admin_id, username)
    client.close()


if __name__ == "__main__":
    main()
