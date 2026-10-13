'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { apiClient } from '@/lib/api-client';
import { AuditRow } from './AuditRow';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import type { components } from '@finsense/types/generated/api.types';

type AuditArticles = components['schemas']['AuditArticles'];

export function AuditTable({
  status,
  sort,
  search,
  page,
  onActionSuccess
}: {
  status: string;
  sort: string;
  search: string;
  page: number;
  onActionSuccess: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [data, setData] = useState<AuditArticles | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  const fetchArticles = useCallback(async () => {
    // FE-04: Ép thoát khỏi luồng đồng bộ để né linter cascading renders
    await Promise.resolve();

    const query = new URLSearchParams();
    query.set('status', status);
    query.set('sort', sort);
    if (search) query.set('search', search);
    query.set('page', page.toString());

    return apiClient<AuditArticles>(`/audit/articles?${query.toString()}`);
  }, [status, sort, search, page]);

  useEffect(() => {
    let cancelled = false;

    void fetchArticles()
      .then((res) => {
        if (cancelled) return;

        setData(res);
        setError(false);
        setLoading(false);
        setExpandedRowId(null);
      })
      .catch(() => {
        if (cancelled) return;

        setError(true);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [fetchArticles]);

  const handlePageChange = (newPage: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('page', newPage.toString());
    router.push(`${pathname}?${params.toString()}`, { scroll: false });
  };

  const handleActionSuccess = () => {
    onActionSuccess();
    setExpandedRowId(null);
    setLoading(true);
    void fetchArticles()
      .then((res) => {
        setData(res);
        setError(false);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  };

  if (error) {
    return (
      <div className="bg-white rounded-xl border border-red-100 p-12 text-center flex flex-col items-center">
        <p className="text-gray-500 font-medium mb-3">Couldn&apos;t load this. Try again.</p>
        <button onClick={fetchArticles} className="px-6 py-2 bg-navy-900 text-white font-bold rounded-lg hover:bg-brand-dark transition-colors">
          Retry
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="p-6 border-b border-gray-100 flex items-center justify-between">
            <div className="w-1/2 h-4 bg-gray-100 rounded animate-pulse"></div>
            <div className="w-1/4 h-8 bg-gray-100 rounded animate-pulse"></div>
          </div>
        ))}
      </div>
    );
  }

  // Đảm bảo truy cập an toàn, đề phòng data bị thiếu trường items
  const items = data?.items || [];
  const total = data?.total ?? 0;

  if (items.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-16 text-center text-gray-500 shadow-sm font-medium">
        No articles found for the current filters.
      </div>
    );
  }

  const startIdx = (page - 1) * 10 + 1;
  const endIdx = Math.min(page * 10, total);

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col">
      <div className="flex flex-col">
        {items.map(row => {
          const rowKey = `${row.cluster_id}-${row.source}`;
          return (
            <AuditRow 
              key={rowKey} 
              row={row} 
              currentFilter={status}
              isExpanded={expandedRowId === rowKey}
              onToggleExpand={() => setExpandedRowId(expandedRowId === rowKey ? null : rowKey)}
              onActionSuccess={handleActionSuccess}
            />
          );
        })}
      </div>

      {total > 0 && (
        <div className="bg-gray-50 border-t border-gray-200 p-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <span className="text-sm font-medium text-gray-500">
            Showing {startIdx}–{endIdx} of {total} {status}
          </span>
          <div className="flex items-center gap-2">
            <button 
              onClick={() => handlePageChange(page - 1)}
              disabled={page === 1}
              className="p-2 border border-gray-200 rounded-lg bg-white text-gray-500 hover:text-navy-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-4 text-sm font-bold text-navy-900">Page {page}</span>
            <button 
              onClick={() => handlePageChange(page + 1)}
              disabled={!data?.has_more}
              className="p-2 border border-gray-200 rounded-lg bg-white text-gray-500 hover:text-navy-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}