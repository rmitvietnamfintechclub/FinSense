'use client';

import './globals.css'; // Đảm bảo bạn đã có file CSS Tailwind
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { useEffect } from 'react';
import { LogOut } from 'lucide-react';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { userEmail, isLoading, logout } = useAuth();
  const isLoginPage = pathname === '/login';

  // Requirement: Visiting the page while signed out sends the user to the sign-in page
  useEffect(() => {
    if (!isLoading && !userEmail && !isLoginPage) {
      router.push('/login');
    }
    // Nếu đã login mà cố vào /login thì đá về trang chủ admin (audit queue)
    if (!isLoading && userEmail && isLoginPage) {
      router.push('/audit');
    }
  }, [isLoading, userEmail, isLoginPage, router]);

  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col bg-gray-50 text-gray-900 font-sans">
        
        {/* Top Bar (Hiển thị cho mọi trang, UI thay đổi tùy trang) */}
        <header className="bg-navy-900 text-white w-full">
          <div className="max-w-335 mx-auto px-6 h-16 flex items-center justify-between">
            {/* Left: Logo */}
            <a href="http://localhost:3000" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
              <div className="w-8 h-8 bg-brand-yellow rounded flex items-center justify-center">
                <span className="text-navy-900 font-black tracking-tighter leading-none">FS</span>
              </div>
              <span className="font-bold tracking-widest uppercase text-sm">Fin-Sense</span>
            </a>

            {/* Middle: Search Box (Chỉ hiện ở Admin Panel nếu cần, nhưng UI mockup FE-04 đòi Toolbar riêng nên ở đây để trống) */}
            <div className="flex-1"></div>

            {/* Right: Auth Status */}
            {!isLoginPage && userEmail && (
              <div className="flex items-center gap-4">
                <span className="px-2 py-0.5 bg-brand-yellow text-navy-900 text-[10px] font-black uppercase tracking-widest rounded-sm">
                  Admin
                </span>
                <span className="text-sm font-medium text-gray-300">{userEmail}</span>
                <div className="w-px h-4 bg-gray-700 mx-2"></div>
                <button 
                  onClick={logout}
                  className="flex items-center gap-2 text-sm font-medium text-gray-400 hover:text-white transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 max-w-335 w-full mx-auto p-6 md:p-8">
          {isLoading ? (
            <div className="h-64 flex items-center justify-center">
              <div className="w-8 h-8 border-4 border-navy-900 border-t-transparent rounded-full animate-spin"></div>
            </div>
          ) : (
             children
          )}
        </main>
        
      </body>
    </html>
  );
}