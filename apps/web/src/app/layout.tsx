import './globals.css';
import { MainLayout } from '@/components/layout/MainLayout';

export const metadata = {
  title: 'Elyan - Operator Runtime',
  description: 'Local-first operator runtime for capabilities, approvals, routing, and optional hosted control surfaces.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <MainLayout>
          {children}
        </MainLayout>
      </body>
    </html>
  );
}
