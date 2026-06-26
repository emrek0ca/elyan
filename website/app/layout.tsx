import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Elyan',
  description: 'Elyan official website.'
};

import { PreferencesProvider } from '@/lib/preferences-context';

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html data-scroll-behavior="smooth" lang="tr" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <PreferencesProvider>
          {children}
        </PreferencesProvider>
      </body>
    </html>
  );
}
