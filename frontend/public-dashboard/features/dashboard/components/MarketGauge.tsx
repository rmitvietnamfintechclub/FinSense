'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { apiClient } from '@finsense/ui/src/api-client';
import type { components } from '@finsense/types/generated/api.types';
import { formatScore, getScoreColorClass } from '@/lib/formatters';

type GaugeResponse = components['schemas']['DashboardGauge'];

// Helper để dịch điểm số thành chữ (dựa theo backend core/buckets.py)
function getSentimentLabel(score: number): string {
  if (score > 0.6) return 'Strongly positive';
  if (score > 0.2) return 'Slightly positive';
  if (score >= -0.2) return 'Neutral';
  if (score >= -0.6) return 'Slightly negative';
  return 'Strongly negative';
}

export function MarketGauge({ windowParam }: { windowParam: string }) {
  const [data, setData] = useState<GaugeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchGaugeData = useCallback(async () => {
    await Promise.resolve();

    setLoading(true);
    setError(false);
    try {
      const result = await apiClient<GaugeResponse>(`/dashboard/gauge?window=${windowParam}`);
      setData(result);
    } catch (err) {
      console.error("Failed to load gauge:", err);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [windowParam]);

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      void fetchGaugeData();
    }, 0);

    return () => clearTimeout(timeoutId);
  }, [fetchGaugeData]);

  // VẼ CÁC VẠCH (TICKS) CỦA GAUGE BẰNG SVG
  const renderTicks = () => {
    const ticks = [];
    const totalTicks = 20; // Chia nửa cung tròn thành 20 vạch
    for (let i = 0; i <= totalTicks; i++) {
      const angle = -90 + (i * 180) / totalTicks; // Từ -90 độ (trái) tới +90 độ (phải)
      const rad = (angle * Math.PI) / 180;
      
      const innerR = 75; // Bán kính trong
      const outerR = 90; // Bán kính ngoài
      
      const x1 = 100 + innerR * Math.sin(rad);
      const y1 = 100 - innerR * Math.cos(rad);
      const x2 = 100 + outerR * Math.sin(rad);
      const y2 = 100 - outerR * Math.cos(rad);

      // Đổi màu vạch theo vùng: Đỏ (Negative) -> Xám (Neutral) -> Xanh (Positive)
      let colorClass = "stroke-gray-300";
      if (i < 8) colorClass = "stroke-sentiment-neg";
      if (i > 12) colorClass = "stroke-sentiment-pos";

      ticks.push(
        <line
          key={i}
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          className={`${colorClass}`}
          strokeWidth="3"
          strokeLinecap="round"
        />
      );
    }
    return ticks;
  };

  if (error) {
    return (
      <div className="bg-white rounded-xl p-8 border border-red-100 flex flex-col items-center justify-center text-gray-500 aspect-square shadow-sm w-full">
        <p>Couldn&apos;t load radar.</p>
        <button 
          onClick={fetchGaugeData} 
          className="text-brand-dark font-medium mt-2 hover:underline cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  // Góc quay của kim chỉ (từ -90 tới +90)
  const score = data?.market_score || 0;
  const needleAngle = Math.max(-1, Math.min(1, score)) * 90;

  return (
    <div className="bg-white shadow-sm border border-gray-100 rounded-xl p-6 md:p-8 flex flex-col items-center justify-between aspect-square w-full relative">
      
      {/* Loading Overlay */}
      {loading && (
        <div className="absolute inset-0 bg-white/60 flex items-center justify-center z-10 rounded-xl backdrop-blur-sm">
          <div className="w-8 h-8 border-4 border-brand-yellow border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}

      {/* 1. KHU VỰC GAUGE (SVG) */}
      <div className="relative w-full max-w-60 aspect-2/1 mt-4">
        <svg viewBox="0 0 200 110" className="w-full h-full overflow-visible">
          {renderTicks()}
          
          {/* Kim đồng hồ (Chỉ vẽ nếu có data hợp lệ) */}
          {data && !data.is_empty && (
            <g transform={`translate(100, 100) rotate(${needleAngle})`} className="transition-transform duration-1000 ease-out">
              <circle cx="0" cy="0" r="5" className="fill-gray-900" />
              <circle cx="0" cy="0" r="1.5" className="fill-white" />
              {/* Cán kim */}
              <polygon points="-2,-4 2,-4 0,-70" className="fill-gray-900" />
            </g>
          )}
        </svg>

        {/* Nhãn 2 đầu */}
        <div className="absolute -bottom-2.5 left-2 text-[10px] uppercase font-bold text-gray-400 tracking-wider">Negative</div>
        <div className="absolute -bottom-2.5 right-2 text-[10px] uppercase font-bold text-gray-400 tracking-wider">Positive</div>
      </div>

      {/* 2. KHU VỰC HIỂN THỊ ĐIỂM SỐ */}
      <div className="text-center flex-1 flex flex-col justify-center mt-6">
        {data?.is_empty ? (
           <div className="text-gray-500 font-medium my-4">No data for this window</div>
        ) : (
          <>
            <div className={`text-5xl font-bold tracking-tight mb-1 ${getScoreColorClass(data?.market_score)}`}>
              {formatScore(data?.market_score)}
            </div>
            <div className="text-sm font-medium text-gray-500">
              {data ? `${getSentimentLabel(data.market_score)} coverage` : '---'}
            </div>
          </>
        )}
      </div>

      {/* 3. KHU VỰC ĐẾM BUCKET (BOTTOM) */}
      <div className="w-full grid grid-cols-3 gap-2 border-t border-gray-100 pt-6 mt-4">
        <div className="flex flex-col items-center">
          <span className="text-xl font-bold text-sentiment-pos">{data?.positive_count ?? '-'}</span>
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Positive</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-xl font-bold text-gray-500">{data?.neutral_count ?? '-'}</span>
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Neutral</span>
        </div>
        <div className="flex flex-col items-center">
          <span className="text-xl font-bold text-sentiment-neg">{data?.negative_count ?? '-'}</span>
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Negative</span>
        </div>
      </div>

    </div>
  );
}