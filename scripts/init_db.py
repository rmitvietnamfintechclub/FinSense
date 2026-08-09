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

    # audit_log
    db.audit_log.create_index("cluster_id", name="cluster_id")
    db.audit_log.create_index([("performed_at", DESCENDING)], name="performed_at_desc")
    db.audit_log.create_index("error_type", name="error_type")
    print("  audit_log: done")

    # frozen_test_set
    db.frozen_test_set.create_index("article_id", unique=True, name="article_id_unique")
    print("  frozen_test_set: done")


if __name__ == "__main__":
    print(f"Connecting to database: {DB_NAME}")
    setup_collections()
    setup_indexes()
    print("\nDone. Verify in Atlas UI → Browse Collections.")
    client.close()