from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def init_db(mongodb_uri: str, db_name: str) -> None:
    global _client, _db
    _client = AsyncIOMotorClient(mongodb_uri)
    await _client.admin.command("ping")
    _db = _client[db_name]
    logger.info("MongoDB client initialised (db=%s)", db_name)


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _db


def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB client closed")
