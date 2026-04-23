import './globals.css';
import { MainLayout } from '@/components/layout/MainLayout';

export const metadata = {
  title: 'Elyan - Local-First Personal Agent Runtime',
  description: 'Local-first personal agent runtime with hosted access, citations, control-plane billing, and app-connected operator routing.',
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
