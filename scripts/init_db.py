"""
FIN-SENSE 2.0 - MongoDB initialization script.

Creates collections, indexes, and seeds static_ontology + concept_dictionary.
Usage: MONGODB_URI=... python scripts/init_db.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import certifi
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import CollectionInvalid

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.config import database_settings
from backend.core.enums import Concept, Ticker

MONGO_URI = database_settings.MONGODB_URI
DB_NAME = database_settings.MONGODB_DB_NAME
STATIC_ONTOLOGY_PATH = REPO_ROOT / "backend" / "pipeline" / "lexicon" / "static_ontology.json"

client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[DB_NAME]


def create_collection(name: str):
    try:
        db.create_collection(name)
        print(f"  Created: {name}")
    except CollectionInvalid:
        print(f"  Already exists (skipped): {name}")


def setup_collections():
    print("Creating collections...")
    for name in [
        "articles",
        "event_clusters",
        "daily_sentiment_history",
        "static_ontology",
        "concept_dictionary",
        "audit_log",
        "frozen_test_set",
    ]:
        create_collection(name)


def setup_indexes():
    print("\nCreating indexes...")

    db.articles.create_index("url", unique=True, name="url_unique")
    db.articles.create_index("cluster_id", name="cluster_id")
    print("  articles: done")

    db.event_clusters.create_index("cluster_id", unique=True, name="cluster_id_unique")
    db.event_clusters.create_index([("created_at", DESCENDING)], name="created_at_desc")
    db.event_clusters.create_index(
        "aggregated_analysis.ticker_sentiments.ticker", name="ticker_idx"
    )
    db.event_clusters.create_index(
        "aggregated_analysis.concept_sentiments.concept", name="concept_idx"
    )
    print("  event_clusters: done")

    db.daily_sentiment_history.create_index(
        [("ticker", ASCENDING), ("date", DESCENDING)],
        unique=True,
        name="ticker_date_unique",
    )
    db.daily_sentiment_history.create_index("ticker", name="ticker")
    print("  daily_sentiment_history: done")

    db.static_ontology.create_index("ticker", unique=True, name="ticker_unique")
    print("  static_ontology: done")

    db.concept_dictionary.create_index("concept", unique=True, name="concept_unique")
    db.concept_dictionary.create_index("aliases", name="aliases_multikey")
    print("  concept_dictionary: done")

    db.audit_log.create_index("cluster_id", name="cluster_id")
    db.audit_log.create_index([("performed_at", DESCENDING)], name="performed_at_desc")
    db.audit_log.create_index("error_type", name="error_type")
    print("  audit_log: done")

    db.frozen_test_set.create_index("article_id", unique=True, name="article_id_unique")
    print("  frozen_test_set: done")


def validate_static_ontology(ontology: dict[str, list[dict[str, object]]]) -> None:
    expected_tickers = {ticker.value for ticker in Ticker}
    allowed_concepts = {concept.value for concept in Concept}
    actual_tickers = set(ontology)

    missing_tickers = expected_tickers - actual_tickers
    extra_tickers = actual_tickers - expected_tickers
    if missing_tickers or extra_tickers:
        raise ValueError(
            "static_ontology ticker mismatch. "
            f"Missing: {sorted(missing_tickers)}. Extra: {sorted(extra_tickers)}."
        )

    for ticker, concept_weights in sorted(ontology.items()):
        if not isinstance(concept_weights, list) or not concept_weights:
            raise ValueError(f"{ticker} must map to a non-empty list")

        seen_concepts = set()
        for item in concept_weights:
            concept = item.get("concept")
            weight = item.get("weight")

            if concept not in allowed_concepts:
                raise ValueError(f"{ticker} uses invalid concept: {concept}")
            if concept in seen_concepts:
                raise ValueError(f"{ticker} has duplicate concept: {concept}")
            if not isinstance(weight, float) or not 0.0 <= weight <= 1.0:
                raise ValueError(f"{ticker}/{concept} weight must be a float in [0, 1]")

            seen_concepts.add(concept)


def seed_static_ontology():
    """
    Ticker -> concept weight map for S_final calculation.
    Seed data is loaded from backend/pipeline/lexicon/static_ontology.json.
    """
    print("\nSeeding static_ontology...")

    with STATIC_ONTOLOGY_PATH.open(encoding="utf-8") as ontology_file:
        ontology = json.load(ontology_file)

    validate_static_ontology(ontology)
    now = datetime.now(timezone.utc)

    for ticker, concept_weights in sorted(ontology.items()):
        db.static_ontology.update_one(
            {"ticker": ticker},
            {
                "$set": {
                    "ticker": ticker,
                    "concept_weights": concept_weights,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        print(f"  Seeded: {ticker}")

    print("  static_ontology: seeded from JSON with idempotent upserts")


def seed_concept_dictionary():
    """
    Alias resolution map: model output strings -> canonical concept enum values.
    """
    print("\nSeeding concept_dictionary...")

    concepts = [
        {
            "concept": "BANKING",
            "aliases": ["banking", "bank", "banks", "ngan hang", "credit", "lending"],
        },
        {
            "concept": "CONSUMER_DISCRETIONARY",
            "aliases": [
                "consumer discretionary",
                "retail",
                "tourism",
                "aviation demand",
                "auto",
                "hospitality",
            ],
        },
        {
            "concept": "CONSUMER_STAPLES",
            "aliases": ["consumer staples", "food", "beverage", "dairy", "fmcg"],
        },
        {
            "concept": "ENERGY",
            "aliases": ["energy", "oil", "gas", "petroleum", "fuel", "refinery"],
        },
        {
            "concept": "INDUSTRIALS",
            "aliases": ["industrials", "manufacturing", "transportation", "airlines"],
        },
        {
            "concept": "MACRO",
            "aliases": [
                "macro",
                "gdp",
                "cpi",
                "inflation",
                "interest rates",
                "exchange rate",
                "monetary policy",
            ],
        },
        {
            "concept": "MATERIALS",
            "aliases": ["materials", "steel", "rubber", "chemicals", "commodities"],
        },
        {
            "concept": "REAL_ESTATE",
            "aliases": ["real estate", "property", "residential", "commercial property"],
        },
        {
            "concept": "SECURITIES",
            "aliases": ["securities", "brokerage", "stock market", "trading liquidity"],
        },
        {
            "concept": "TECHNOLOGY",
            "aliases": ["technology", "it", "software", "digital transformation"],
        },
    ]

    allowed_concepts = {concept.value for concept in Concept}
    now = datetime.now(timezone.utc)

    for concept_doc in concepts:
        if concept_doc["concept"] not in allowed_concepts:
            raise ValueError(f"Invalid concept_dictionary concept: {concept_doc['concept']}")

        db.concept_dictionary.update_one(
            {"concept": concept_doc["concept"]},
            {
                "$set": {
                    "concept": concept_doc["concept"],
                    "aliases": concept_doc["aliases"],
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        print(f"  Seeded: {concept_doc['concept']}")


if __name__ == "__main__":
    print(f"Connecting to database: {DB_NAME}")
    setup_collections()
    setup_indexes()
    seed_static_ontology()
    seed_concept_dictionary()
    print("\nDone. Verify in Atlas UI -> Browse Collections.")
    client.close()
