'use client';

import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { ADMIN_TOKEN_KEY } from '@finsense/ui';

// localStorage is the store; useSyncExternalStore gives every component the same value and
// renders the server snapshot (null) during hydration, so server and client HTML match.
const listeners = new Set<() => void>();

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener('storage', onChange); // other tabs
  return () => {
    listeners.delete(onChange);
    window.removeEventListener('storage', onChange);
  };
}

function notify() {
  listeners.forEach((l) => l());
}

const getToken = () => localStorage.getItem(ADMIN_TOKEN_KEY);
const getServerToken = () => null;
const subscribeNever = () => () => {};

// Display only — the API verifies the signature on every audit call.
function decodeUsername(token: string): string | null {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join('')
    );
    const username = JSON.parse(json)?.username;
    return typeof username === 'string' ? username : null;
  } catch {
    return null; // malformed token = signed out; the effect below removes it
  }
}

export function useAuth() {
  const router = useRouter();
  const token = useSyncExternalStore(subscribe, getToken, getServerToken);
  const isReady = useSyncExternalStore(subscribeNever, () => true, () => false);
  const userEmail = token ? decodeUsername(token) : null;

  useEffect(() => {
    if (token && !userEmail) {
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      notify();
    }
  }, [token, userEmail]);

  const login = useCallback((newToken: string) => {
    localStorage.setItem(ADMIN_TOKEN_KEY, newToken);
    notify();
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    notify();
    router.push('/admin/login');
  }, [router]);

  return { userEmail, isReady, login, logout };
}
