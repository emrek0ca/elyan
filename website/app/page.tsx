'use client';

import { useEffect } from 'react';

export default function RootPage() {
  useEffect(() => {
    window.location.replace('/tr/');
  }, []);

  return (
    <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--background)' }}>
      <p style={{ color: 'var(--text-muted)' }}>Yönlendiriliyor / Redirecting...</p>
    </div>
  );
}
