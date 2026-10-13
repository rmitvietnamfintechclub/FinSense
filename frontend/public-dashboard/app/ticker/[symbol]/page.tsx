"use client";

import React, { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { apiClient } from "@finsense/ui/src/api-client";
import { RecentEventList } from "@/features/ticker/components/RecentEventList";
import { DualAxisChart } from "@/features/ticker/components/DualAxisChart";
import { formatScore, getScoreColorClass, formatTime } from "@/lib/formatters";
import type { components } from "@finsense/types/generated/api.types";

type TickerDetail = components["schemas"]["TickerDetail"];

function getSentimentLabel(score: number | null): string {
  if (score === null) return "No coverage";
  if (score > 0.6) return 'Strongly positive';
  if (score > 0.2) return 'Slightly positive coverage';
  if (score >= -0.2) return 'Neutral coverage';
  if (score >= -0.6) return 'Slightly negative coverage';
  return 'Strongly negative coverage';
}

function TickerContent() {
  const params = useParams();
  const symbol = (params.symbol as string).toUpperCase();
  const searchParams = useSearchParams();
  const router = useRouter();

  const chartWindow = searchParams.get('chart') || '30d';

  const [detail, setDetail] = useState<TickerDetail | null>(null);
  const [notFound, setNotFound] = useState(false);

  const updateChartParam = (value: string) => {
    const newParams = new URLSearchParams(searchParams.toString());
    newParams.set('chart', value);
    router.push(`/ticker/${symbol}?${newParams.toString()}`, { scroll: false });
  };

  const handleBackToDashboard = (e: React.MouseEvent) => {
    e.preventDefault();
    router.push("/");
  };

  useEffect(() => {
    let cancelled = false;

    const loadTicker = async () => {
      try {
        const data = await apiClient<TickerDetail>(`/ticker/${symbol}?window=72h`);
        if (!cancelled) setDetail(data);
      } catch (error: unknown) {
        if (
          !cancelled &&
          typeof error === "object" &&
          error !== null &&
          "message" in error &&
          typeof error.message === "string" &&
          error.message.includes("404")
        ) {
          setNotFound(true);
        }
      }
    };

    void loadTicker();

    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (notFound) {
    return <div className="text-center py-20 text-2xl font-bold text-gray-500">Ticker not found</div>;
  }

  const score = detail?.sentiment_score ?? null;
  const isEmpty = detail?.is_empty_state ?? true;
  const scalePosition = typeof score === 'number' ? ((score + 1) / 2) * 100 : 50;

  return (
    <div className="flex flex-col gap-8">
      <nav className="flex items-center text-sm font-medium text-gray-500">
        <a href="#" onClick={handleBackToDashboard} className="hover:text-brand-dark transition-colors">Dashboard</a>
        <ChevronRight className="w-4 h-4 mx-1" />
        <span className="text-navy-900">{symbol}</span>
      </nav>

      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6 bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
        <div>
          <h1 className="text-5xl font-black text-navy-900 mb-1 tracking-tight">{symbol}</h1>
          <p className="text-gray-500 text-lg font-medium mb-4">{detail?.company_name || '...'}</p>
          <div className="flex items-center gap-4 text-sm font-bold text-gray-400 uppercase tracking-widest">
            <span>{detail?.article_count ?? '-'} articles</span> • 
            <span>{detail?.event_count ?? '-'} events</span> • 
            <span>Updated {detail ? formatTime(detail.last_updated) : '--:--'}</span>
          </div>
        </div>

        <div className="w-full md:w-64 flex flex-col items-end shrink-0">
          <div className={`text-4xl font-bold tracking-tight mb-1 ${getScoreColorClass(score, isEmpty)}`}>
            {formatScore(score, isEmpty)}
          </div>
          <div className="text-sm font-bold text-gray-500 mb-4">{getSentimentLabel(score)}</div>
          <div className="w-full h-2 rounded-full bg-linear-to-r from-sentiment-neg via-gray-300 to-sentiment-pos relative">
            {!isEmpty && (
              <div 
                className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 bg-navy-900 border-2 border-white rounded-full shadow-md transition-all duration-1000"
                style={{ left: `${scalePosition}%` }}
              ></div>
            )}
          </div>
          <div className="w-full flex justify-between text-[10px] font-bold text-gray-400 mt-2">
            <span>-1.0</span><span>0</span><span>+1.0</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-7 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold tracking-widest text-navy-900 uppercase">Coverage vs Price</h2>
            <select
              value={chartWindow}
              onChange={(e) => updateChartParam(e.target.value)}
              className="bg-transparent text-sm font-medium text-gray-700 cursor-pointer focus:outline-none"
            >
              <option value="7d">7d</option>
              <option value="30d">30d</option>
              <option value="90d">90d</option>
            </select>
          </div>
          <DualAxisChart symbol={symbol} chartWindow={chartWindow} />
        </div>

        <div className="lg:col-span-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
             <h2 className="text-sm font-bold tracking-widest text-navy-900 uppercase">Recent Stories (Last 3 Days)</h2>
          </div>
          {/* Thay EventList thành RecentEventList chuyên dụng */}
          <RecentEventList symbol={symbol} />
        </div>
      </div>
    </div>
  );
}

export default function TickerDetailPage() {
  return (
    <Suspense fallback={<div className="animate-pulse h-screen w-full bg-gray-50"></div>}>
      <TickerContent />
    </Suspense>
  );
}