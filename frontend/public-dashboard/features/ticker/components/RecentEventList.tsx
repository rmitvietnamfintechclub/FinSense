"use client";

import React, { useEffect, useState, useCallback } from "react";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { apiClient } from "@finsense/ui/src/api-client";
import type { components } from "@finsense/types/generated/api.types";
import { formatScore, getScoreColorClass } from "@/lib/formatters";

type TickerEvents = components["schemas"]["TickerEvents"];
type TickerEventItem = NonNullable<TickerEvents["items"]>[number];

function RecentEventRow({
  event,
  isFirstRow = false,
}: {
  event: TickerEventItem;
  isFirstRow?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(isFirstRow);
  const isEmpty = event.sentiment_score === null;
  const createdAt = event.created_at ? new Date(event.created_at) : null;
  const formattedDate =
    createdAt && !Number.isNaN(createdAt.getTime())
      ? createdAt.toLocaleDateString("en-GB", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        })
      : "N/A";

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden hover:border-gray-300 transition-colors">
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="p-4 md:p-5 cursor-pointer flex flex-col md:flex-row gap-4 justify-between items-start md:items-center"
      >
        <div className="flex items-start gap-4 flex-1 overflow-hidden w-full">
          <div className="flex flex-col gap-2 min-w-0 w-full">
            <h3
              className="text-base font-bold text-navy-900 truncate"
              title={event.event_title}
            >
              {event.event_title}
            </h3>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-gray-500 font-medium mr-2">
                {event.article_count} articles
              </span>
              <span className="text-gray-400 text-xs">{formattedDate}</span>
            </div>
          </div>
        </div>

        <div className="shrink-0 ml-auto md:ml-0 text-gray-400">
          <div className="flex items-center gap-4">
            <span
              className={`text-lg font-bold min-w-12 text-right ${getScoreColorClass(event.sentiment_score, isEmpty)}`}
            >
              {formatScore(event.sentiment_score, isEmpty)}
            </span>
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
          <div className="flex flex-col gap-3">
            {(event.source_breakdown ?? []).map((src, i) => (
              <a
                key={i}
                href={src.article_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex flex-col md:flex-row items-start md:items-center gap-3 bg-white p-3 rounded-lg border border-gray-200 hover:border-gray-300 hover:shadow-sm transition-all group"
              >
                <span className="px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs font-medium min-w-20 text-center shrink-0">
                  {src.source}
                </span>
                <span
                  className="text-sm font-medium text-navy-900 flex-1 truncate"
                  title={src.article_title}
                >
                  {src.article_title}
                </span>
                <div className="flex items-center gap-3 ml-auto shrink-0 w-full md:w-auto justify-between md:justify-end mt-2 md:mt-0">
                  <span
                    className={`text-sm font-bold min-w-12.5 text-right ${getScoreColorClass(src.score, src.score === null)}`}
                  >
                    {formatScore(src.score, src.score === null)}
                  </span>
                  <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-brand-dark" />
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function RecentEventList({ symbol }: { symbol: string }) {
  const [events, setEvents] = useState<TickerEventItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchEvents = useCallback(
    async (pageNum: number, isReset: boolean) => {
      await Promise.resolve();
      setLoading(true);
      setError(false);
      try {
        const data = await apiClient<TickerEvents>(
          `/ticker/${symbol}/events?window=72h&page=${pageNum}&limit=5`,
        );
        const items = data.items ?? [];
        setEvents((prev) => (isReset ? items : [...prev, ...items]));
        setHasMore(Boolean(data.has_more));
        if (isReset) setPage(1);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [symbol],
  );

  useEffect(() => {
    let isActive = true;

    const loadInitialEvents = async () => {
      setLoading(true);
      setError(false);

      try {
        const data = await apiClient<TickerEvents>(
          `/ticker/${symbol}/events?window=72h&page=1&limit=5`,
        );
        if (isActive) {
          setEvents(data.items ?? []);
          setHasMore(Boolean(data.has_more));
          setPage(1);
        }
      } catch {
        if (isActive) setError(true);
      } finally {
        if (isActive) setLoading(false);
      }
    };

    void loadInitialEvents();

    return () => {
      isActive = false;
    };
  }, [symbol]);

  if (error)
    return (
      <div className="p-8 text-center text-red-500 border border-red-100 rounded-xl bg-white">
        Failed to load recent events.
      </div>
    );
  if (!loading && events.length === 0)
    return (
      <div className="p-8 text-center text-gray-500 border border-gray-200 rounded-xl bg-white">
        No news for {symbol} in the last 3 days.
      </div>
    );

  return (
    <div className="flex flex-col gap-4">
      {events.map((event, index) => (
        <RecentEventRow
          key={`${event.cluster_id}-${index}`}
          event={event}
          isFirstRow={index === 0 && page === 1}
        />
      ))}
      {loading && (
        <div className="p-6 flex justify-center">
          <div className="w-6 h-6 border-2 border-brand-yellow border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}
      {hasMore && !loading && (
        <button
          onClick={() => fetchEvents(page + 1, false)}
          className="py-3 text-sm font-medium text-navy-900 bg-white border border-gray-200 rounded-xl hover:bg-gray-50"
        >
          Load more
        </button>
      )}
    </div>
  );
}
