'use client';

import React, { useState } from 'react';
import { CorrectForm } from './CorrectForm';
import { apiClient } from '@/lib/api-client';
import type { components } from '@finsense/types/generated/api.types';

type AuditArticleRow = components['schemas']['AuditArticleRow'];

export function AuditRow({
  row,
  currentFilter,
  isExpanded,
  onToggleExpand,
  onActionSuccess,
}: {
  row: AuditArticleRow;
  currentFilter: string;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onActionSuccess: () => void;
}) {
  const [isFading, setIsFading] = useState(false);
  const [approveError, setApproveError] = useState('');
  const [isApproving, setIsApproving] = useState(false);

  // Đảm bảo ai_confidence luôn có giá trị fallback an toàn
  const confidence = row.ai_confidence ?? 0;
  const confWidth = `${Math.max(confidence * 100, 5)}%`;
  let confColor = 'bg-green-500';
  if (confidence < 0.8) confColor = 'bg-yellow-400';
  if (confidence < 0.5) confColor = 'bg-red-500';

  const handleApprove = async () => {
    setIsApproving(true);
    setApproveError('');
    try {
      await apiClient(`/audit/events/${row.cluster_id}/${row.source}`, {
        method: 'PATCH',
        body: JSON.stringify({ action_type: 'approve' }),
      });
      
      if (currentFilter === 'pending') {
        setIsFading(true);
        setTimeout(() => {
          onActionSuccess();
        }, 300);
      } else {
        onActionSuccess();
      }
    } catch {
      setApproveError("Couldn't save. Try again.");
      setIsApproving(false);
    }
  };

  const handleCorrectionSuccess = () => {
    if (currentFilter === 'pending') {
      setIsFading(true);
      setTimeout(() => onActionSuccess(), 300);
    } else {
      onActionSuccess();
    }
  };

  return (
    <div className={`bg-white border-b border-gray-200 transition-all duration-300 ${isFading ? 'opacity-0 scale-95 h-0 overflow-hidden border-none' : 'opacity-100'}`}>
      
      <div className="flex flex-col xl:flex-row items-start xl:items-center gap-4 p-4 md:p-5 hover:bg-gray-50 transition-colors">
        
        <div className="flex-1 min-w-0 flex flex-col gap-1 w-full">
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2 py-0.5 bg-gray-100 border border-gray-200 rounded text-xs font-bold text-gray-600">{row.source}</span>
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-widest ${row.is_audited ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
              {row.is_audited ? 'Audited' : 'Pending'}
            </span>
            {approveError && <span className="text-xs text-red-500 font-medium ml-2">{approveError}</span>}
          </div>
          <h3 className="text-sm font-bold text-navy-900 truncate" title={row.article_title || row.event_title}>
            {row.article_title || row.event_title}
          </h3>
          <p className="text-xs text-gray-500 truncate mt-0.5">Event: {row.event_title}</p>
        </div>

        <div className="flex items-center gap-6 xl:gap-8 shrink-0 w-full xl:w-auto mt-3 xl:mt-0">
          <div className="flex flex-col w-20">
            <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Tickers</span>
            <span className="text-sm font-medium text-navy-900">{row.ticker_count}</span>
          </div>

          <div className="flex flex-col w-32">
            <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">AI Confidence</span>
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-16 bg-gray-100 rounded-full overflow-hidden">
                <div className={`h-full ${confColor} rounded-full`} style={{ width: confWidth }}></div>
              </div>
              <span className="text-xs font-bold text-navy-900">{confidence.toFixed(2)}</span>
            </div>
          </div>

          <div className="flex items-center gap-2 ml-auto xl:ml-0">
            {row.is_audited ? (
              <button 
                onClick={onToggleExpand}
                className="px-4 py-2 border border-gray-200 text-navy-900 text-xs font-bold uppercase tracking-widest rounded-lg hover:bg-gray-100 transition-colors"
              >
                {isExpanded ? 'Close' : 'Re-edit'}
              </button>
            ) : (
              <>
                <button 
                  onClick={handleApprove}
                  disabled={isApproving}
                  className="px-4 py-2 bg-navy-900 hover:bg-brand-dark text-white text-xs font-bold uppercase tracking-widest rounded-lg transition-colors disabled:opacity-50"
                >
                  {isApproving ? '...' : 'Approve'}
                </button>
                <button 
                  onClick={onToggleExpand}
                  className="px-4 py-2 border border-gray-200 text-navy-900 text-xs font-bold uppercase tracking-widest rounded-lg hover:bg-gray-100 transition-colors"
                >
                  {isExpanded ? 'Close' : 'Correct'}
                </button>
              </>
            )}
          </div>
        </div>

      </div>

      {isExpanded && (
        <CorrectForm 
          row={row} 
          onClose={onToggleExpand} 
          onSuccess={handleCorrectionSuccess} 
        />
      )}
    </div>
  );
}