'use client';

import React from 'react';

const ERROR_TYPES = [
  "No error",
  "Wrong magnitude",
  "Wrong direction",
  "Wrong ticker",
  "Missed ticker"
];

export function ErrorTypePicker({
  selected,
  onChange
}: {
  selected: string | null;
  onChange: (type: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {ERROR_TYPES.map(type => (
        <button
          key={type}
          type="button"
          onClick={() => onChange(type)}
          className={`px-3 py-1.5 text-xs font-bold rounded-md transition-colors border ${
            selected === type 
              ? 'bg-navy-900 border-navy-900 text-brand-yellow' 
              : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
          }`}
        >
          {type}
        </button>
      ))}
    </div>
  );
}