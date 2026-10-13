'use client';

import React, { Suspense, useEffect, useState, useCallback } from 'react';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import { AuditFilters } from '@/features/audit/components/AuditFilters';
import { AuditTable } from '@/features/audit/components/AuditTable';
import type { components } from '@finsense/types/generated/api.types';

type AuditSummary = components['schemas']['AuditSummary'];

function AuditContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  // Đồng bộ state với URL
  const status = searchParams.get('status') || 'pending';
  const sort = searchParams.get('sort') || 'newest';
  const search = searchParams.get('search') || '';
  const page = parseInt(searchParams.get('page') || '1', 10);

  const [summary, setSummary] = useState<AuditSummary | null>(null);

  const fetchSummary = useCallback(
    () => apiClient<AuditSummary>('/audit/summary'),
    []
  );

  useEffect(() => {
    let isActive = true;

    void fetchSummary()
      .then((data) => {
        if (isActive) setSummary(data);
      })
      .catch((error) => {
        console.error('Failed to fetch audit summary:', error);
      });

    return () => {
      isActive = false;
    };
  }, [fetchSummary]);

  const refreshSummary = useCallback(() => {
    void fetchSummary()
      .then((data) => setSummary(data))
      .catch((error) => {
        console.error('Failed to refresh audit summary:', error);
      });
  }, [fetchSummary]);

  const updateParams = (updates: Record<string, string>) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    });
    router.push(`${pathname}?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-black text-navy-900 mb-2 tracking-tight">Audit queue</h1>
        <p className="text-gray-600">Review AI-extracted sentiment per source article. Approve as-is, or correct and log the change.</p>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">Total Articles</span>
          <div className="text-3xl font-black text-navy-900 mt-2">{summary?.total_articles ?? '-'}</div>
        </div>
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">Audited Articles</span>
          <div className="text-3xl font-black text-sentiment-pos mt-2">{summary?.audited_articles ?? '-'}</div>
        </div>
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">Pending Review</span>
          <div className="text-3xl font-black text-brand-dark mt-2">{summary?.pending_review ?? '-'}</div>
          <p className="text-[10px] text-gray-400 mt-1.5 leading-tight">
            Includes raw articles not selected for AI extraction. Do not expect this to reach zero.
          </p>
        </div>
      </div>

      {/* Toolbar */}
      <AuditFilters status={status} sort={sort} search={search} onChange={updateParams} />

      {/* Data Table Stub */}
      <AuditTable 
        status={status} 
        sort={sort} 
        search={search} 
        page={page} 
        onActionSuccess={fetchSummary} 
      />
    </div>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<div className="animate-pulse h-screen w-full bg-gray-50"></div>}>
      <AuditContent />
    </Suspense>
  );
}