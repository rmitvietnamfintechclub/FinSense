"""Pipeline entrypoint.

Intended stage order is rss -> scraper -> cluster -> extract -> aggregate
(see docs/FOLDER_STRUCTURE_GUIDANCE.md), but only the cluster stage is
implemented so far. `main()` takes already-scraped articles as input rather
than fetching them itself, since rss/scraper don't exist yet; wire those in
here once they land, and hand `run_cluster_stage`'s output to extract/aggregate
once those exist too.
"""
from __future__ import annotations

from collections.abc import Sequence

from backend.core.schemas.article import Article
from backend.core.schemas.event_cluster import EventCluster
from backend.pipeline.stages.cluster.builder import run_cluster_stage


def main(articles: Sequence[Article]) -> list[EventCluster]:
    return run_cluster_stage(articles)
