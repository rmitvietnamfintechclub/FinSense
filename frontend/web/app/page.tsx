'use client';

import React, { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { SummaryCards } from '@/features/dashboard/components/SummaryCards';
import { TickerList } from '@/features/dashboard/components/TickerList';
import { EventList } from '@/features/dashboard/components/EventList';
import { MarketGauge } from '@/features/dashboard/components/MarketGauge';

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Đọc state từ URL, fallback về default
  const view = searchParams.get('view') || 'tickers'; // 'tickers' | 'events'
  const windowParam = searchParams.get('window') || '24h'; // '24h' | '48h' | '72h'

  // Hàm update URL mà không làm reload trang
  const updateParams = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set(key, value);
    router.push(`/?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="flex flex-col gap-8">
      {/* Header & Subtitle */}
      <div>
        <h1 className="text-3xl font-bold text-navy-900 mb-2">Market sentiment</h1>
        <p className="text-gray-600">How Vietnamese financial news is covering the market.</p>
      </div>

      {/* 4 Metric Cards */}
      <SummaryCards />

      {/* Main Content Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column (Lists) */}
        <div className="lg:col-span-8 flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-bold tracking-widest text-navy-900 uppercase">
              Most Covered {view === 'tickers' ? 'Tickers' : 'Events'}
            </h2>
            
            <div className="flex items-center gap-3">
              {/* View Toggle (Tickers / Events) */}
              <div className="flex items-center bg-gray-200/50 p-1 rounded-lg">
                <button
                  onClick={() => updateParams('view', 'tickers')}
                  className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${view === 'tickers' ? 'bg-white shadow-sm text-navy-900' : 'text-gray-600 hover:text-navy-900'}`}
                >
                  Tickers
                </button>
                <button
                  onClick={() => updateParams('view', 'events')}
                  className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${view === 'events' ? 'bg-white shadow-sm text-navy-900' : 'text-gray-600 hover:text-navy-900'}`}
                >
                  Events
                </button>
              </div>
            </div>
          </div>

          {/* RENDERING LIST (Dựa vào URL param) */}
          <div className="w-full">
            {view === 'tickers' ? (
              <TickerList windowParam={windowParam} />
            ) : (
              <EventList windowParam={windowParam} />
            )}
          </div>
        </div>

        {/* Right Column (Gauge) */}
        <div className="lg:col-span-4 flex flex-col gap-4">
          <div className="flex items-center justify-between">
             <h2 className="text-sm font-bold tracking-widest text-navy-900 uppercase">Fear & Greed Radar</h2>
             
             {/* Time Window Filter (1d, 2d, 3d -> 24h, 48h, 72h) */}
             <select 
               value={windowParam}
               onChange={(e) => updateParams('window', e.target.value)}
               className="bg-transparent text-sm font-medium text-gray-700 cursor-pointer focus:outline-none"
             >
               <option value="24h">1 day</option>
               <option value="48h">2 days</option>
               <option value="72h">3 days</option>
             </select>
          </div>

          <MarketGauge windowParam={windowParam} />
        </div>

      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="animate-pulse h-screen w-full bg-gray-50"></div>}>
      <DashboardContent />
    </Suspense>
  );
}