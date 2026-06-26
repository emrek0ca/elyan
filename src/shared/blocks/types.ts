import type { JsonMap, JsonValue } from '../protocol';

export type ElyanBlockType =
  | 'text'
  | 'code'
  | 'table'
  | 'chart'
  | 'file'
  | 'task_trace'
  | 'approval'
  | 'artifact'
  | 'terminal'
  | 'browser'
  | 'desktop_action'
  | 'error';

export type ElyanBlockStatus =
  | 'streaming'
  | 'queued'
  | 'planning'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'waiting_approval'
  | 'canceled';

export interface ElyanBlockBase {
  type: ElyanBlockType | string;
  version?: number;
  status?: ElyanBlockStatus | string;
  title?: string;
  summary?: string;
  mobileFallback?: ElyanTextBlock | ElyanUnknownBlock;
  [key: string]: unknown;
}

export interface ElyanTextBlock extends ElyanBlockBase {
  type: 'text';
  markdown: string;
}

export interface ElyanCodeBlock extends ElyanBlockBase {
  type: 'code';
  code?: string;
  language?: string;
  filename?: string;
}

export interface ElyanTableBlock extends ElyanBlockBase {
  type: 'table';
  columns?: JsonValue[];
  rows?: JsonValue[];
}

export interface ElyanChartBlock extends ElyanBlockBase {
  type: 'chart';
  chartType?: 'line' | 'bar' | 'pie' | string;
  spec?: JsonMap;
  points?: JsonValue[];
}

export interface ElyanFileBlock extends ElyanBlockBase {
  type: 'file';
  fileId?: string;
  name?: string;
  mime?: string;
  mimeType?: string;
  size?: number;
  sizeBytes?: number;
  previewUrl?: string;
}

export interface ElyanTaskTraceBlock extends ElyanBlockBase {
  type: 'task_trace';
  intent?: string;
  route?: string;
  steps?: JsonValue[];
}

export interface ElyanApprovalBlock extends ElyanBlockBase {
  type: 'approval';
  approvalId?: string;
  riskLevel?: string;
  actionSummary?: string;
}

export interface ElyanArtifactBlock extends ElyanBlockBase {
  type: 'artifact';
  artifactId?: string;
  mime?: string;
  mimeType?: string;
}

export interface ElyanTerminalBlock extends ElyanBlockBase {
  type: 'terminal';
  output?: string;
  lines?: JsonValue[];
  maxVisibleLines?: number;
}

export interface ElyanBrowserBlock extends ElyanBlockBase {
  type: 'browser';
  currentUrl?: string;
  screenshotUrl?: string;
}

export interface ElyanDesktopActionBlock extends ElyanBlockBase {
  type: 'desktop_action';
  actionId?: string;
  app?: string;
}

export interface ElyanErrorBlock extends ElyanBlockBase {
  type: 'error';
  code?: string;
  message?: string;
  retryActionId?: string;
}

export interface ElyanMemoryEchoBlock extends ElyanBlockBase {
  type: 'memory_echo' | 'memory_surface' | 'memory_recall';
  recall?: string;
  question?: string;
  confidence?: number;
}

export interface ElyanProactiveTouchBlock extends ElyanBlockBase {
  type: 'proactive_touch' | 'proactive' | 'proactive_surface';
  suggestion?: string;
  cta?: string;
  context?: string;
}

export interface ElyanUnknownBlock extends ElyanBlockBase {
  type: string;
}

export type ElyanBlock =
  | ElyanTextBlock
  | ElyanCodeBlock
  | ElyanTableBlock
  | ElyanChartBlock
  | ElyanFileBlock
  | ElyanTaskTraceBlock
  | ElyanApprovalBlock
  | ElyanArtifactBlock
  | ElyanTerminalBlock
  | ElyanBrowserBlock
  | ElyanDesktopActionBlock
  | ElyanErrorBlock
  | ElyanMemoryEchoBlock
  | ElyanProactiveTouchBlock
  | ElyanUnknownBlock;

export interface ElyanMessage {
  id: string;
  sessionId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  blocks?: ElyanBlock[];
  status?: 'streaming' | 'completed' | 'failed' | string;
  createdAt: string;
}

export function isElyanBlock(value: unknown): value is ElyanBlock {
  return Boolean(value && typeof value === 'object' && typeof (value as { type?: unknown }).type === 'string');
}

export function normalizeElyanBlocks(value: unknown): ElyanBlock[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item): ElyanBlock | null => {
      if (typeof item === 'string') {
        return { type: 'text', markdown: item, version: 1 };
      }
      if (!item || typeof item !== 'object') {
        return null;
      }
      const record = item as Record<string, JsonValue | undefined>;
      const rawType = String(record.type ?? record.kind ?? '').trim();
      if (!rawType) {
        return null;
      }
      return { ...record, type: rawType } as ElyanBlock;
    })
    .filter((item): item is ElyanBlock => item !== null);
}

export function fallbackTextBlock(content: string): ElyanTextBlock[] {
  const markdown = String(content || '').trim();
  return markdown ? [{ type: 'text', markdown, version: 1 }] : [];
}
