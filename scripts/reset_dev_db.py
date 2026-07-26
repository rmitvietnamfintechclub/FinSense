"""Wipe pipeline collections for local development. Never run against prod."""

import sys

from backend.core.config import database_settings
from backend.core.database import get_database

COLLECTIONS = ["articles", "event_clusters"]


def reset() -> None:
    db_name = database_settings.MONGODB_DB_NAME

    if "dev" not in db_name.lower() and "test" not in db_name.lower():
        sys.exit(f"Refusing to wipe '{db_name}' — name must contain 'dev' or 'test'.")

    confirm = input(f"Delete all documents in {COLLECTIONS} from '{db_name}'? [y/N] ")
    if confirm.lower() != "y":
        sys.exit("Aborted.")

    db = get_database()
    for name in COLLECTIONS:
        result = db[name].delete_many({})
        print(f"{name}: deleted {result.deleted_count}")


if __name__ == "__main__":
    reset()
