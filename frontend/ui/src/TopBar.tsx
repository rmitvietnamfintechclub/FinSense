import React from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { LogOut, ShieldCheck } from 'lucide-react';
import { SearchBox } from './SearchBox';

interface TopBarProps {
  isAdmin?: boolean;
  adminEmail?: string;
  onSignOut?: () => void;
  lastUpdated?: string; // e.g. "10:30 AM"
}

export function TopBar({ isAdmin, adminEmail, onSignOut, lastUpdated }: TopBarProps) {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-40">
      <div className="max-w-335 mx-auto px-6 h-16 flex items-center justify-between gap-8">
        
        <div className="shrink-0">
          <Link href="/" className="hover:opacity-80 transition-opacity block">
            <Image 
              src="https://d2uq10394z5icp.cloudfront.net/global/FTC-DefaultLogo-NoName.svg"
              alt="FIN-SENSE Logo" 
              width={160}
              height={40} 
              priority 
              className="w-auto h-8" 
            />
          </Link>
        </div>

        <div className="flex-1 flex justify-center">
          <SearchBox />
        </div>

        <div className="shrink-0 flex items-center gap-4 text-sm">
          {isAdmin ? (
            <>
              <div className="flex items-center gap-2 px-3 py-1.5 bg-brand-yellow/10 text-brand-dark rounded-full font-medium text-xs border border-brand-yellow/30">
                <ShieldCheck className="w-4 h-4" /> ADMIN
              </div>
              <span className="text-gray-800 font-medium hidden md:block">{adminEmail || 'admin@domain.com'}</span>
              <button 
                onClick={onSignOut}
                className="flex items-center gap-2 text-gray-600 hover:text-navy-900 transition-colors"
              >
                <LogOut className="w-4 h-4" />
                <span className="hidden md:block">Sign out</span>
              </button>
            </>
          ) : (
            <div className="text-right hidden md:block">
              <div className="text-gray-800 font-medium">Updated {lastUpdated || '--:--'}</div>
              <div className="text-xs text-gray-500">Auto-refreshes every 30 min</div>
            </div>
          )}
        </div>
        
      </div>
    </header>
  );
}