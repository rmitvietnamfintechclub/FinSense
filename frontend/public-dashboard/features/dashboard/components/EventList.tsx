"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { apiClient } from "@finsense/ui/src/api-client";
import type { components } from "@finsense/types/generated/api.types";
import { formatScore, getScoreColorClass } from "@/lib/formatters";

// Mở rộng EventFeedItem để hỗ trợ an toàn cả Dashboard lẫn Ticker Detail
type EventFeedItem = components["schemas"]["EventFeedItem"] & {
  sentiment_score?: number | null;
  is_empty?: boolean;
};

type EventArticlesResponse = components["schemas"]["EventArticles"];
type DashboardEventsResponse = components["schemas"]["DashboardEvents"];

// === SUBCOMPONENT: 1 DÒNG EVENT ===
function EventRow({
  event,
  isFirstRow = false,
}: {
  event: EventFeedItem;
  isFirstRow?: boolean;
}) {
  const router = useRouter();
  const [isExpanded, setIsExpanded] = useState(isFirstRow);
  const [articlesData, setArticlesData] =
    useState<EventArticlesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const hasFetchedOnce = useRef(false);

  const fetchArticles = useCallback(async () => {
    if (articlesData || loading) return;
    setLoading(true);
    setError(false);
    try {
      const res = await apiClient<EventArticlesResponse>(
        `/dashboard/events/${event.cluster_id}/articles`,
      );
      setArticlesData(res);
      hasFetchedOnce.current = true;
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [event.cluster_id, articlesData, loading]);

  useEffect(() => {
    if (isFirstRow && !hasFetchedOnce.current) {
      queueMicrotask(() => {
        void fetchArticles();
      });
    }
  }, [isFirstRow, fetchArticles]);

  const sortedSources = Object.entries(event.sources).sort(
    (a, b) => b[1] - a[1],
  );

  const toggleExpand = () => {
    if (!isExpanded) {
      void fetchArticles();
    }
    setIsExpanded(!isExpanded);
  };

  const hasScore = event.sentiment_score !== undefined;

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden hover:border-gray-300 transition-colors">
      <div
        onClick={toggleExpand}
        className="p-4 md:p-5 cursor-pointer flex flex-col md:flex-row gap-4 justify-between items-start md:items-center"
      >
        <div className="flex items-start gap-4 flex-1 overflow-hidden w-full">
          <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center font-bold text-gray-500 shrink-0 border border-gray-200">
            {event.rank}
          </div>
          <div className="flex flex-col gap-2 min-w-0 w-full">
            <h3
              className="text-base font-bold text-navy-900 truncate"
              title={event.event_title}
            >
              {event.event_title}
            </h3>

            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-gray-500 font-medium mr-2">
                {event.total_articles} articles
              </span>

              {sortedSources.map(([src, count]) => (
                <span
                  key={src}
                  className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs border border-gray-200"
                >
                  {src} <span className="font-bold">· {count}</span>
                </span>
              ))}

              {event.tickers_mentioned && event.tickers_mentioned.length > 0 && (
                <div className="flex items-center gap-1 ml-auto md:ml-4">
                  {event.tickers_mentioned.map((t) => (
                    <span
                      key={t}
                      onClick={(e) => {
                        e.stopPropagation();
                        router.push(`/ticker/${t}`);
                      }}
                      className="px-2 py-0.5 border border-brand-yellow/50 bg-brand-yellow/5 text-brand-dark rounded text-xs font-bold uppercase cursor-pointer hover:bg-brand-yellow hover:text-navy-900 transition-colors"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="shrink-0 ml-auto md:ml-0 text-gray-400">
          <div className="flex items-center gap-4">
            {hasScore && (
              <span
                className={`text-lg font-bold min-w-12 text-right ${getScoreColorClass(
                  event.sentiment_score,
                  event.is_empty,
                )}`}
              >
                {formatScore(event.sentiment_score, event.is_empty)}
              </span>
            )}
            {isExpanded ? (
              <ChevronUp className="w-5 h-5" />
            ) : (
              <ChevronDown className="w-5 h-5" />
            )}
          </div>
        </div>
      </div>

      {isExpanded && (
        <div className="bg-gray-50 border-t border-gray-200 p-4 md:p-5">
          {loading && (
            <div className="text-sm text-gray-500 animate-pulse">
              Loading articles...
            </div>
          )}
          {error && (
            <div className="text-sm text-red-500">Failed to load articles.</div>
          )}
          {articlesData && !loading && !error && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-gray-500 mb-2">
                Showing the {articlesData.articles_shown} articles the AI read,
                of {articlesData.total_articles} covering this event.
              </p>
              {articlesData.articles.map((art, i) => {
                const isEmpty = art.score === null || art.score === undefined;
                return (
                  <a
                    key={i}
                    href={art.article_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex flex-col md:flex-row items-start md:items-center gap-3 bg-white p-3 rounded-lg border border-gray-200 hover:border-gray-300 hover:shadow-sm transition-all group"
                  >
                    <span className="px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs font-medium min-w-20 text-center shrink-0">
                      {art.source}
                    </span>
                    <span
                      className="text-sm font-medium text-navy-900 flex-1 truncate"
                      title={art.article_title}
                    >
                      {art.article_title}
                    </span>
                    <div className="flex items-center gap-3 ml-auto shrink-0 w-full md:w-auto justify-between md:justify-end mt-2 md:mt-0">
                      <span
                        className={`text-sm font-bold min-w-12.5 text-right ${getScoreColorClass(
                          art.score,
                          isEmpty,
                        )}`}
                      >
                        {formatScore(art.score, isEmpty)}
                      </span>
                      <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-brand-dark" />
                    </div>
                  </a>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// === COMPONENT CHÍNH: EVENTS LIST ===
export function EventList({
  windowParam,
  tickerParam,
  emptyMessage,
}: {
  windowParam: string;
  tickerParam?: string;
  emptyMessage?: string;
}) {
  const [events, setEvents] = useState<EventFeedItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchEvents = useCallback(
    async (pageNum: number, isReset: boolean) => {
      setLoading(true);
      setError(false);
      try {
        const baseUrl = tickerParam
          ? `/tickers/${tickerParam}/events`
          : `/dashboard/events`;
        const data = await apiClient<DashboardEventsResponse>(
          `${baseUrl}?window=${windowParam}&page=${pageNum}&limit=5`,
        );
        setEvents((prev) => (isReset ? data.events : [...prev, ...data.events]));
        setHasMore(data.has_more);
        if (isReset) setPage(1);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [windowParam, tickerParam],
  );

  useEffect(() => {
    const runFetch = () => {
      void fetchEvents(1, true);
    };
    queueMicrotask(runFetch);
  }, [windowParam, tickerParam, fetchEvents]);

  const loadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchEvents(nextPage, false);
  };

  if (error) {
    return (
      <div className="bg-white rounded-xl p-8 border border-red-100 flex flex-col items-center justify-center text-gray-500">
        <p>Couldn&apos;t load events.</p>
        <button
          onClick={() => fetchEvents(page, page === 1)}
          className="text-brand-dark font-medium mt-2 hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!loading && events.length === 0) {
    return (
      <div className="bg-white rounded-xl p-8 text-center text-gray-500 border border-gray-200">
        {emptyMessage || "No events in the selected window."}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {events.map((event, index) => (
        <EventRow
          key={`${event.cluster_id}-${index}`} 
          event={event}
          isFirstRow={index === 0 && page === 1}
        />
      ))}

      {loading && (
        <div className="p-6 bg-white border border-gray-200 rounded-xl flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-brand-yellow border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}

      {hasMore && !loading && (
        <button
          onClick={loadMore}
          className="py-3 text-sm font-medium text-navy-900 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
        >
          Load more
        </button>
      )}
    </div>
  );
}