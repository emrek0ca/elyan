export interface RenderHints {
  tone?: 'neutral' | 'caution' | 'streaming';
  density?: 'compact' | 'regular';
  expandable?: boolean;
  sectionRole?: 'detail';
}

export interface ChatMessageBlock {
  type: string;
  markdown?: string;
  title?: string;
  summary?: string;
  detail?: string;
  items?: string[] | { label: string; value: string; confidence?: number }[];
  status?: 'running' | 'waiting_approval' | 'needs_desktop' | 'completed' | 'failed' | 'retrying' | 'degraded';
  kind?: string;
  stableBlockId?: string;
  visibility?: 'user_visible' | 'assistant_internal_by_default';
  confidence?: number;
  priority?: number;
  cacheDigest?: string;
  renderHints?: RenderHints;
  raw?: Record<string, any>;
}

const assistantTextBlockType = 'text';
const elyanIdentityFallback =
  'Ben Elyan. Görevleri güvenli, anlaşılır ve düzenli şekilde planlayıp yürüten bütünleşik bir yapay zeka sistemiyim.';

function normalizeBlockType(type: string): string {
  switch (type.trim().toLowerCase()) {
    case 'formula':
    case 'latex':
      return 'math';
    case 'dynamic_chart':
    case 'graph':
    case 'echarts':
      return 'chart';
    case 'colored_table':
    case 'data_table':
      return 'table';
    case 'attachment':
    case 'document':
    case 'image':
      return 'file';
    default:
      return type.trim().toLowerCase() || assistantTextBlockType;
  }
}

function sanitizeAssistantVisibleText(value: string): string {
  const normalized = value.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!normalized) return '';

  const lower = normalized.toLocaleLowerCase('tr-TR');
  const mentionsElyan = lower.includes('elyan');
  const exposesInternalIdentity =
    lower.includes('iç model') ||
    lower.includes('model provider') ||
    lower.includes('sağlayıcı') ||
    lower.includes('provider') ||
    lower.includes('routing') ||
    lower.includes('gizli prompt') ||
    lower.includes('system prompt');

  if (mentionsElyan && exposesInternalIdentity) {
    return elyanIdentityFallback;
  }

  return normalized;
}

function normalizeMarkdown(value?: string | null): string {
  if (!value) return '';
  return sanitizeAssistantVisibleText(value);
}

export function parseAssistantMessageBlock(raw: any): ChatMessageBlock | null {
  if (typeof raw === 'string') {
    const markdown = normalizeMarkdown(raw);
    if (!markdown) return null;
    return { type: assistantTextBlockType, markdown, visibility: 'user_visible' };
  }
  
  if (typeof raw !== 'object' || !raw) return null;

  const rawType = typeof raw.type === 'string'
    ? raw.type
    : typeof raw.kind === 'string'
      ? raw.kind
      : assistantTextBlockType;
  const type = normalizeBlockType(rawType);
  
  // Filter out internal blocks immediately
  if (raw.visibility === 'assistant_internal_by_default') {
    return null; // Do not render on web surface
  }

  const block: ChatMessageBlock = {
    type,
    raw,
    visibility: raw.visibility || 'user_visible',
    stableBlockId: raw.stableBlockId,
    confidence: raw.confidence,
    priority: raw.priority,
    cacheDigest: raw.cacheDigest,
    renderHints: raw.renderHints,
  };

  if (raw.title) block.title = raw.title;
  if (raw.summary) block.summary = raw.summary;
  if (raw.detail) block.detail = raw.detail;
  if (raw.status) block.status = raw.status;
  if (raw.kind) block.kind = raw.kind;
  if (raw.items) block.items = raw.items;

  if (type === 'text') {
    block.markdown = normalizeMarkdown(raw.markdown || raw.text || raw.content || raw.body || raw.message);
    if (!block.markdown) return null;
  } else if (raw.markdown) {
    block.markdown = normalizeMarkdown(raw.markdown);
  }

  return block;
}

export function parseMessageBlocksFromJson(
  json: any,
  fallbacks: (string | null | undefined)[] = []
): ChatMessageBlock[] {
  if (!json || typeof json !== 'object') {
    return fallbackToTextBlocks(fallbacks);
  }

  // Canonical blocks protocol
  const blocksArray = Array.isArray(json.blocks) ? json.blocks : [];
  if (blocksArray.length > 0) {
    return blocksArray
      .map(parseAssistantMessageBlock)
      .filter((b: any): b is ChatMessageBlock => b !== null);
  }

  // If no blocks, fallback to standard text mapping
  const content = json.content || json.text || json.message;
  if (content) {
    return fallbackToTextBlocks([content]);
  }

  return fallbackToTextBlocks(fallbacks);
}

function fallbackToTextBlocks(fallbacks: (string | null | undefined)[]): ChatMessageBlock[] {
  for (const fallback of fallbacks) {
    const normalized = normalizeMarkdown(fallback);
    if (normalized) {
      return [{ type: assistantTextBlockType, markdown: normalized, visibility: 'user_visible' }];
    }
  }
  return [];
}
