"""Shared MongoDB connection — single client per process, used by both the API and the pipeline."""
from __future__ import annotations

from functools import lru_cache

import certifi
from pymongo import MongoClient
from pymongo.database import Database

from backend.core.config import database_settings


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    if not database_settings.MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not set")
    return MongoClient(database_settings.MONGODB_URI, tlsCAFile=certifi.where())


def get_database() -> Database:
    return get_client()[database_settings.MONGODB_DB_NAME]
