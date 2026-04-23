import type { SearchMode } from '@/types/search';
import type { OrchestrationPlan, ExecutionSurfaceSnapshot } from '@/core/orchestration';
import type { RuntimeSettings } from '@/core/runtime-settings';

export type OperatorSource =
  | 'web'
  | 'telegram'
  | 'whatsapp_cloud'
  | 'whatsapp_baileys'
  | 'imessage_bluebubbles'
  | 'voice'
  | 'cli';

export type OperatorRequest = {
  source: OperatorSource;
  text: string;
  mode?: SearchMode;
  modelId?: string;
  conversationId?: string;
  messageId?: string;
  userId?: string;
  displayName?: string;
  metadata?: Record<string, string>;
};

export type OperatorResponse = {
  text: string;
  sources: Array<{ url: string; title: string }>;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  settings: RuntimeSettings;
  modelId: string;
};
