'use client';

import React, { useState } from 'react';
import { ErrorTypePicker } from './ErrorTypePicker';
import { apiClient } from '@/lib/api-client';
import type { components } from '@finsense/types/generated/api.types';

type AuditArticleRow = components['schemas']['AuditArticleRow'];
type AuditAction = components['schemas']['AuditAction'];

// Helper format điểm thành string 2 chữ số (an toàn với null/undefined)
const fmt = (num: number | null | undefined) => {
  if (num === null || num === undefined) return '-';
  return num > 0 ? `+${num.toFixed(2)}` : num.toFixed(2);
};

export function CorrectForm({
  row,
  onClose,
  onSuccess
}: {
  row: AuditArticleRow;
  onClose: () => void;
  onSuccess: () => void;
}) {
  // Lấy các mảng một cách an toàn (fallback về mảng rỗng nếu undefined)
  const currentTickers = row.ticker_sentiments || [];
  const currentConcepts = row.concept_sentiments || [];
  const originalTickers = row.original_ticker_sentiments || [];
  const originalConcepts = row.original_concept_sentiments || [];

  const aiOriginalTickers = new Map(originalTickers.map(t => [t.ticker, t.score]));
  const aiOriginalConcepts = new Map(originalConcepts.map(c => [c.concept, c.score]));

  // State lưu trữ dữ liệu đang gõ (dạng chuỗi để cho phép gõ dấu '-' hoặc '.')
  const [tickerScores, setTickerScores] = useState<Record<string, string>>(
    Object.fromEntries(currentTickers.map(t => [String(t.ticker), t.score !== null && t.score !== undefined ? String(t.score) : '']))
  );
  const [conceptScores, setConceptScores] = useState<Record<string, string>>(
    Object.fromEntries(currentConcepts.map(c => [String(c.concept), c.score !== null && c.score !== undefined ? String(c.score) : '']))
  );
  
  const [errorType, setErrorType] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const hasChanges = () => {
    const tChanged = currentTickers.some(t => parseFloat(tickerScores[String(t.ticker)] || '0') !== t.score);
    const cChanged = currentConcepts.some(c => parseFloat(conceptScores[String(c.concept)] || '0') !== c.score);
    return tChanged || cChanged;
  };

  const handleSave = async () => {
    setErrorMsg('');
    
    // Kiểm tra định dạng số
    const allValues = [...Object.values(tickerScores), ...Object.values(conceptScores)];
    for (const val of allValues) {
      if (val === '') continue; // Bỏ qua nếu rỗng
      const num = parseFloat(val);
      if (isNaN(num) || num < -1 || num > 1) {
        setErrorMsg('All scores must be numbers between -1.00 and +1.00');
        return;
      }
    }

    if (!errorType) {
      setErrorMsg('Please select an error type.');
      return;
    }

    setIsSubmitting(true);

    try {
      // Chỉ lấy những phần bị thay đổi
      const corrected_ticker_sentiments: NonNullable<AuditAction['corrected_ticker_sentiments']> = currentTickers
        .filter((t): t is (typeof t) & { ticker: NonNullable<typeof t.ticker> } =>
          t.ticker !== undefined && parseFloat(tickerScores[String(t.ticker)] || '0') !== t.score
        )
        .map(t => ({ ticker: t.ticker, score: parseFloat(tickerScores[String(t.ticker)] || '0') }));

      const corrected_concept_sentiments: NonNullable<AuditAction['corrected_concept_sentiments']> = currentConcepts
        .filter((c): c is (typeof c) & { concept: NonNullable<typeof c.concept> } =>
          c.concept !== undefined && parseFloat(conceptScores[String(c.concept)] || '0') !== c.score
        )
        .map(c => ({ concept: c.concept, score: parseFloat(conceptScores[String(c.concept)] || '0') }));

      const payload: AuditAction = {
        action_type: 'correct',
        error_type: errorType as AuditAction['error_type'],
        corrected_ticker_sentiments: corrected_ticker_sentiments.length > 0 ? corrected_ticker_sentiments : undefined,
        corrected_concept_sentiments: corrected_concept_sentiments.length > 0 ? corrected_concept_sentiments : undefined,
      };

      await apiClient(`/audit/events/${row.cluster_id}/${row.source}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });

      onSuccess();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to save correction.');
      setIsSubmitting(false);
    }
  };

  const handleCancel = () => {
    if (hasChanges() || errorType) {
      if (!window.confirm('Discard your changes?')) return;
    }
    onClose();
  };

  const canSave = errorType !== null && (hasChanges() || errorType === 'No error');

  return (
    <div className="bg-gray-50 border-t border-gray-200 p-6 flex flex-col lg:flex-row gap-8">
      {/* TRÁI: Text sent to AI */}
      <div className="flex-1 flex flex-col gap-4 min-w-0">
        <h4 className="text-xs font-bold text-gray-500 uppercase tracking-widest">Text sent to AI</h4>
        <div className="bg-white p-4 rounded-xl border border-gray-200 text-sm text-gray-700 leading-relaxed max-h-96 overflow-y-auto whitespace-pre-wrap shadow-inner">
          {row.content_fed_to_ai || 'No body content available.'}
        </div>
        <div className="flex items-center gap-4 text-xs font-medium text-gray-400 uppercase tracking-wider">
          <span>{row.model_version}</span>
          <span>•</span>
          <span>Prompt: {row.prompt_version}</span>
          <span>•</span>
          <span>{row.published_at ? new Date(row.published_at).toLocaleDateString('en-GB') : 'Unknown date'}</span>
        </div>
      </div>

      {/* PHẢI: Correct the scores */}
      <div className="flex-1 flex flex-col gap-6">
        <div className="flex flex-col gap-4">
          <h4 className="text-xs font-bold text-gray-500 uppercase tracking-widest">Correct the scores</h4>
          
          <div className="flex flex-col gap-3">
            {currentTickers.map(t => {
               const originalScore = aiOriginalTickers.get(t.ticker);
               const isChanged = parseFloat(tickerScores[String(t.ticker)] || '0') !== t.score;
               return (
                 <div key={String(t.ticker)} className="flex items-center justify-between bg-white p-3 rounded-lg border border-gray-200">
                   <div className="flex flex-col">
                     <span className="font-bold text-navy-900">{String(t.ticker)}</span>
                     <span className="text-[10px] uppercase tracking-widest text-gray-400">Ticker</span>
                   </div>
                   <div className="flex items-center gap-4">
                     <div className="flex flex-col items-end">
                       <span className="text-[10px] text-gray-400 uppercase font-bold tracking-widest mb-1">AI Original</span>
                       <span className="text-sm font-bold text-gray-400">{fmt(originalScore)}</span>
                     </div>
                     <input
                       type="text"
                       value={tickerScores[String(t.ticker)]}
                       onChange={(e) => setTickerScores({...tickerScores, [String(t.ticker)]: e.target.value})}
                       className={`w-20 px-3 py-1.5 text-right font-bold rounded border focus:outline-none focus:ring-2 transition-all ${
                         isChanged ? 'bg-yellow-50 border-brand-yellow text-navy-900 focus:ring-brand-yellow/50' : 'bg-gray-50 border-gray-200 text-gray-700 focus:border-brand-dark'
                       }`}
                     />
                   </div>
                 </div>
               );
            })}

            {currentConcepts.map(c => {
               const originalScore = aiOriginalConcepts.get(c.concept);
               const isChanged = parseFloat(conceptScores[String(c.concept)] || '0') !== c.score;
               return (
                 <div key={String(c.concept)} className="flex items-center justify-between bg-white p-3 rounded-lg border border-gray-200">
                   <div className="flex flex-col">
                     <span className="font-bold text-navy-900 truncate max-w-30" title={String(c.concept)}>{String(c.concept)}</span>
                     <span className="text-[10px] uppercase tracking-widest text-gray-400">Concept</span>
                   </div>
                   <div className="flex items-center gap-4">
                     <div className="flex flex-col items-end">
                       <span className="text-[10px] text-gray-400 uppercase font-bold tracking-widest mb-1">AI Original</span>
                       <span className="text-sm font-bold text-gray-400">{fmt(originalScore)}</span>
                     </div>
                     <input
                       type="text"
                       value={conceptScores[String(c.concept)]}
                       onChange={(e) => setConceptScores({...conceptScores, [String(c.concept)]: e.target.value})}
                       className={`w-20 px-3 py-1.5 text-right font-bold rounded border focus:outline-none focus:ring-2 transition-all ${
                         isChanged ? 'bg-yellow-50 border-brand-yellow text-navy-900 focus:ring-brand-yellow/50' : 'bg-gray-50 border-gray-200 text-gray-700 focus:border-brand-dark'
                       }`}
                     />
                   </div>
                 </div>
               );
            })}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <h4 className="text-xs font-bold text-gray-500 uppercase tracking-widest">Error Type</h4>
          <ErrorTypePicker selected={errorType} onChange={setErrorType} />
        </div>

        {errorMsg && <div className="text-sm font-medium text-red-500">{errorMsg}</div>}

        <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-200 mt-2">
          <button onClick={handleCancel} disabled={isSubmitting} className="px-5 py-2 text-sm font-bold text-gray-600 hover:text-navy-900 transition-colors">
            Cancel
          </button>
          <button 
            onClick={handleSave} 
            disabled={!canSave || isSubmitting}
            className="px-6 py-2 bg-navy-900 hover:bg-brand-dark text-white text-sm font-bold rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? 'Saving...' : 'Save correction'}
          </button>
        </div>
      </div>
    </div>
  );
}