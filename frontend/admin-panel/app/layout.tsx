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
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900 font-sans">
        
        <TopBar adminEmail="admin@rmit.edu.vn" isAdmin={true} />

        <PageShell>
          {children}
        </PageShell>

        <footer className="mt-auto py-6 text-center text-sm text-gray-500">
          Measures news coverage tone, not a buy/sell signal.
        </footer>
        
      </body>
    </html>
  );
}