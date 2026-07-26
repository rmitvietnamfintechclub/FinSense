from __future__ import annotations

from backend.core.database import get_database
from backend.pipeline.stages.cluster.stage import run_cluster
from backend.pipeline.stages.rss.stage import run_rss
from backend.pipeline.stages.scraper.stage import run_scraper


def _preview(text: str, width: int = 400) -> str:
    collapsed = " ".join(text.split())  # kill newlines / double spaces
    return collapsed if len(collapsed) <= width else collapsed[:width] + "..."


def print_scraped_clusters(clusters) -> None:
    reps = scraped = unset = 0

    for cluster in clusters:
        breakdown = cluster.source_breakdown
        title = getattr(cluster, "event_title", None) or "(no title yet)"
        print("=" * 80)
        print(f"CLUSTER  {cluster.cluster_id}   ({len(breakdown)} sources)")
        print(f"  title: {title}")
        print("-" * 80)

        for n, sb in enumerate(breakdown, 1):
            rep = sb.representative_article
            reps += 1
            print(f"  [{n}] {sb.source}")
            print(f"      url:          {rep.url}")
            print(f"      published_at: {rep.published_at}")
            content = rep.content_fed_to_ai
            if content:
                scraped += 1
                print(f"      content:      SCRAPED ({len(content):,} chars)")
                print(f"      preview_content:      {_preview(content)!r}")
            else:
                unset += 1
                print("      content:      [UNSET] fetch_body returned None")

    print("=" * 80)
    print(
        f"SUMMARY: {len(clusters)} clusters | {reps} representatives | "
        f"{scraped} scraped | {unset} unset"
    )


def run_pipeline(db=None) -> list:
    db = db if db is not None else get_database()
    articles = db.articles
    event_clusters = db.event_clusters

    new_articles = run_rss(articles)
    new_clusters = run_cluster(new_articles, event_clusters, articles)
    return run_scraper(new_clusters)


def main():
    clusters = run_pipeline()
    print_scraped_clusters(clusters)  # the printer from earlier

    # TODO: run_extract(scraped_clusters, event_clusters) — persists content_fed_to_ai + ai_response


if __name__ == "__main__":
    main()
