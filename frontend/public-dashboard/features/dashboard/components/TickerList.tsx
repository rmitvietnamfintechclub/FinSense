"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@finsense/ui/src/api-client";
import type { components } from "@finsense/types/generated/api.types";
import { formatScore, getScoreColorClass } from "@/lib/formatters";

type TickerFeedItem = components["schemas"]["TickerFeedItem"];
type DashboardTickersResponse = components["schemas"]["DashboardTickers"];

export function TickerList({ windowParam }: { windowParam: string }) {
  const router = useRouter();
  const [tickers, setTickers] = useState<TickerFeedItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchTickers = useCallback(
    async (pageNum: number, isReset: boolean) => {
      try {
        setLoading(true);
        setError(false);
        const data = await apiClient<DashboardTickersResponse>(
          `/dashboard/tickers?window=${windowParam}&page=${pageNum}&limit=5`,
        );

        setTickers((prev) =>
          isReset ? data.tickers : [...prev, ...data.tickers],
        );
        setHasMore(data.has_more);

        if (isReset) {
          setPage(1);
        }
      } catch (err) {
        console.error(err);
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [windowParam],
  );

  useEffect(() => {
    let isActive = true;

    queueMicrotask(() => {
      if (isActive) {
        void fetchTickers(1, true);
      }
    });

    return () => {
      isActive = false;
    };
  }, [windowParam, fetchTickers]);

  const loadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchTickers(nextPage, false);
  };

  if (error) {
    return (
      <div className="bg-white rounded-xl p-8 border border-red-100 flex flex-col items-center justify-center text-gray-500">
        <p>Couldn&apos;t load tickers.</p>
        <button
          onClick={() => fetchTickers(page, page === 1)}
          className="text-brand-dark font-medium mt-2 hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!loading && tickers.length === 0) {
    return (
      <div className="bg-white rounded-xl p-8 text-center text-gray-500 border border-gray-200">
        No events in the selected window.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {tickers.map((ticker, index) => {
        const isTop1 = ticker.rank === 1;
        const isTop2 = ticker.rank === 2;
        const isTop3 = ticker.rank === 3;

        // Xử lý viền trái cho Top 2 và Top 3
        let leftBorderClass = "border-l-4 border-l-transparent";
        if (isTop2) leftBorderClass = "border-l-4 border-l-slate-300"; // Bạc
        if (isTop3) leftBorderClass = "border-l-4 border-l-amber-600"; // Đồng

        return (
          <div
            key={ticker.ticker}
            onClick={() => router.push(`/ticker/${ticker.ticker}`)}
            className={`bg-white rounded-xl cursor-pointer hover:shadow-md transition-shadow group
              ${isTop1 ? "p-6 border-2 border-brand-yellow" : `p-4 border border-gray-200 ${leftBorderClass}`}
            `}
          >
            {/* Cấu trúc cho TOP 1 */}
            {isTop1 ? (
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full border border-brand-yellow flex items-center justify-center font-bold text-brand-dark bg-brand-yellow/10">
                      1
                    </div>
                    <div className="flex items-baseline gap-2">
                      <span className="text-xl font-bold text-navy-900 group-hover:text-brand-dark transition-colors">
                        {ticker.ticker}
                      </span>
                      <span className="text-sm text-gray-500">
                        {ticker.company_name}
                      </span>
                    </div>
                  </div>
                  <span className="px-3 py-1 rounded-full border border-brand-yellow text-brand-dark text-xs font-bold uppercase tracking-wider">
                    Most Covered
                  </span>
                </div>

                <div>
                  <div className="flex items-baseline gap-1 mb-2">
                    <span className="text-4xl font-bold text-navy-900">
                      {ticker.event_count}
                    </span>
                    <span className="text-sm text-gray-500">events today</span>
                  </div>
                  {/* Bar giả lập tỷ lệ (Top 1 luôn 100%) */}
                  <div className="w-full h-2 bg-navy-900 rounded-full"></div>
                </div>

                <div className="flex items-center justify-between pt-2">
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-widest">
                    Sentiment Score
                  </div>
                  <div className="flex items-center gap-3">
                    <span
                      className={`text-2xl font-bold ${getScoreColorClass(ticker.sentiment_score, ticker.is_empty)}`}
                    >
                      {formatScore(ticker.sentiment_score, ticker.is_empty)}
                    </span>
                    <span className="text-sm text-gray-500">tone</span>
                  </div>
                </div>
              </div>
            ) : (
              /* Cấu trúc cho TOP 2 trở đi */
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 rounded-full border border-gray-200 flex items-center justify-center font-bold text-gray-400 shrink-0">
                  {ticker.rank}
                </div>
                <div className="flex flex-col min-w-30">
                  <span className="text-lg font-bold text-navy-900 group-hover:text-brand-dark transition-colors">
                    {ticker.ticker}
                  </span>
                  <span className="text-xs text-gray-500 truncate">
                    {ticker.company_name}
                  </span>
                </div>
                <div className="flex-1 flex flex-col justify-center gap-1">
                  <span className="text-sm font-bold text-navy-900">
                    {ticker.event_count}{" "}
                    <span className="font-normal text-gray-500">events</span>
                  </span>
                  {/* Vẽ bar tương đối (mock max 30 cho rank phụ) */}
                  <div className="w-full bg-gray-100 rounded-full h-1.5 max-w-50">
                    <div
                      className="bg-gray-500 h-1.5 rounded-full"
                      style={{
                        width: `${Math.max((ticker.event_count / 30) * 100, 10)}%`,
                      }}
                    ></div>
                  </div>
                </div>
                <div
                  className={`text-xl font-bold shrink-0 ${getScoreColorClass(ticker.sentiment_score, ticker.is_empty)}`}
                >
                  {formatScore(ticker.sentiment_score, ticker.is_empty)}
                </div>
              </div>
            )}
          </div>
        );
      })}

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
