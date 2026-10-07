"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { apiClient } from "@finsense/ui/src/api-client";
import { formatScore } from "@/lib/formatters";

type TickerHistoryRow = {
  data: never[];
  date: string;
  closing_price: number | null;
  daily_sentiment_score: number | null;
};


export function DualAxisChart({ symbol, chartWindow }: { symbol: string; chartWindow: string }) {
  const [data, setData] = useState<TickerHistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const fetchChart = useCallback(async () => {
    await Promise.resolve();
    setLoading(true);
    setError(false);
    try {
      // FE-03: Đổi 30d thành 30 (bỏ chữ d để truyền API parameter chuẩn)
      const days = parseInt(chartWindow.replace('d', ''), 10) || 30;
      const res = await apiClient<TickerHistoryRow>(`/ticker/${symbol}/history?days=${days}`);
      setData(res.data || []);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [symbol, chartWindow]);

  useEffect(() => {
    void Promise.resolve().then(fetchChart);
  }, [fetchChart]);

  if (error) return <div className="h-64 flex items-center justify-center text-red-500 border border-red-100 rounded-xl bg-white">Failed to load chart</div>;
  if (loading) return <div className="h-64 flex items-center justify-center border border-gray-100 rounded-xl animate-pulse bg-gray-50"></div>;
  if (data.length === 0) return <div className="h-64 flex items-center justify-center text-gray-500 border border-gray-100 rounded-xl bg-white">Not enough data to display chart</div>;

  // --- THÔNG SỐ VẼ SVG ---
  const width = 800;
  const height = 300;
  const paddingX = 40;
  const paddingY = 40;
  const chartW = width - paddingX * 2;
  const chartH = height - paddingY * 2;
  const midY = paddingY + chartH / 2;

  const validPrices = data.map((d) => d.closing_price).filter((p): p is number => p !== null);
  const hasPriceData = validPrices.length > 0;
  const minPrice = hasPriceData ? Math.min(...validPrices) * 0.95 : 0;
  const maxPrice = hasPriceData ? Math.max(...validPrices) * 1.05 : 100;
  const priceRange = maxPrice - minPrice;

  const stepX = data.length > 1 ? chartW / (data.length - 1) : chartW;

  let linePath = "";
  let isFirstPoint = true;
  data.forEach((d, i) => {
    if (d.closing_price !== null) {
      const x = paddingX + i * stepX;
      const y = paddingY + chartH - ((d.closing_price - minPrice) / priceRange) * chartH;
      if (isFirstPoint) {
        linePath += `M ${x} ${y} `;
        isFirstPoint = false;
      } else {
        linePath += `L ${x} ${y} `;
      }
    }
  });

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const scaleX = width / rect.width;
    const svgX = mouseX * scaleX - paddingX;

    let closestIdx = Math.round(svgX / stepX);
    if (closestIdx < 0) closestIdx = 0;
    if (closestIdx >= data.length) closestIdx = data.length - 1;
    setHoverIndex(closestIdx);
  };

  return (
    <div className="w-full relative">
      <div className="flex items-center gap-6 mb-4 text-xs font-bold text-gray-500 uppercase tracking-widest">
        <div className="flex items-center gap-2"><div className="w-3 h-3 bg-brand-yellow rounded-sm"></div> News sentiment</div>
        <div className="flex items-center gap-2"><div className="w-4 h-0.5 bg-navy-900"></div> Closing price</div>
      </div>

      {!hasPriceData && (
        <div className="absolute top-12 right-4 text-xs font-bold bg-gray-100 text-gray-500 px-3 py-1 rounded-md">Price data unavailable</div>
      )}

      <div className="w-full overflow-hidden bg-white border border-gray-100 rounded-xl relative shadow-sm">
        <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="w-full h-full" onMouseMove={handleMouseMove} onMouseLeave={() => setHoverIndex(null)}>
          <line x1={paddingX} y1={midY} x2={width - paddingX} y2={midY} stroke="#e5e7eb" strokeWidth="1" />
          <line x1={paddingX} y1={height - paddingY} x2={width - paddingX} y2={height - paddingY} stroke="#e5e7eb" strokeWidth="1" />

          {/* LƯU Ý SỬA LẠI TÊN BIẾN THEO SCHEMA: daily_sentiment_score */}
          {data.map((d, i) => {
            if (d.daily_sentiment_score === null) return null;
            const x = paddingX + i * stepX;
            let barH = Math.abs(d.daily_sentiment_score) * (chartH / 2);
            if (d.daily_sentiment_score === 0) barH = 2;

            const y = d.daily_sentiment_score > 0 ? midY - barH : midY;
            return <rect key={`bar-${i}`} x={x - 4} y={y} width="8" height={barH} fill={d.daily_sentiment_score >= 0 ? "#EAB308" : "#94a3b8"} rx="2" className="transition-all duration-300" />;
          })}

          {hasPriceData && <path d={linePath} fill="none" stroke="#0F172A" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />}

          {data.map((d, i) => {
            const showLabel = i === 0 || i === Math.floor(data.length / 2) || i === data.length - 1;
            if (!showLabel) return null;
            return <text key={`lx-${i}`} x={paddingX + i * stepX} y={height - 15} fontSize="12" fill="#9ca3af" textAnchor="middle">{new Date(d.date).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</text>;
          })}

          {hoverIndex !== null && data[hoverIndex] && (
            <g>
              <line x1={paddingX + hoverIndex * stepX} y1={paddingY} x2={paddingX + hoverIndex * stepX} y2={height - paddingY} stroke="#94a3b8" strokeWidth="1" strokeDasharray="4 4" />
              <circle cx={paddingX + hoverIndex * stepX} cy={data[hoverIndex].closing_price !== null ? paddingY + chartH - ((data[hoverIndex].closing_price! - minPrice) / priceRange) * chartH : midY} r="4" fill="#0F172A" />
            </g>
          )}
        </svg>

        {hoverIndex !== null && data[hoverIndex] && (
          <div className="absolute pointer-events-none bg-navy-900 text-white p-3 rounded-lg shadow-xl text-xs flex flex-col gap-1 z-10 w-44" style={{ left: `calc(${((paddingX + hoverIndex * stepX) / width) * 100}% - 88px)`, top: "20px" }}>
            <div className="font-bold text-gray-300 mb-1">{new Date(data[hoverIndex].date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</div>
            <div className="flex justify-between items-center">
              <span className="text-gray-400">Tone:</span>
              <span className={`font-bold ${data[hoverIndex].daily_sentiment_score === null ? "text-gray-400" : data[hoverIndex].daily_sentiment_score! >= 0 ? "text-brand-yellow" : "text-white"}`}>
                {data[hoverIndex].daily_sentiment_score === null ? "No news" : formatScore(data[hoverIndex].daily_sentiment_score)}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-400">Price:</span>
              <span className="font-bold">{data[hoverIndex].closing_price !== null ? data[hoverIndex].closing_price?.toLocaleString() : "Unavailable"}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}