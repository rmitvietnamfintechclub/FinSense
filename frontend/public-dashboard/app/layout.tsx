import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TopBar, PageShell } from "@finsense/ui";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FIN-SENSE | News Sentiment",
  description: "How Vietnamese financial news is covering the market.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* 
        Thêm bg-gray-50 và text-gray-900 để đảm bảo màu nền/chữ luôn chuẩn 
        Cho font-sans để áp dụng font Geist mặc định 
      */}
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900 font-sans">
        
        {/* Top Bar dùng chung (Tạm thời hardcode lastUpdated chờ API) */}
        <TopBar lastUpdated="10:30 AM" />

        {/* Cấu trúc PageShell giới hạn max-width 1340px theo requirement */}
        <PageShell>
          {children}
        </PageShell>

        {/* Dòng Disclaimer bắt buộc của FE-01 */}
        <footer className="mt-auto py-6 text-center text-sm text-gray-500">
          Measures news coverage tone, not a buy/sell signal.
        </footer>
        
      </body>
    </html>
  );
}