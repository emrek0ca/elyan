import ChatInterface from '../[id]/ChatInterface';
import { registry } from '@/core/providers';
import { SearchMode } from '@/types/search';

export const dynamic = 'force-dynamic';

export default async function NewChatPage({
  searchParams,
}: {
  searchParams?: Promise<{ q?: string; mode?: string }>;
}) {
  const params = searchParams ? await searchParams : {};
  const initialMode: SearchMode = params.mode === 'research' ? 'research' : 'speed';
  const availableModels = await registry.listAvailableModels();

  return (
    <ChatInterface
      initialQuery={params.q || ''}
      initialMode={initialMode}
      availableModels={availableModels}
    />
  );
}
