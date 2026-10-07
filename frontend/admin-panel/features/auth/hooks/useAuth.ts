'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

function decodeJWT(token: string) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(window.atob(base64).split('').map(function(c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
    return JSON.parse(jsonPayload);
  } catch (e) {
    return null;
  }
}

function getInitialUserEmail() {
  if (typeof window === 'undefined') {
    return null;
  }

  const token = window.localStorage.getItem('admin_token');
  if (!token) {
    return null;
  }

  const payload = decodeJWT(token);
  if (payload?.username) {
    return payload.username;
  }

  window.localStorage.removeItem('admin_token');
  return null;
}

export function useAuth() {
  const router = useRouter();
  const [userEmail, setUserEmail] = useState<string | null>(getInitialUserEmail);
  const isLoading = false;

  const logout = () => {
    localStorage.removeItem('admin_token');
    setUserEmail(null);
    router.push('/login');
  };

  return { userEmail, isLoading, logout };
}