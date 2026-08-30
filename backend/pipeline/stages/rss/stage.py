import logging

from pymongo.collection import Collection

from backend.core.database import get_database
from backend.core.schemas.article import Article
from backend.pipeline.stages.rss.filter import existing_urls, is_relevant
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


def run_rss(db_articles: Collection | None = None) -> list[Article]:
    if db_articles is None:
        db_articles = get_database().articles

    articles = fetch_all_feeds()

    # Collapse within-batch duplicates first: the same story can appear twice in
    # one pull, and there is no point asking the database about it twice.
    seen_url: set[str] = set()
    candidates: list[Article] = []
    for article in articles:
        if article.url in seen_url:
            continue
        seen_url.add(article.url)
        candidates.append(article)

    # One `$in` query for the whole batch. Previously this was a find_one per
    # article, which on a ~100-article pull was ~100 sequential round trips to
    # Atlas and dominated the stage's runtime.
    already_ingested = existing_urls((a.url for a in candidates), db_articles)

    valid_articles = []
    for article in candidates:
        if article.url in already_ingested:
            logger.info(f"URL: {article.url} already existed in database")
            continue
        if not is_relevant(article.title, article.summary):
            logger.info(f"Article with URL: {article.url} is irrelevant")
            continue
        valid_articles.append(article)

    _save_articles(valid_articles, db_articles)

    return valid_articles
