'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { TopBar, apiClient } from '@finsense/ui';
import type { components } from '@finsense/types/generated/api.types';
import { useAuth } from '@/features/auth/useAuth';
import { formatTime } from '@/lib/formatters';

type DashboardSummary = components['schemas']['DashboardSummary'];

const REFRESH_MS = 60 * 60 * 1000; // the header promises "Auto-refreshes every 1 hour"

export function HeaderBar() {
  const { userEmail, logout } = useAuth();
  const onAdminPage = usePathname().startsWith('/admin');
  const signedIn = userEmail !== null;
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  useEffect(() => {
    // The status describes dashboard data, which admin pages don't show.
    if (onAdminPage) return;
    let cancelled = false;
    const load = () =>
      apiClient<DashboardSummary>('/dashboard/summary')
        .then((summary) => {
          if (!cancelled) setLastUpdated(summary.last_updated ?? null);
        })
        .catch((err) => console.error('Failed to fetch last updated time:', err));
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [onAdminPage]);

  const navLink = onAdminPage
    ? { href: '/', label: 'Dashboard' }
    : signedIn
      ? { href: '/admin/audit', label: 'Audit queue' }
      : { href: '/admin/login', label: 'Admin sign-in' };

  return (
    <TopBar
      lastUpdated={onAdminPage ? undefined : formatTime(lastUpdated)}
      isAdmin={signedIn}
      adminEmail={userEmail ?? undefined}
      onSignOut={logout}
      navLink={navLink}
    />
  );
}
