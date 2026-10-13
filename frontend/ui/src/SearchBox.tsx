'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Search } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { components } from '@finsense/types/generated/api.types';
import { apiClient } from './api-client';

type TickerDirectoryEntry = components['schemas']['TickerDirectoryEntry'];
type TickerDirectoryResponse = components['schemas']['TickerDirectory'];

export function SearchBox() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const [tickers, setTickers] = useState<TickerDirectoryEntry[]>([]);
  // const [isLoading, setIsLoading] = useState(false); // Dùng để làm skeleton/spinner nếu cần

  useEffect(() => {
    let isMounted = true;
    
    async function fetchTickers() {
      try {
        const data = await apiClient<TickerDirectoryResponse>('/tickers');
        if (isMounted && data.tickers) {
          setTickers(data.tickers);
        }
      } catch (error) {
        console.error("Failed to load ticker directory:", error);
      }
    }

    fetchTickers();
    return () => { isMounted = false; };
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filteredResults = query.trim().length > 0
    ? tickers.filter((t) => {
        const lowerQuery = query.toLowerCase().trim();
        return (
          t.ticker.toLowerCase().includes(lowerQuery) ||
          t.company_name.toLowerCase().includes(lowerQuery)
        );
      })
    : [];

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') setIsOpen(false);
    if (e.key === 'Enter' && filteredResults.length > 0) {
      router.push(`/ticker/${filteredResults[0].ticker}`);
      setIsOpen(false);
      setQuery(''); // Reset query sau khi chuyển trang
    }
  };

  return (
    <div ref={wrapperRef} className="relative w-full max-w-xl">
      <div className="relative flex items-center">
        <Search className="absolute left-3 text-gray-500 w-4 h-4" />
        <input
          type="text"
          className="w-full bg-gray-100 border-none rounded-lg py-2.5 pl-10 pr-4 text-sm focus:ring-2 focus:ring-brand-yellow focus:outline-none transition-all placeholder:text-gray-500"
          placeholder="e.g. HPG, Hoa Phat Group"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsOpen(true)}
        />
      </div>

      {isOpen && query.length > 0 && (
        <div className="absolute top-full left-0 w-full mt-2 bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden z-50">
          {filteredResults.length > 0 ? (
            <ul className="max-h-64 overflow-y-auto">
              {filteredResults.map((item) => (
                <li key={item.ticker}>
                  <button
                    onClick={() => {
                      router.push(`/ticker/${item.ticker}`);
                      setIsOpen(false);
                      setQuery('');
                    }}
                    className="w-full text-left px-4 py-3 hover:bg-gray-50 flex items-baseline gap-3 transition-colors"
                  >
                    <span className="font-bold text-navy-900">{item.ticker}</span>
                    <span className="text-sm text-gray-600 truncate">{item.company_name}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="px-4 py-3 text-sm text-gray-500">No ticker found</div>
          )}
        </div>
      )}
    </div>
  );
}