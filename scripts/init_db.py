"""
FIN-SENSE 2.0 — MongoDB initialisation script
Run once to create collections, indexes, and seed static_ontology + concept_dictionary.
Usage: MONGODB_URI=... python backend/scripts/init_db.py
"""

from datetime import datetime, timezone

import certifi
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import CollectionInvalid

from backend.core.config import database_settings

MONGO_URI = database_settings.MONGODB_URI
DB_NAME = database_settings.MONGODB_DB_NAME

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

    # articles
    db.articles.create_index("url", unique=True, name="url_unique")
    db.articles.create_index("cluster_id", name="cluster_id")
    print("  articles: done")

    # event_clusters
    db.event_clusters.create_index("cluster_id", unique=True, name="cluster_id_unique")
    db.event_clusters.create_index([("created_at", DESCENDING)], name="created_at_desc")
    db.event_clusters.create_index(
        "aggregated_analysis.ticker_sentiments.ticker", name="ticker_idx"
    )
    db.event_clusters.create_index(
        "aggregated_analysis.concept_sentiments.concept", name="concept_idx"
    )
    print("  event_clusters: done")

    # daily_sentiment_history
    db.daily_sentiment_history.create_index(
        [("ticker", ASCENDING), ("date", DESCENDING)],
        unique=True,
        name="ticker_date_unique",
    )
    db.daily_sentiment_history.create_index("ticker", name="ticker")
    print("  daily_sentiment_history: done")

    # static_ontology
    db.static_ontology.create_index("ticker", unique=True, name="ticker_unique")
    print("  static_ontology: done")

    # concept_dictionary
    db.concept_dictionary.create_index("concept", unique=True, name="concept_unique")
    db.concept_dictionary.create_index("aliases", name="aliases_multikey")
    print("  concept_dictionary: done")

    # audit_log
    db.audit_log.create_index("cluster_id", name="cluster_id")
    db.audit_log.create_index([("performed_at", DESCENDING)], name="performed_at_desc")
    db.audit_log.create_index("error_type", name="error_type")
    print("  audit_log: done")

    # frozen_test_set
    db.frozen_test_set.create_index("article_id", unique=True, name="article_id_unique")
    print("  frozen_test_set: done")


def seed_static_ontology():
    """
    Ticker → concept weight map for S_final calculation.
    PLACEHOLDER weights — mandatory human review required before production.
    """
    print("\nSeeding static_ontology...")

    tickers = [
        {
            "ticker": "HPG",
            "concept_weights": [
                {"concept": "STEEL", "weight": 1.0},
                {"concept": "CONSTRUCTION_MATERIALS", "weight": 0.5},
                {"concept": "MACRO", "weight": 0.3},
            ],
        },
        {
            "ticker": "VCB",
            "concept_weights": [
                {"concept": "BANKING", "weight": 1.0},
                {"concept": "MONETARY_POLICY", "weight": 0.8},
                {"concept": "MACRO", "weight": 0.3},
            ],
        },
        {
            "ticker": "VIC",
            "concept_weights": [
                {"concept": "REAL_ESTATE", "weight": 1.0},
                {"concept": "RETAIL", "weight": 0.4},
                {"concept": "MACRO", "weight": 0.2},
            ],
        },
        {
            "ticker": "GAS",
            "concept_weights": [
                {"concept": "OIL_GAS", "weight": 1.0},
                {"concept": "MACRO", "weight": 0.3},
            ],
        },
        {
            "ticker": "SSI",
            "concept_weights": [
                {"concept": "SECURITIES", "weight": 1.0},
                {"concept": "MACRO", "weight": 0.4},
            ],
        },
    ]

    for t in tickers:
        t["created_at"] = datetime.now(timezone.utc)
        db.static_ontology.update_one(
            {"ticker": t["ticker"]},
            {"$setOnInsert": t},
            upsert=True,
        )
        print(f"  Seeded: {t['ticker']}")

    print("  WARNING: concept_weights are PLACEHOLDERS.")
    print("  Mandatory human review required before production deployment.")


def seed_concept_dictionary():
    """
    Alias resolution map: whatever string Gemini returns → canonical concept enum.
    """
    print("\nSeeding concept_dictionary...")

    concepts = [
        {
            "concept": "STEEL",
            "aliases": ["Thép", "THEP", "thep", "steel", "ngành thép"],
        },
        {
            "concept": "BANKING",
            "aliases": ["Ngân hàng", "NH", "ngan hang", "bank", "banking"],
        },
        {
            "concept": "REAL_ESTATE",
            "aliases": [
                "BĐS",
                "BDS",
                "PROPERTY",
                "Bất động sản",
                "Nhà đất",
                "Địa ốc",
                "bat dong san",
            ],
        },
        {
            "concept": "OIL_GAS",
            "aliases": ["Dầu khí", "dau khi", "petroleum", "oil", "gas", "xăng dầu"],
        },
        {
            "concept": "SECURITIES",
            "aliases": ["Chứng khoán", "chung khoan", "CK", "brokerage", "securities"],
        },
        {
            "concept": "RETAIL",
            "aliases": ["Bán lẻ", "ban le", "retail", "bán buôn"],
        },
        {
            "concept": "FOOD_BEVERAGE",
            "aliases": ["Thực phẩm", "thuc pham", "F&B", "food", "beverage", "đồ uống"],
        },
        {
            "concept": "LOGISTICS",
            "aliases": [
                "Logistics",
                "vận tải",
                "van tai",
                "transportation",
                "vận chuyển",
            ],
        },
        {
            "concept": "TECHNOLOGY",
            "aliases": ["Công nghệ", "cong nghe", "tech", "IT", "công nghệ thông tin"],
        },
        {
            "concept": "MACRO",
            "aliases": [
                "Vĩ mô",
                "vi mo",
                "macro",
                "GDP",
                "CPI",
                "lạm phát",
                "lam phat",
                "kinh tế vĩ mô",
            ],
        },
        {
            "concept": "MONETARY_POLICY",
            "aliases": [
                "Chính sách tiền tệ",
                "NHNN",
                "lãi suất",
                "lai suat",
                "tín phiếu",
                "tin phieu",
                "Fed",
            ],
        },
        {
            "concept": "CONSTRUCTION_MATERIALS",
            "aliases": [
                "Vật liệu xây dựng",
                "VLXD",
                "xi măng",
                "xi mang",
                "cement",
                "vật liệu",
            ],
        },
    ]

    for c in concepts:
        c["created_at"] = datetime.now(timezone.utc)
        db.concept_dictionary.update_one(
            {"concept": c["concept"]},
            {"$setOnInsert": c},
            upsert=True,
        )
        print(f"  Seeded: {c['concept']}")


if __name__ == "__main__":
    print(f"Connecting to database: {DB_NAME}")
    setup_collections()
    setup_indexes()
    seed_static_ontology()
    seed_concept_dictionary()
    print("\nDone. Verify in Atlas UI → Browse Collections.")
    client.close()
