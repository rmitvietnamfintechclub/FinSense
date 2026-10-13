'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';

type TokenResponse = {
  access_token: string;
};

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await apiClient<TokenResponse>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });

      // Lưu token và redirect sang Audit Queue
      localStorage.setItem('admin_token', response.access_token);

      // Chuyển hướng dẫn trong client bằng Next.js router
      router.push('/audit');
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Invalid email or password.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto mt-20 bg-white p-8 rounded-2xl border border-gray-200 shadow-sm">
      <div className="text-center mb-8">
        <h1 className="text-2xl font-black text-navy-900 mb-2">Admin Sign-in</h1>
        <p className="text-sm text-gray-500">Sign in to access the audit queue.</p>
      </div>

      {error && (
        <div className="mb-6 p-3 bg-red-50 border border-red-100 text-red-600 text-sm font-medium rounded-lg text-center">
          {error}
        </div>
      )}

      <form onSubmit={handleLogin} className="flex flex-col gap-5">
        <div>
          <label className="block text-xs font-bold tracking-widest text-gray-500 uppercase mb-2">Email / Username</label>
          <input 
            type="text" 
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:border-brand-dark focus:ring-2 focus:ring-brand-yellow/20 outline-none transition-all"
            placeholder="admin@finsense.vn"
            required
          />
        </div>
        
        <div>
          <label className="block text-xs font-bold tracking-widest text-gray-500 uppercase mb-2">Password</label>
          <input 
            type="password" 
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:border-brand-dark focus:ring-2 focus:ring-brand-yellow/20 outline-none transition-all"
            placeholder="••••••••"
            required
          />
        </div>

        <button 
          type="submit" 
          disabled={loading}
          className="mt-2 w-full bg-navy-900 hover:bg-brand-dark text-white font-bold py-3.5 rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}