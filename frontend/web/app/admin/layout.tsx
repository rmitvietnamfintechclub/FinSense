'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/useAuth';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { userEmail, isReady } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname === '/admin/login';
  const signedIn = userEmail !== null;

  useEffect(() => {
    if (!isReady) return;
    if (!signedIn && !isLoginPage) router.replace('/admin/login');
    if (signedIn && isLoginPage) router.replace('/admin/audit');
  }, [isReady, signedIn, isLoginPage, router]);

  // Render nothing until we know, so a signed-out visitor never sees an audit frame.
  // Navigation convenience only — the API enforces auth on every /audit call.
  const allowed = isReady && (isLoginPage ? !signedIn : signedIn);
  return allowed ? <>{children}</> : null;
}
