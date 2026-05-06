import React from 'react';
import { MainLayoutClient } from './MainLayoutClient';

export function MainLayout({ children }: { children: React.ReactNode }) {
  return <MainLayoutClient>{children}</MainLayoutClient>;
}
