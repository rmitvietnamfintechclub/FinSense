import React from 'react';

interface PageShellProps {
  children: React.ReactNode;
}

export function PageShell({ children }: PageShellProps) {
  return (
    <main className="max-w-335 mx-auto px-6 py-8 w-full">
      {children}
    </main>
  );
}