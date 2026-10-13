'use client';

import React, { useEffect, useState } from 'react';
import { apiClient } from '@finsense/ui/src/api-client';
import type { components } from '@finsense/types/generated/api.types';
import { formatTime } from '@/lib/formatters';
import { List, FileText, Activity, Clock } from 'lucide-react';

type DashboardSummary = components['schemas']['DashboardSummary'];

export function SummaryCards() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let isMounted = true;

    const loadData = async () => {
      try {
        const result = await apiClient<DashboardSummary>('/dashboard/summary');
        
        // Chỉ set state sau khi đã lấy data thành công (bất đồng bộ)
        if (isMounted) {
          setData(result);
          setError(false);
        }
      } catch (err) {
        console.error("Failed to fetch summary:", err);
        if (isMounted) {
          setError(true);
        }
      }
    };

    // Khởi chạy lần đầu
    loadData();

    // Auto-refresh mỗi 30 phút theo requirement
    const interval = setInterval(loadData, 30 * 60 * 1000);
    
    // Cleanup function
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  if (error) {
    return (
      <div className="bg-white rounded-xl p-6 border border-red-100 flex flex-col items-center justify-center text-gray-500">
        <p>Couldn&apos;t load summary.</p>
        <button 
          onClick={() => window.location.reload()} 
          className="text-brand-dark font-medium mt-2 hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  const cards = [
    { label: 'TICKERS', value: data?.total_tickers ?? '-', icon: List },
    { label: 'ARTICLES', value: data?.total_articles ?? '-', icon: FileText },
    { label: 'EVENTS', value: data?.total_events ?? '-', icon: Activity },
    { label: 'LAST UPDATED', value: data ? formatTime(data.last_updated) : '--:--', icon: Clock },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6">
      {cards.map((card, idx) => (
        <div key={idx} className="bg-white rounded-xl p-5 md:p-6 shadow-sm border border-gray-100 flex flex-col justify-between">
          <div className="flex items-center gap-2 text-gray-500 mb-3">
            <card.icon className="w-4 h-4" />
            <span className="text-xs font-semibold tracking-wider uppercase">{card.label}</span>
          </div>
          {data ? (
            <div className="text-3xl md:text-4xl font-bold text-navy-900">
              {card.label === 'LAST UPDATED' ? (
                <span className="text-2xl md:text-3xl">{card.value}</span>
              ) : (
                card.value
              )}
            </div>
          ) : (
            <div className="h-10 bg-gray-100 animate-pulse rounded w-1/2"></div> // Loading state
          )}
        </div>
      ))}
    </div>
  );
}