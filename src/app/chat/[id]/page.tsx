import React from 'react';
import ChatInterface from './ChatInterface';
import { registry } from '@/core/providers';

export const dynamic = 'force-dynamic';

export default async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const availableModels = await registry.listAvailableModels();

  return <ChatInterface chatId={id} availableModels={availableModels} />;
}
