'use client';

import React, { useState, useEffect } from 'react';
import { Search } from 'lucide-react';

export function AuditFilters({
  status,
  sort,
  search,
  onChange,
}: {
  status: string;
  sort: string;
  search: string;
  onChange: (updates: Record<string, string>) => void;
}) {
  const [localSearch, setLocalSearch] = useState(search);

  // Debounce logic cho ô Search
  useEffect(() => {
    const timeout = setTimeout(() => {
      if (localSearch !== search) {
        onChange({ search: localSearch, page: '1' }); // Search mới thì luôn reset về trang 1
      }
    }, 400);
    return () => clearTimeout(timeout);
  }, [localSearch, search, onChange]);

  return (
    <div className="flex flex-col md:flex-row gap-4 justify-between items-start md:items-center bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
      {/* Ô tìm kiếm */}
      <div className="relative w-full md:w-80">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          value={localSearch}
          onChange={(e) => setLocalSearch(e.target.value)}
          placeholder="Search ticker or title..."
          className="w-full pl-9 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:bg-white focus:border-brand-dark focus:ring-2 focus:ring-brand-yellow/20 outline-none transition-all"
        />
      </div>

      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 w-full md:w-auto">
        {/* Sort Control */}
        <select
          value={sort}
          onChange={(e) => onChange({ sort: e.target.value, page: '1' })}
          className="py-2.5 px-4 bg-gray-50 border border-gray-200 rounded-lg text-sm font-medium text-gray-700 outline-none cursor-pointer focus:bg-white"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="confidence_asc">Lowest AI confidence first</option>
        </select>

        {/* Status Filter */}
        <div className="flex bg-gray-100 p-1 rounded-lg shrink-0">
          {['pending', 'audited', 'all'].map((s) => (
            <button
              key={s}
              onClick={() => onChange({ status: s, page: '1' })}
              className={`px-4 py-1.5 text-sm font-bold rounded-md transition-colors capitalize ${
                status === s
                  ? 'bg-white text-navy-900 shadow-sm'
                  : 'text-gray-500 hover:text-navy-900'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}