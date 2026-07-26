import logging

from pymongo.collection import Collection

from backend.core.database import get_database
from backend.core.schemas.article import Article
from backend.pipeline.stages.rss.filter import is_duplicate, is_relevant
from backend.pipeline.stages.rss.rss_fetcher import fetch_all_feeds

logger = logging.getLogger(__name__)


def _save_articles(
    articles: list[Article], collection: Collection | None = None
) -> None:
    if collection is None:
        collection = get_database().articles

    if not articles:
        return

    collection.insert_many(article.model_dump() for article in articles)


def run_rss(db_articles: Collection) -> list[Article]:
    if db_articles is None:
        db_articles = get_database().articles

    valid_articles = []

    articles = fetch_all_feeds()
    seen_url: set[str] = set()
    for article in articles:
        url = article.url
        if url in seen_url:
            continue
        seen_url.add(url)
        if is_duplicate(url, db_articles):
            logger.info(f"URL: {url} already existed in database")
            continue
        if not is_relevant(article.title, article.summary):
            logger.info(f"Article with URL: {url} is irrelevant")
            continue
        valid_articles.append(article)

    _save_articles(valid_articles, db_articles)

    return valid_articles
