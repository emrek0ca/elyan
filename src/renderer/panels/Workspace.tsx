import { useEffect, useLayoutEffect, useRef, useState, useMemo, type ReactElement, type ClipboardEvent, type DragEvent, type MouseEvent } from 'react';
import type { BootstrapSnapshot, RuntimeArtifact } from '../../shared/protocol';
import { getDesktopApi } from '../desktop-api';
import {
  asArray,
  asRecord,
  asString,
  selectedConversation,
  stateRecord,
  runtimeRecord,
  runtimeSessionConnectionRecord,
  runtimeSessionDeviceRecord,
  runtimeSessionReadinessRecord,
} from '../lib/data';
import { getRandomGreeting } from '../lib/greetings';
import { useDictation } from '../hooks/useDictation';
import type { DesktopTaskShellView } from '../lib/desktop-task-shell';
import type { ListSurfaceItem } from './ListSurface';
import { normalizeElyanBlocks } from '../../shared/blocks/types';
import { BlockListRenderer } from '../chat/blocks/BlockRenderer';

import img2 from '../assets/new_chat/2.png';
import img3 from '../assets/new_chat/3.png';
import img4 from '../assets/new_chat/4.png';
import img5 from '../assets/new_chat/5.png';
import img6 from '../assets/new_chat/6.png';
import img7 from '../assets/new_chat/7.png';
import img8 from '../assets/new_chat/8.png';

const NEW_CHAT_IMAGES = [img2, img3, img4, img5, img6, img7, img8];

type ComposerAttachment = RuntimeArtifact & { sizeBytes: number };
type MessageContextMenuState = {
  x: number;
  y: number;
  text: string;
};

const ASSISTANT_BLOCK_TYPE_ALIASES: Record<string, string> = {
  colored_table: 'table',
  data_table: 'table',
  dynamic_chart: 'chart',
  echarts: 'chart',
  formula: 'math',
  graph: 'chart',
  latex: 'math',
};

const SUPPORTED_ASSISTANT_BLOCK_TYPES = new Set([
  'text',
  'summary',
  'next_steps',
  'status',
  'task_trace',
  'attachment_context',
  'context_signal',
  'actionable',
  'block_group',
  'code',
  'table',
  'chart',
  'file',
  'math',
  'artifact',
]);

function normalizeAssistantBlockType(value: unknown): string {
  const type = asString(value).trim().toLowerCase();
  return ASSISTANT_BLOCK_TYPE_ALIASES[type] ?? type;
}

function renderableAssistantBlocks(value: unknown): Record<string, unknown>[] {
  const blocks = asArray(value)
    .map((item) => {
      if (typeof item === 'string') {
        return { type: 'text', markdown: item };
      }
      const block = asRecord(item);
      const type = normalizeAssistantBlockType(block.type ?? block.kind);
      return type ? { ...block, type } : block;
    })
    .filter((block) => (
      asString(block.visibility).trim().toLowerCase() !== 'assistant_internal_by_default' &&
      SUPPORTED_ASSISTANT_BLOCK_TYPES.has(normalizeAssistantBlockType(block.type))
    ));
  return mergeAdjacentTextBlocks(blocks);
}

function mergeAdjacentTextBlocks(blocks: Record<string, unknown>[]): Record<string, unknown>[] {
  const merged: Record<string, unknown>[] = [];
  for (const block of blocks) {
    const type = asString(block.type).trim();
    const previous = merged.at(-1);
    if (type === 'text' && previous && asString(previous.type).trim() === 'text') {
      const previousBody = blockBody(previous);
      const nextBody = blockBody(block);
      merged[merged.length - 1] = {
        ...previous,
        markdown: [previousBody, nextBody].filter(Boolean).join('\n\n'),
      };
      continue;
    }
    merged.push(block);
  }
  return merged;
}

function compactForCompletenessCompare(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function hasOddTokenCount(value: string, token: string): boolean {
  let count = 0;
  let start = 0;
  while (true) {
    const index = value.indexOf(token, start);
    if (index < 0) return count % 2 === 1;
    count += 1;
    start = index + token.length;
  }
}

function looksLikeIncompleteAssistantTail(value: string): boolean {
  const text = value.trimEnd();
  if (!text) return true;
  if (hasOddTokenCount(text, '```') || hasOddTokenCount(text, '~~~') || hasOddTokenCount(text, '**') || hasOddTokenCount(text, '__')) {
    return true;
  }
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  const lastLine = lines.at(-1) ?? '';
  const startsListItem = /^(?:[-*+]|\d+[.)])\s+/.test(lastLine);
  const hasTerminalPunctuation = /[.!?:;,\)\]}'">]$/.test(lastLine);
  return startsListItem && !hasTerminalPunctuation && lastLine.length <= 80;
}

function shouldPreferFallbackText(currentText: string, fallbackText: string): boolean {
  const current = currentText.trim();
  const fallback = fallbackText.trim();
  if (!fallback || current === fallback) return false;
  if (!current) return true;
  const compactCurrent = compactForCompletenessCompare(current);
  const compactFallback = compactForCompletenessCompare(fallback);
  if (!compactCurrent || !compactFallback || compactCurrent === compactFallback || compactCurrent.includes(compactFallback)) {
    return false;
  }
  if (compactFallback.includes(compactCurrent) && compactFallback.length > compactCurrent.length) {
    return true;
  }
  if (looksLikeIncompleteAssistantTail(current) && compactFallback.length > compactCurrent.length) {
    return true;
  }
  return compactFallback.length >= compactCurrent.length + 32;
}

function completeAssistantBlocksForDisplay(blocks: Record<string, unknown>[], fallbackText: string): Record<string, unknown>[] {
  if (blocks.length === 0 || !fallbackText.trim()) return blocks;
  const currentText = blocks
    .filter((block) => normalizeAssistantBlockType(block.type) === 'text')
    .map(blockBody)
    .filter(Boolean)
    .join('\n\n');
  if (!shouldPreferFallbackText(currentText, fallbackText)) return blocks;
  const result: Record<string, unknown>[] = [];
  let insertedText = false;
  for (const block of blocks) {
    if (normalizeAssistantBlockType(block.type) === 'text') {
      if (!insertedText) {
        result.push({ ...block, type: 'text', markdown: fallbackText });
        insertedText = true;
      }
      continue;
    }
    if (!insertedText) {
      result.push({ type: 'text', markdown: fallbackText });
      insertedText = true;
    }
    result.push(block);
  }
  return result;
}

function blockData(block: Record<string, unknown>): Record<string, unknown> {
  return asRecord(block.data ?? block.raw);
}

function scalarText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = scalarText(value).trim();
    if (text) return text;
  }
  return '';
}

function blockBody(block: Record<string, unknown>): string {
  const data = blockData(block);
  return (
    firstText(
      block.markdown,
      block.content,
      block.text,
      block.body,
      block.message,
      block.summary,
      block.value,
      block.description,
      data.markdown,
      data.content,
      data.text,
      data.body,
      data.message,
      data.summary,
      data.value,
      data.description,
    )
  ).trim();
}

function blockRenderHints(block: Record<string, unknown>): Record<string, unknown> {
  const data = blockData(block);
  return asRecord(block.renderHints ?? data.renderHints);
}

function numberFrom(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value.replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function cleanStructuredText(value: unknown): string {
  const record = asRecord(value);
  const raw = Object.keys(record).length > 0
    ? firstText(record.value, record.label, record.title, record.text, record.content, record.name, record.key, record.id)
    : scalarText(value);
  return raw
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p\s*>/gi, '\n')
    .replace(/<\/?[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

type TableBlockData = {
  title: string;
  caption: string;
  columns: string[];
  rows: string[][];
  highlightRules: TableHighlightRule[];
};

type TableHighlightRule = {
  column: string;
  match: string;
  tone: 'neutral' | 'success' | 'warning' | 'danger' | 'info';
};

function tableHighlightRules(block: Record<string, unknown>, data: Record<string, unknown>): TableHighlightRule[] {
  const style = asRecord(block.style ?? data.style);
  const rules = asArray(block.highlightRules).length > 0
    ? asArray(block.highlightRules)
    : asArray(data.highlightRules).length > 0
      ? asArray(data.highlightRules)
      : asArray(style.highlightRules);
  return rules
    .map((item): TableHighlightRule | null => {
      const record = asRecord(item);
      const column = firstText(record.column, record.key, record.field);
      const match = firstText(record.match, record.value, record.equals);
      const rawTone = firstText(record.tone, record.variant).toLowerCase();
      const tone: TableHighlightRule['tone'] = ['success', 'warning', 'danger', 'info', 'neutral'].includes(rawTone)
        ? rawTone as TableHighlightRule['tone']
        : 'neutral';
      return column && match ? { column, match, tone } : null;
    })
    .filter((rule): rule is TableHighlightRule => rule !== null);
}

function tableBlockData(block: Record<string, unknown>): TableBlockData {
  const data = blockData(block);
  const title = firstText(block.title, data.title);
  const caption = firstText(block.caption, block.summary, data.caption, data.summary);
  const rawColumns = asArray(block.columns).length > 0
    ? asArray(block.columns)
    : asArray(block.headers).length > 0
      ? asArray(block.headers)
      : asArray(data.columns).length > 0
        ? asArray(data.columns)
        : asArray(data.headers);
  const rawRows = asArray(block.rows).length > 0
    ? asArray(block.rows)
    : asArray(block.items).length > 0
      ? asArray(block.items)
      : asArray(block.data).length > 0
        ? asArray(block.data)
        : asArray(data.rows).length > 0
          ? asArray(data.rows)
          : asArray(data.data).length > 0
            ? asArray(data.data)
            : asArray(data.items);
  const columns = rawColumns.map(cleanStructuredText).filter(Boolean);
  const inferredColumns = columns.length > 0
    ? columns
    : rawRows.reduce<string[]>((acc, row) => {
      if (acc.length > 0) return acc;
      const record = asRecord(row);
      if (Object.keys(record).length > 0) {
        return Object.keys(record).map(cleanStructuredText).filter(Boolean);
      }
      if (Array.isArray(row)) {
        return Array.from({ length: row.length }, (_, index) => `Sütun ${index + 1}`);
      }
      return acc;
    }, []);
  const rows = rawRows
    .map((row) => {
      if (Array.isArray(row)) {
        return row.map(cleanStructuredText);
      }
      const record = asRecord(row);
      if (Object.keys(record).length === 0) {
        const text = cleanStructuredText(row);
        return text ? [text] : [];
      }
      if (inferredColumns.length > 0) {
        const ordered = inferredColumns.map((column) => cleanStructuredText(record[column] ?? record[column.toLowerCase()]));
        if (ordered.some(Boolean)) return ordered;
      }
      return Object.values(record).map(cleanStructuredText);
    })
    .filter((row) => row.some(Boolean));
  const inferredColumnCount = Math.max(inferredColumns.length, ...rows.map((row) => row.length), 0);
  const safeColumns = inferredColumns.length > 0
    ? inferredColumns
    : Array.from({ length: inferredColumnCount }, (_, index) => `Sütun ${index + 1}`);
  return { title, caption, columns: safeColumns, rows, highlightRules: tableHighlightRules(block, data) };
}

type ChartPoint = {
  label: string;
  value: number;
  color: string;
};

type ChartBlockData = {
  title: string;
  chartType: 'bar' | 'line' | 'pie' | 'function';
  points: ChartPoint[];
  expression: string;
  variables: string[];
  range: Record<string, unknown>;
  fixed: Record<string, unknown>;
};

const CHART_COLORS = ['#6f8f72', '#b28b57', '#7f8ea3', '#9b786f', '#5f8f97', '#a27a94'];

function chartBlockData(block: Record<string, unknown>): ChartBlockData {
  const data = blockData(block);
  const title = firstText(block.title, data.title);
  const expression = firstText(block.expression, block.expr, data.expression, data.expr);
  const requestedType = firstText(block.chartType, block.chart_type, block.chartKind, data.chartType, data.chart_type, data.chartKind, data.type).toLowerCase();
  const chartType: ChartBlockData['chartType'] = expression
    ? 'function'
    : requestedType === 'line' || requestedType === 'pie'
      ? requestedType
      : 'bar';
  const rawPoints = asArray(block.points).length > 0
    ? asArray(block.points)
    : asArray(block.values).length > 0
      ? asArray(block.values)
      : asArray(block.items).length > 0
        ? asArray(block.items)
        : asArray(block.data).length > 0
          ? asArray(block.data)
          : asArray(data.points).length > 0
            ? asArray(data.points)
            : asArray(data.data).length > 0
              ? asArray(data.data)
              : asArray(data.items);
  const points = rawPoints
    .map((point, index): ChartPoint | null => {
      const record = asRecord(point);
      const value = numberFrom(record.value ?? record.y ?? record.v ?? record.count ?? record.total);
      if (value === null) return null;
      const label = firstText(record.label, record.x, record.name, record.key) || `${index + 1}`;
      const color = firstText(record.color, record.fill) || CHART_COLORS[index % CHART_COLORS.length]!;
      return { label, value, color };
    })
    .filter((point): point is ChartPoint => point !== null);
  return {
    title,
    chartType,
    points,
    expression,
    variables: asArray(block.variables).length > 0
      ? asArray(block.variables).map(scalarText).filter(Boolean)
      : asArray(data.variables).map(scalarText).filter(Boolean),
    range: asRecord(block.range ?? data.range),
    fixed: asRecord(block.fixed ?? data.fixed),
  };
}

type FileBlockData = {
  name: string;
  mimeType: string;
  uri: string;
  sizeBytes: number | null;
  preview: string;
};

function fileBlockData(block: Record<string, unknown>): FileBlockData {
  const data = blockData(block);
  return {
    name: firstText(block.name, block.filename, block.fileName, data.name, data.filename, data.fileName) || 'Dosya',
    mimeType: firstText(block.mimeType, block.mime_type, block.mime, block.contentType, data.mimeType, data.mime_type, data.mime, data.contentType),
    uri: firstText(block.uri, block.url, block.path, data.uri, data.url, data.path),
    sizeBytes: numberFrom(block.sizeBytes ?? block.size ?? block.fileSize ?? data.sizeBytes ?? data.size ?? data.fileSize),
    preview: firstText(block.preview, block.previewText, data.preview, data.previewText),
  };
}

function linkHrefFromUri(uri: string): string {
  const value = uri.trim();
  if (!value) return '';
  if (/^(https?:|file:|elyan:|data:|blob:)/i.test(value)) return value;
  return fileUrlFromPath(value);
}

type MarkdownNode =
  | { kind: 'text'; value: string }
  | { kind: 'bold'; value: string }
  | { kind: 'italic'; value: string }
  | { kind: 'code'; value: string }
  | { kind: 'link'; href: string; label: string };

function parseInlineMarkdown(text: string): MarkdownNode[] {
  const pattern = /(\*\*(.+?)\*\*|__(.+?)__|\*(.+?)\*|_(.+?)_|`(.+?)`|\[(.+?)\]\((.+?)\))/g;
  const nodes: MarkdownNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push({ kind: 'text', value: text.slice(last, match.index) });
    }
    const bold = match[2] ?? match[3];
    const italic = match[4] ?? match[5];
    const code = match[6];
    const linkLabel = match[7];
    const linkHref = match[8];
    if (bold != null) {
      nodes.push({ kind: 'bold', value: bold });
    } else if (italic != null) {
      nodes.push({ kind: 'italic', value: italic });
    } else if (code != null) {
      nodes.push({ kind: 'code', value: code });
    } else if (linkLabel != null && linkHref != null) {
      nodes.push({ kind: 'link', href: linkHref, label: linkLabel });
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    nodes.push({ kind: 'text', value: text.slice(last) });
  }
  return nodes;
}

function InlineMarkdown({ text }: { text: string }) {
  const nodes = parseInlineMarkdown(text);
  return (
    <>
      {nodes.map((node, i) => {
        if (node.kind === 'bold') return <strong key={i}>{node.value}</strong>;
        if (node.kind === 'italic') return <em key={i}>{node.value}</em>;
        if (node.kind === 'code') return <code key={i}>{node.value}</code>;
        if (node.kind === 'link') return <a key={i} href={node.href} target="_blank" rel="noopener noreferrer">{node.label}</a>;
        return <span key={i}>{node.value}</span>;
      })}
    </>
  );
}

type MarkdownLine =
  | { kind: 'blank' }
  | { kind: 'h1' | 'h2' | 'h3'; text: string }
  | { kind: 'hr' }
  | { kind: 'code_fence'; lang: string; lines: string[] }
  | { kind: 'ul'; text: string }
  | { kind: 'ol'; num: number; text: string }
  | { kind: 'blockquote'; text: string }
  | { kind: 'para'; text: string };

function parseMarkdownBlocks(raw: string): MarkdownLine[] {
  const lines = raw.replace(/\r\n/g, '\n').split('\n');
  const result: MarkdownLine[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? '';
    const trimmed = line.trim();
    if (!trimmed) { result.push({ kind: 'blank' }); i++; continue; }
    if (/^#{1}\s/.test(trimmed)) { result.push({ kind: 'h1', text: trimmed.replace(/^#\s+/, '') }); i++; continue; }
    if (/^#{2}\s/.test(trimmed)) { result.push({ kind: 'h2', text: trimmed.replace(/^##\s+/, '') }); i++; continue; }
    if (/^#{3}\s/.test(trimmed)) { result.push({ kind: 'h3', text: trimmed.replace(/^###\s+/, '') }); i++; continue; }
    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) { result.push({ kind: 'hr' }); i++; continue; }
    if (/^```/.test(trimmed)) {
      const lang = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test((lines[i] ?? '').trim())) {
        codeLines.push(lines[i] ?? '');
        i++;
      }
      i++;
      result.push({ kind: 'code_fence', lang, lines: codeLines });
      continue;
    }
    if (/^[-*+]\s/.test(trimmed)) { result.push({ kind: 'ul', text: trimmed.replace(/^[-*+]\s+/, '') }); i++; continue; }
    const olMatch = /^(\d+)\.\s(.+)/.exec(trimmed);
    if (olMatch) { result.push({ kind: 'ol', num: parseInt(olMatch[1] ?? '0', 10), text: olMatch[2] ?? '' }); i++; continue; }
    if (/^>\s/.test(trimmed)) { result.push({ kind: 'blockquote', text: trimmed.replace(/^>\s+/, '') }); i++; continue; }
    result.push({ kind: 'para', text: trimmed });
    i++;
  }
  return result;
}

function RichMarkdown({ text, compact = false }: { text: string; compact?: boolean }) {
  const blocks = parseMarkdownBlocks(text);
  const elements: ReactElement[] = [];
  let ulBuffer: string[] = [];
  let olBuffer: Array<{ num: number; text: string }> = [];

  function flushUl() {
    if (ulBuffer.length > 0) {
      elements.push(<ul key={`ul-${elements.length}`}>{ulBuffer.map((t, i) => <li key={i}><InlineMarkdown text={t} /></li>)}</ul>);
      ulBuffer = [];
    }
  }
  function flushOl() {
    if (olBuffer.length > 0) {
      elements.push(<ol key={`ol-${elements.length}`} start={olBuffer[0]!.num}>{olBuffer.map((item, i) => <li key={i}><InlineMarkdown text={item.text} /></li>)}</ol>);
      olBuffer = [];
    }
  }

  for (const block of blocks) {
    if (block.kind === 'ul') {
      flushOl();
      ulBuffer.push(block.text);
      continue;
    }
    if (block.kind === 'ol') {
      flushUl();
      olBuffer.push({ num: block.num, text: block.text });
      continue;
    }
    flushUl();
    flushOl();
    if (block.kind === 'blank') { if (!compact) elements.push(<div key={`br-${elements.length}`} className="md-spacer" />); continue; }
    if (block.kind === 'h1') { elements.push(<h2 key={`h1-${elements.length}`}><InlineMarkdown text={block.text} /></h2>); continue; }
    if (block.kind === 'h2') { elements.push(<h3 key={`h2-${elements.length}`}><InlineMarkdown text={block.text} /></h3>); continue; }
    if (block.kind === 'h3') { elements.push(<h4 key={`h3-${elements.length}`}><InlineMarkdown text={block.text} /></h4>); continue; }
    if (block.kind === 'hr') { elements.push(<hr key={`hr-${elements.length}`} />); continue; }
    if (block.kind === 'code_fence') {
      elements.push(<pre key={`pre-${elements.length}`} data-lang={block.lang || undefined}><code>{block.lines.join('\n')}</code></pre>);
      continue;
    }
    if (block.kind === 'blockquote') { elements.push(<blockquote key={`bq-${elements.length}`}><InlineMarkdown text={block.text} /></blockquote>); continue; }
    if (block.kind === 'para') { elements.push(<p key={`p-${elements.length}`}><InlineMarkdown text={block.text} /></p>); continue; }
  }
  flushUl();
  flushOl();
  return <>{elements}</>;
}

function StepStatusPill({ status }: { status: string }) {
  const normalized = status.trim().toLowerCase();
  const label = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(normalized)
    ? 'tamamlandı'
    : ['failed', 'error'].includes(normalized)
      ? 'başarısız'
      : ['cancelled', 'canceled'].includes(normalized)
        ? 'iptal edildi'
      : normalized === 'waiting_approval'
        ? 'onay bekliyor'
        : normalized === 'needs_desktop'
          ? 'masaüstü gerekiyor'
          : normalized === 'skipped'
            ? 'atlanıyor'
            : normalized === 'running' || normalized === 'in_progress'
              ? 'sürüyor'
            : normalized === 'started' || normalized === 'queued'
                ? 'başladı'
                : normalized || 'durum';
  const variant = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(normalized) ? 'success'
    : ['failed', 'error', 'cancelled', 'canceled'].includes(normalized) ? 'error'
    : normalized === 'running' || normalized === 'started' || normalized === 'in_progress' ? 'active'
    : normalized === 'waiting_approval' ? 'warn'
    : 'neutral';
  return <span className={`message-block__pill message-block__pill--${variant}`} title={normalized}>{label}</span>;
}

function nextProgressiveLength(text: string, current: number): number {
  if (current >= text.length) return text.length;
  if (text.length - current <= 72) return text.length;
  const target = Math.min(text.length, current + Math.max(18, Math.min(64, Math.ceil(text.length / 26))));
  const sentenceBoundary = text.slice(target).search(/[.!?…]\s/);
  if (sentenceBoundary >= 0 && sentenceBoundary <= 90) {
    return Math.min(text.length, target + sentenceBoundary + 2);
  }
  const spaceBoundary = text.indexOf(' ', target);
  if (spaceBoundary > target && spaceBoundary - target <= 36) {
    return spaceBoundary + 1;
  }
  return target;
}

function useProgressiveText(text: string, shouldType: boolean, onFinished?: () => void): string {
  const [displayedText, setDisplayedText] = useState(shouldType ? '' : text);
  const onFinishedRef = useRef(onFinished);

  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    if (!shouldType) {
      setDisplayedText(text);
      return;
    }

    setDisplayedText((current) => {
      if (!current) return '';
      if (text.startsWith(current)) return current;
      return text.slice(0, Math.min(current.length, text.length));
    });
  }, [text, shouldType]);

  useEffect(() => {
    if (!shouldType) return undefined;
    if (displayedText.length >= text.length) {
      onFinishedRef.current?.();
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      setDisplayedText(text.slice(0, nextProgressiveLength(text, displayedText.length)));
    }, displayedText.length === 0 ? 12 : 28);
    return () => window.clearTimeout(timeoutId);
  }, [displayedText, text, shouldType]);

  return displayedText;
}

function StreamingRichMarkdown({
  text,
  compact = false,
  shouldType = false,
  onFinished,
}: {
  text: string;
  compact?: boolean;
  shouldType?: boolean;
  onFinished?: () => void;
}) {
  const displayedText = useProgressiveText(text, shouldType, onFinished);
  return <RichMarkdown text={displayedText} compact={compact} />;
}

function TextBlock({
  block,
  fallbackTitle = '',
  compact = false,
  shouldType = false,
  onFinished,
}: {
  block: Record<string, unknown>;
  fallbackTitle?: string;
  compact?: boolean;
  shouldType?: boolean;
  onFinished?: () => void;
}) {
  const title = asString(block.title).trim() || fallbackTitle;
  const body = blockBody(block);
  const hints = blockRenderHints(block);
  const tone = asString(hints.tone).trim();
  const density = asString(hints.density).trim() || (compact ? 'compact' : '');
  if (!title && !body) {
    return null;
  }
  return (
    <section
      className={[
        'message-block message-block--text',
        tone ? `message-block--tone-${tone}` : '',
        density ? `message-block--density-${density}` : '',
      ].filter(Boolean).join(' ')}
      aria-label={title || undefined}
    >
      {title ? <strong className="message-block__title">{title}</strong> : null}
      {body ? (
        <div className="message-block__markdown">
          <StreamingRichMarkdown text={body} compact={compact} shouldType={shouldType} onFinished={onFinished} />
        </div>
      ) : null}
    </section>
  );
}

function CodeBlock({ block }: { block: Record<string, unknown> }) {
  const data = blockData(block);
  const code = firstText(block.code, data.code, block.content, data.content, block.markdown, data.markdown);
  const language = firstText(block.language, block.lang, data.language, data.lang);
  const filename = firstText(block.filename, block.file, data.filename, data.file);
  const executable = block.executable === true || data.executable === true;
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  if (!code) return null;
  return (
    <section className="message-block message-block--code" aria-label={filename || language || 'Kod'}>
      <div className="message-block__code-header">
        <span>{filename || language || 'Kod'}</span>
        {executable ? <StepStatusPill status="started" /> : null}
        <button
          type="button"
          className="message-block__copy"
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? 'Aç' : 'Daralt'}
        </button>
        <button
          type="button"
          className="message-block__copy"
          onClick={() => {
            const writePromise = navigator.clipboard?.writeText(code);
            if (!writePromise) return;
            void writePromise.then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1100);
            });
          }}
        >
          {copied ? 'Kopyalandı' : 'Kopyala'}
        </button>
      </div>
      {collapsed ? null : <pre className="message-block__code" data-lang={language || undefined}><code>{code}</code></pre>}
    </section>
  );
}

function TableBlock({ block }: { block: Record<string, unknown> }) {
  const table = tableBlockData(block);
  const [sort, setSort] = useState<{ columnIndex: number; direction: 'asc' | 'desc' } | null>(null);
  const [copied, setCopied] = useState(false);
  const toneForCell = (columnIndex: number, cellValue: string): TableHighlightRule['tone'] | '' => {
    const column = table.columns[columnIndex] ?? '';
    const rule = table.highlightRules.find((candidate) => (
      candidate.column.toLowerCase() === column.toLowerCase() &&
      candidate.match.toLowerCase() === cellValue.toLowerCase()
    ));
    return rule?.tone ?? '';
  };
  const rows = useMemo(() => {
    if (!sort) return table.rows;
    return [...table.rows].sort((left, right) => {
      const leftValue = left[sort.columnIndex] ?? '';
      const rightValue = right[sort.columnIndex] ?? '';
      const numericLeft = numberFrom(leftValue);
      const numericRight = numberFrom(rightValue);
      const compare = numericLeft !== null && numericRight !== null
        ? numericLeft - numericRight
        : leftValue.localeCompare(rightValue, 'tr', { numeric: true, sensitivity: 'base' });
      return sort.direction === 'asc' ? compare : -compare;
    });
  }, [sort, table.rows]);
  const csv = useMemo(() => {
    const escape = (value: string) => `"${String(value).replace(/"/g, '""')}"`;
    return [table.columns, ...rows].map((row) => row.map(escape).join(',')).join('\n');
  }, [rows, table.columns]);
  if (table.columns.length === 0 || table.rows.length === 0) return null;
  return (
    <section className="message-block message-block--table" aria-label={table.title || 'Tablo'}>
      <div className="message-block__table-header">
        {table.title ? <strong className="message-block__title">{table.title}</strong> : <span />}
        <button
          type="button"
          className="message-block__copy"
          onClick={() => {
            const writePromise = navigator.clipboard?.writeText(csv);
            if (!writePromise) return;
            void writePromise.then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1100);
            });
          }}
        >
          {copied ? 'Kopyalandı' : 'CSV kopyala'}
        </button>
      </div>
      <div className="message-block__table-scroll">
        <table className="message-block__table">
          <thead>
            <tr>
              {table.columns.map((column, index) => {
                const sorted = sort?.columnIndex === index ? sort.direction : '';
                return (
                  <th key={`${column}-${index}`}>
                    <button
                      type="button"
                      className="message-block__table-sort"
                      onClick={() => setSort((current) => (
                        current?.columnIndex === index
                          ? { columnIndex: index, direction: current.direction === 'asc' ? 'desc' : 'asc' }
                          : { columnIndex: index, direction: 'asc' }
                      ))}
                    >
                      <span>{column}</span>
                      {sorted ? <small>{sorted === 'asc' ? '↑' : '↓'}</small> : null}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {table.columns.map((_, cellIndex) => {
                  const cell = row[cellIndex] ?? '';
                  const tone = toneForCell(cellIndex, cell);
                  return (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>
                      {tone ? <span className={`message-block__tone message-block__tone--${tone}`}>{cell}</span> : cell}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.caption ? <p className="message-block__summary">{table.caption}</p> : null}
    </section>
  );
}

function ChartBlock({ block }: { block: Record<string, unknown> }) {
  const chart = chartBlockData(block);
  if (chart.points.length === 0 && chart.chartType !== 'function') return null;
  if (chart.chartType === 'function') {
    return <FunctionChartBlock chart={chart} />;
  }
  const maxValue = Math.max(...chart.points.map((point) => Math.abs(point.value)), 1);
  const totalValue = chart.points.reduce((sum, point) => sum + Math.max(0, point.value), 0) || 1;
  const linePoints = chart.points
    .map((point, index) => {
      const x = chart.points.length === 1 ? 50 : (index / (chart.points.length - 1)) * 100;
      const y = 100 - ((point.value / maxValue) * 82 + 9);
      return `${x},${Math.max(4, Math.min(96, y))}`;
    })
    .join(' ');
  let pieOffset = 0;
  const pieGradient = chart.points
    .map((point) => {
      const start = pieOffset;
      const sweep = (Math.max(0, point.value) / totalValue) * 360;
      pieOffset += sweep;
      return `${point.color} ${start}deg ${pieOffset}deg`;
    })
    .join(', ');

  return (
    <section className="message-block message-block--chart" aria-label={chart.title || 'Grafik'}>
      {chart.title ? <strong className="message-block__title">{chart.title}</strong> : null}
      {chart.chartType === 'pie' ? (
        <div className="message-block__chart-pie-wrap">
          <div className="message-block__chart-pie" style={{ background: `conic-gradient(${pieGradient})` }} aria-hidden="true" />
          <ChartLegend points={chart.points} />
        </div>
      ) : chart.chartType === 'line' ? (
        <div className="message-block__chart-line">
          <svg viewBox="0 0 100 100" role="img" aria-label={chart.title || 'Çizgi grafik'} preserveAspectRatio="none">
            <polyline points={linePoints} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <ChartLegend points={chart.points} compact />
        </div>
      ) : (
        <div className="message-block__chart-bars">
          {chart.points.map((point) => (
            <div className="message-block__bar" key={point.label}>
              <div className="message-block__bar-track">
                <span style={{ height: `${Math.max(6, Math.min(100, (Math.abs(point.value) / maxValue) * 100))}%`, background: point.color }} />
              </div>
              <small title={point.label}>{point.label}</small>
              <strong>{point.value}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function FunctionChartBlock({ chart }: { chart: ChartBlockData }) {
  const fixed = Object.entries(chart.fixed)
    .map(([key, value]) => `${key} = ${scalarText(value) || String(value)}`)
    .filter(Boolean);
  const range = Object.entries(chart.range)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join('..') : scalarText(value) || String(value)}`)
    .filter(Boolean);
  return (
    <section className="message-block message-block--chart message-block--function-chart" aria-label={chart.title || 'Fonksiyon grafiği'}>
      {chart.title ? <strong className="message-block__title">{chart.title}</strong> : null}
      <pre className="message-block__math" data-format="function"><code>{chart.expression}</code></pre>
      {chart.variables.length > 0 ? <p className="message-block__summary">Değişkenler: {chart.variables.join(', ')}</p> : null}
      {range.length > 0 ? <p className="message-block__summary">Aralık: {range.join(' · ')}</p> : null}
      {fixed.length > 0 ? <p className="message-block__summary">Sabit: {fixed.join(' · ')}</p> : null}
    </section>
  );
}

function ChartLegend({ points, compact = false }: { points: ChartPoint[]; compact?: boolean }) {
  return (
    <div className={`message-block__chart-legend${compact ? ' message-block__chart-legend--compact' : ''}`}>
      {points.map((point) => (
        <span key={point.label}>
          <i style={{ background: point.color }} aria-hidden="true" />
          {point.label}
          <strong>{point.value}</strong>
        </span>
      ))}
    </div>
  );
}

function FileBlock({ block }: { block: Record<string, unknown> }) {
  const file = fileBlockData(block);
  const href = linkHrefFromUri(file.uri);
  const typeLabel = file.mimeType || (file.name.includes('.') ? file.name.split('.').pop() || 'dosya' : 'dosya');
  const icon = /pdf/i.test(file.mimeType || file.name)
    ? 'PDF'
    : /image/i.test(file.mimeType)
      ? 'IMG'
      : /csv|spreadsheet|excel/i.test(file.mimeType || file.name)
        ? 'CSV'
        : 'FILE';
  const content = (
    <>
      <span className="message-block__file-icon">{icon}</span>
      <span className="message-block__file-copy">
        <strong>{file.name}</strong>
        <small>{[typeLabel, file.sizeBytes != null ? formatAttachmentSize(file.sizeBytes) : ''].filter(Boolean).join(' · ')}</small>
        {file.preview ? <em>{file.preview}</em> : null}
      </span>
    </>
  );
  return (
    <section className="message-block message-block--file" aria-label={file.name}>
      {href ? (
        <a className="message-block__file-link" href={href} target="_blank" rel="noreferrer">
          {content}
        </a>
      ) : (
        <div className="message-block__file-link">{content}</div>
      )}
    </section>
  );
}

function normalizeLatex(raw: string): string {
  const trimmed = raw.trim();
  if ((trimmed.startsWith('\\[') && trimmed.endsWith('\\]')) || (trimmed.startsWith('\\(') && trimmed.endsWith('\\)'))) {
    return trimmed.slice(2, -2).trim();
  }
  if (trimmed.startsWith('$$') && trimmed.endsWith('$$')) {
    return trimmed.slice(2, -2).trim();
  }
  if (trimmed.startsWith('$') && trimmed.endsWith('$')) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function MathBlock({ block }: { block: Record<string, unknown> }) {
  const data = blockData(block);
  const content = normalizeLatex(firstText(block.content, block.latex, block.markdown, data.content, data.latex, data.markdown));
  const format = firstText(block.format, data.format) || 'latex';
  const displayMode = block.displayMode !== false && block.display_mode !== false && data.displayMode !== false && data.display_mode !== false;
  const [copied, setCopied] = useState(false);
  if (!content) return null;
  return (
    <section className={`message-block message-block--math${displayMode ? ' message-block--math-display' : ''}`} aria-label="Matematik">
      <div className="message-block__code-header">
        <span>{format}</span>
        <button
          type="button"
          className="message-block__copy"
          onClick={() => {
            const writePromise = navigator.clipboard?.writeText(content);
            if (!writePromise) return;
            void writePromise.then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1100);
            });
          }}
        >
          {copied ? 'Kopyalandı' : 'Kopyala'}
        </button>
      </div>
      <pre className="message-block__math" data-format={format}><code>{content}</code></pre>
    </section>
  );
}

function ArtifactBlock({ block }: { block: Record<string, unknown> }) {
  const data = blockData(block);
  const artifactType = firstText(block.artifactType, block.artifact_type, data.artifactType, data.artifact_type, data.type, block.kind) || 'artifact';
  const url = linkHrefFromUri(firstText(block.url, block.uri, block.src, data.url, data.uri, data.src));
  const rawTitle = firstText(block.title, data.title);
  const mime = firstText(block.mime, block.mimeType, data.mime, data.mimeType);
  const isImage = artifactType === 'image' || artifactType === 'chart_image' || mime.startsWith('image/');
  if (!url && !rawTitle && !mime) return null;
  const title = rawTitle || 'Artifact';
  if (isImage && url) {
    return (
      <section className="message-block message-block--artifact message-block--artifact-image" aria-label={title}>
        {title ? <strong className="message-block__title">{title}</strong> : null}
        <img className="message-block__artifact-image" src={url} alt={title || ''} />
      </section>
    );
  }
  const content = (
    <>
      <span className="message-block__file-icon">ART</span>
      <span className="message-block__file-copy">
        <strong>{title}</strong>
        {mime ? <small>{mime}</small> : null}
      </span>
    </>
  );
  return (
    <section className="message-block message-block--artifact" aria-label={title}>
      {url ? (
        <a className="message-block__file-link" href={url} target="_blank" rel="noreferrer">
          {content}
        </a>
      ) : (
        <div className="message-block__file-link">{content}</div>
      )}
    </section>
  );
}

function TaskTraceBlock({ block }: { block: Record<string, unknown> }) {
  const trace = asRecord(block.trace ?? blockData(block));
  const title = firstText(block.title, trace.title) || 'Görev durumu';
  const body = blockBody(block) || firstText(trace.summary, trace.description, trace.text);
  const overallStatus = firstText(block.status, block.state, trace.status, trace.state).toLowerCase();
  const rawSteps = asArray(block.steps).length > 0
    ? asArray(block.steps)
    : asArray(block.items).length > 0
      ? asArray(block.items)
      : asArray(trace.steps).length > 0
        ? asArray(trace.steps)
        : asArray(trace.items);
  const steps = rawSteps
    .map(asRecord)
    .map((step, idx) => ({
      id: asString(step.id) || asString(step.key) || `step-${idx}`,
      label: asString(step.label) || asString(step.title) || asString(step.capability) || asString(step.value),
      detail: asString(step.detail) || asString(step.description) || asString(step.output) || asString(step.summary),
      status: asString(step.status) || asString(step.state),
    }))
    .filter((step) => step.label || step.detail || step.status)
    .slice(0, 12);
  const isRunning = overallStatus === 'running' || overallStatus === 'started' || overallStatus === 'in_progress';
  const isCompleted = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(overallStatus);
  return (
    <section className={`message-block message-block--task-trace${isRunning ? ' message-block--running' : ''}`} aria-label={title}>
      <div className="message-block__header">
        <span className="message-block__task-icon" aria-hidden="true" />
        <strong>{title}</strong>
        {overallStatus && !isCompleted ? <StepStatusPill status={overallStatus} /> : null}
        {isCompleted ? <StepStatusPill status="completed" /> : null}
      </div>
      {body ? <p className="message-block__summary">{body}</p> : null}
      {steps.length > 0 ? (
        <ol className="message-block__steps">
          {steps.map((step) => {
            const stepStatus = step.status.toLowerCase();
            const isDone = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(stepStatus);
            const isStepFailed = ['failed', 'error', 'cancelled', 'canceled'].includes(stepStatus);
            const isActive = stepStatus === 'running' || stepStatus === 'started' || stepStatus === 'in_progress';
            const stepClass = [
              'message-block__step',
              isDone ? 'step--done' : '',
              isStepFailed ? 'step--failed' : '',
              isActive ? 'step--active' : '',
              !isDone && !isStepFailed && !isActive ? 'step--pending' : '',
            ].filter(Boolean).join(' ');
            return (
              <li key={step.id} className={stepClass}>
                <span className="step__indicator" aria-hidden="true">
                  {isDone ? '✓' : isStepFailed ? '✗' : isActive ? '' : '·'}
                </span>
                <span className="step__label">{step.label || step.detail || 'Adım'}</span>
                {isActive ? <StepStatusPill status="running" /> : null}
                {isStepFailed ? <StepStatusPill status="failed" /> : null}
                {step.detail && step.detail !== step.label ? <small className="step__detail">{step.detail}</small> : null}
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

function ActionableBlock({ block }: { block: Record<string, unknown> }) {
  const title = asString(block.title).trim();
  const body = blockBody(block);
  const items = asArray(block.items);
  const actions = asArray(block.actions);
  if (!title && !body && items.length === 0 && actions.length === 0) return null;
  return (
    <section className="message-block message-block--actionable" aria-label={title || 'Aksiyon'}>
      {title ? <strong className="message-block__title">{title}</strong> : null}
      {body ? <div className="message-block__markdown"><RichMarkdown text={body} compact /></div> : null}
      {actions.length > 0 ? (
        <div className="message-block__actions">
          {actions.map((action, i) => {
            const rec = asRecord(action);
            const label = asString(rec.label) || asString(rec.title) || asString(rec.value);
            const hint = asString(rec.hint) || asString(rec.description);
            return label ? (
              <div key={i} className="message-block__action-item">
                <span>{label}</span>
                {hint ? <small>{hint}</small> : null}
              </div>
            ) : null;
          })}
        </div>
      ) : null}
      {items.length > 0 ? (
        <ul>
          {items.map((item, i) => {
            const rec = asRecord(item);
            const text = typeof item === 'string' ? item : asString(rec.label) || asString(rec.value);
            return text ? <li key={i}><InlineMarkdown text={text} /></li> : null;
          })}
        </ul>
      ) : null}
    </section>
  );
}

function AssistantBlocks({
  blocks,
  shouldType = false,
  onFinished,
}: {
  blocks: Record<string, unknown>[];
  shouldType?: boolean;
  onFinished?: () => void;
}) {
  return (
    <div className="message-blocks">
      {blocks.map((block, index) => {
        const type = asString(block.type).trim();
        const key = asString(block.stableBlockId) || asString(block.cacheDigest) || `${type}-${index}`;
        const title = asString(block.title).trim();
        const body = blockBody(block);
        const items = asArray(block.items);
        const children = renderableAssistantBlocks(block.blocks ?? block.children);

        if (type === 'block_group') {
          return children.length > 0 ? (
            <section key={key} className="message-block message-block--group" aria-label={title || 'Detay'}>
              {title ? <strong className="message-block__title">{title}</strong> : null}
              <AssistantBlocks blocks={children} shouldType={shouldType} onFinished={onFinished} />
            </section>
          ) : null;
        }

        if (type === 'task_trace') {
          return <TaskTraceBlock key={key} block={block} />;
        }

        if (type === 'code') {
          return <CodeBlock key={key} block={block} />;
        }

        if (type === 'table') {
          return <TableBlock key={key} block={block} />;
        }

        if (type === 'chart') {
          return <ChartBlock key={key} block={block} />;
        }

        if (type === 'file') {
          return <FileBlock key={key} block={block} />;
        }

        if (type === 'math') {
          return <MathBlock key={key} block={block} />;
        }

        if (type === 'artifact') {
          return <ArtifactBlock key={key} block={block} />;
        }

        if (type === 'next_steps') {
          return (
            <section key={key} className="message-block message-block--next-steps" aria-label={title || 'Sonraki adımlar'}>
              {title ? <strong className="message-block__title">{title}</strong> : <strong className="message-block__title">Sonraki adımlar</strong>}
              {body ? (
                <div className="message-block__markdown">
                  <StreamingRichMarkdown text={body} compact shouldType={shouldType} onFinished={onFinished} />
                </div>
              ) : null}
              {items.length > 0 ? (
                <ul>
                  {items.map((item, itemIndex) => {
                    const record = asRecord(item);
                    const text = typeof item === 'string'
                      ? item
                      : asString(record.label) || asString(record.value) || asString(record.description) || asString(record.status);
                    return text ? <li key={`${key}-${itemIndex}`}><InlineMarkdown text={text} /></li> : null;
                  })}
                </ul>
              ) : null}
            </section>
          );
        }

        if (type === 'attachment_context' || type === 'context_signal') {
          return (
            <section key={key} className="message-block message-block--context" aria-label={title || 'Bağlam'}>
              {title ? <strong className="message-block__title">{title}</strong> : null}
              {body ? <p>{body}</p> : null}
              {items.map((item, itemIndex) => {
                const record = asRecord(item);
                const label = asString(record.label);
                const value = asString(record.value);
                return label || value ? <p key={`${key}-${itemIndex}`}><strong>{label ? `${label}` : ''}</strong>{label && value ? ': ' : ''}{value}</p> : null;
              })}
            </section>
          );
        }

        if (type === 'actionable') {
          return <ActionableBlock key={key} block={block} />;
        }

        if (['text', 'summary', 'status'].includes(type)) {
          const label = title || (type === 'summary' ? 'Sonuç' : type === 'status' ? 'Durum' : '');
          return <TextBlock key={key} block={block} fallbackTitle={label} shouldType={shouldType} onFinished={onFinished} />;
        }

        return null;
      })}
    </div>
  );
}

function attachmentIdentity(attachment: ComposerAttachment): string {
  return attachment.id ?? attachment.path ?? `${attachment.name ?? 'attachment'}-${attachment.mimeType ?? 'artifact'}`;
}

function fileUrlFromPath(pathValue: string): string {
  const normalized = String(pathValue || '').trim().replace(/\\/g, '/');
  if (!normalized) {
    return '';
  }
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return `file:///${encodeURI(normalized)}`;
  }
  if (normalized.startsWith('/')) {
    return `file://${encodeURI(normalized)}`;
  }
  return `file://${encodeURI(normalized)}`;
}

interface WorkspaceProps {
  snapshot: BootstrapSnapshot | null;
  selectedConversationId: string;
  composer: string;
  composerAttachments: ComposerAttachment[];
  pendingUserMessage?: { text: string; attachments: ComposerAttachment[] } | null;
  taskShell?: DesktopTaskShellView;
  skillItems: ListSurfaceItem[];
  busy: boolean;
  lastError: string;
  chatLocked: boolean;
  chatLockTitle: string;
  chatLockDetail: string;
  logoUrl: string;
  userName: string;
  onComposerChange: (value: string) => void;
  onClearComposer: () => void;
  onCreateConversation: () => void;
  onPasteFiles: (files: File[]) => void;
  onRemoveComposerAttachment: (attachmentId: string) => void;
  onSend: () => void;
  onConfirmPlan: (pendingPlanId: string, approved: boolean) => void;
  onOpenPermissionSettings: (permissionKey: string, systemPermissionKey: string) => void;
  onToggleShortcutHelp: () => void;
  onCreatePairingSession: () => void;
  onOpenTasks?: () => void;
  onExecuteAssignedTasks?: () => void;
  onApproveTask?: (taskId: string, approved: boolean) => void;
}

export function Workspace({
  snapshot,
  selectedConversationId,
  composer,
  composerAttachments,
  pendingUserMessage,
  taskShell = defaultDesktopTaskShell,
  skillItems,
  busy,
  lastError,
  chatLocked,
  chatLockTitle,
  chatLockDetail,
  logoUrl,
  userName,
  onComposerChange,
  onClearComposer,
  onCreateConversation,
  onPasteFiles,
  onRemoveComposerAttachment,
  onSend,
  onConfirmPlan,
  onOpenPermissionSettings,
  onToggleShortcutHelp,
  onCreatePairingSession,
  onOpenTasks = noop,
  onExecuteAssignedTasks = noop,
  onApproveTask = noopApproveTask,
}: WorkspaceProps) {
  const stateConversation = asRecord(stateRecord(snapshot).conversation);
  const activeId = selectedConversationId || asString(stateConversation.activeId);
  const conversation = activeId ? selectedConversation(snapshot, activeId) : null;
  const snapshotMessages = conversation?.messages ?? [];
  
  const [seenMessageIds, setSeenMessageIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    setSeenMessageIds(new Set(snapshotMessages.map((m) => m.id)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  const messages = useMemo(() => {
    const list = [...snapshotMessages];
    if (pendingUserMessage) {
      list.push({
        id: 'pending-user',
        role: 'user',
        text: pendingUserMessage.text,
        meta: { selectedArtifacts: pendingUserMessage.attachments },
        timestampMs: Date.now(),
      } as any);
    }
    return list;
  }, [snapshotMessages, pendingUserMessage]);

  const firstName = userName.split(' ')[0] || 'Elyan';
  const showAgentStatus = busy;
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const timelineRef = useRef<HTMLElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isComposerDragActive, setIsComposerDragActive] = useState(false);
  const [isComposerFocused, setIsComposerFocused] = useState(false);
  const [isComposerMultiline, setIsComposerMultiline] = useState(false);
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashMenuIndex, setSlashMenuIndex] = useState(0);
  const [messageMenu, setMessageMenu] = useState<MessageContextMenuState | null>(null);

  // Dictation
  const { dictationState, start: startDictation, stop: stopDictation, cancel: cancelDictation, isActive: isDictationActive } = useDictation();

  // Insert final transcript into composer
  useEffect(() => {
    if (dictationState.state === 'final_result' && dictationState.partialTranscript === null) {
      // The final event was just received (via dictation-status event or local state update)
      // Since we don't store the final text directly in DictationState (we emit dictation-final separately),
      // we need to listen to 'dictation-final' on the api directly here, or we can just capture it in useDictation
      // Wait, let's update useDictation to store the final transcript temporarily, or just rely on the IPC event directly here.
    }
  }, [dictationState.state]);

  const latestComposer = useRef(composer);
  latestComposer.current = composer;

  useLayoutEffect(() => {
    const api = getDesktopApi();
    if (!api?.subscribe) return;
    
    const unsub = api.subscribe('dictation-final', (payload: any) => {
      if (payload?.transcript) {
        const prev = latestComposer.current;
        const space = prev.length > 0 && !prev.endsWith(' ') ? ' ' : '';
        onComposerChange(prev + space + payload.transcript);
      }
    });
    return () => unsub();
  }, [onComposerChange]);


  const runtime = runtimeRecord(snapshot);
  const runtimeDevice = runtimeSessionDeviceRecord(snapshot);
  const runtimeReadiness = runtimeSessionReadinessRecord(snapshot);
  const runtimeConnection = runtimeSessionConnectionRecord(snapshot);
  const runtimeLifecycleState = asString(runtime.runtimeLifecycleState).trim().toLowerCase();
  const targetStatus = asString(runtimeReadiness.targetStatus ?? runtime.targetStatus).trim().toLowerCase();
  const targetErrorCode = asString(runtimeReadiness.targetErrorCode ?? runtime.targetErrorCode).trim().toLowerCase();
  const connectionStatus = asString(runtimeConnection.status).trim().toLowerCase();
  const canReceiveTasks = runtimeReadiness.canReceiveTasks === true;
  const pairing = asRecord(stateRecord(snapshot).pairing);
  const pairingStatus = asString(pairing.lastSessionStatus ?? pairing.status).trim().toLowerCase();
  const isMobileConnected = Boolean(runtimeDevice?.id) && canReceiveTasks && (targetStatus === 'ready' || runtimeLifecycleState === 'ready' || connectionStatus === 'online');
  const mobileConnectionStage = isMobileConnected
    ? 'ready'
    : pairingStatus === 'pending'
      ? 'waiting_claim'
      : pairingStatus === 'claimed' || runtimeLifecycleState === 'claimed_registering'
        ? 'claimed_registering'
        : runtimeLifecycleState === 'runtime_connecting'
          ? 'runtime_connecting'
          : runtimeLifecycleState === 'reconnecting'
            ? 'reconnecting'
            : targetErrorCode || targetStatus || 'offline';
  const mobileConnectionCopy = (() => {
    if (mobileConnectionStage === 'ready') {
      return {
        title: 'Mobil hazır',
        detail: 'Telefonundan gelen görevler bu masaüstüne aktarılabilir.',
      };
    }
    if (mobileConnectionStage === 'waiting_claim') {
      return {
        title: 'QR kod bekliyor',
        detail: 'Telefonundan QR kodu okuttuğunda kayıt otomatik tamamlanır.',
      };
    }
    if (mobileConnectionStage === 'claimed_registering') {
      return {
        title: 'Kayıt tamamlanıyor',
        detail: 'Telefon eşleşti. Masaüstü runtime görev almaya hazırlanıyor.',
      };
    }
    if (mobileConnectionStage === 'runtime_connecting') {
      return {
        title: 'Bağlantı kuruluyor',
        detail: 'Runtime kanalı açılıyor; olmazsa heartbeat ve görev kontrolü devam eder.',
      };
    }
    if (mobileConnectionStage === 'reconnecting') {
      return {
        title: 'Yeniden bağlanıyor',
        detail: 'Bağlantı korunuyor. Görevler güvenli aralıklarla tekrar kontrol ediliyor.',
      };
    }
    if (mobileConnectionStage === 'plan_restricted' || mobileConnectionStage === 'desktop_plan_required' || mobileConnectionStage === 'desktop_limit_reached') {
      return {
        title: 'Plan kontrolü gerekli',
        detail: 'Bu masaüstünün mobilden görev alması için hesap planını kontrol et.',
      };
    }
    return {
      title: 'Mobil cihazınızı bağlayın',
      detail: 'Elyan mobil uygulamasından giriş yapıp bu masaüstünü eşleştirin.',
    };
  })();
  const qrDataUrl = asString(pairing.qrDataUrl);

  const [showMobileBubble, setShowMobileBubble] = useState(!isMobileConnected);
  const [showQR, setShowQR] = useState(false);

  useEffect(() => {
    if (isMobileConnected) {
      setShowMobileBubble(false);
      setShowQR(false);
    }
  }, [isMobileConnected]);

  const emptyStateImage = useMemo(() => NEW_CHAT_IMAGES[Math.floor(Math.random() * NEW_CHAT_IMAGES.length)], [activeId]);
  const emptyStateGreeting = useMemo(() => getRandomGreeting(firstName), [activeId, firstName]);

  function attachmentFilesFromClipboard(event: ClipboardEvent<HTMLTextAreaElement>): File[] {
    return attachmentFilesFromDataTransfer(event.clipboardData);
  }

  function attachmentFilesFromDataTransfer(dataTransfer: DataTransfer): File[] {
    const items = Array.from(dataTransfer.items ?? []);
    const filesFromItems = items
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    const filesFromClipboard = Array.from(dataTransfer.files ?? []);
    const merged = [...filesFromItems, ...filesFromClipboard];
    const seen = new Set<string>();
    return merged.filter((file) => {
      const key = `${file.name}|${file.size}|${file.type}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }

  function attachmentFilesFromDrop(event: DragEvent<HTMLElement>): File[] {
    return attachmentFilesFromDataTransfer(event.dataTransfer);
  }

  async function copyMessageText(text: string) {
    const payload = String(text || '');
    if (!payload) {
      return;
    }
    try {
      await navigator.clipboard.writeText(payload);
    } catch {
      const fallback = document.createElement('textarea');
      fallback.value = payload;
      fallback.style.position = 'fixed';
      fallback.style.left = '-9999px';
      document.body.appendChild(fallback);
      fallback.select();
      document.execCommand('copy');
      document.body.removeChild(fallback);
    }
  }

  type SlashCommand = {
    id: string;
    label: string;
    description: string;
    shortcut?: string;
    tags?: string[];
    prefix: '/' | '$';
    kind: 'action' | 'skill';
    run: () => void;
  };

  const staticSlashCommands: SlashCommand[] = [
    { id: 'new', label: 'Yeni sohbet', description: 'Temiz bir konuşma açar.', shortcut: 'Cmd/Ctrl+N', tags: ['oturum'], prefix: '/', kind: 'action', run: () => onCreateConversation() },
    { id: 'file', label: 'Dosya ekle', description: 'Bilgisayardan bir veya daha fazla dosya seç.', shortcut: 'Cmd/Ctrl+O', tags: ['ek'], prefix: '/', kind: 'action', run: () => fileInputRef.current?.click() },
    { id: 'image', label: 'Görsel ekle', description: 'Sadece görseller için dosya seçici aç.', shortcut: 'Cmd/Ctrl+Shift+I', tags: ['ek'], prefix: '/', kind: 'action', run: () => imageInputRef.current?.click() },
    { id: 'send', label: 'Gönder', description: 'Hazırsa mevcut mesajı yollar.', shortcut: 'Cmd/Ctrl+Enter', tags: ['hızlı'], prefix: '/', kind: 'action', run: () => onSend() },
    { id: 'clear', label: 'Composer temizle', description: 'Yazı ve ekleri temizler.', shortcut: 'Cmd/Ctrl+Backspace', tags: ['temizle'], prefix: '/', kind: 'action', run: () => onClearComposer() },
    { id: 'copylast', label: 'Son yanıtı kopyala', description: 'Elyan’ın son cevabını panoya alır.', tags: ['kopya'], prefix: '/', kind: 'action', run: () => void copyLastAssistantMessage() },
    { id: 'focus', label: 'Composer’a odaklan', description: 'Yazı alanını aktif eder.', tags: ['odak'], prefix: '/', kind: 'action', run: () => composerRef.current?.focus() },
    { id: 'top', label: 'Başa git', description: 'Konuşmanın en üstüne çıkar.', tags: ['gezinti'], prefix: '/', kind: 'action', run: () => scrollTimeline('top') },
    { id: 'bottom', label: 'Alta git', description: 'Konuşmanın en altına iner.', tags: ['gezinti'], prefix: '/', kind: 'action', run: () => scrollTimeline('bottom') },
    { id: 'help', label: 'Kısayollar', description: 'Kısayol yardımını açar.', tags: ['yardım'], prefix: '/', kind: 'action', run: () => onToggleShortcutHelp() },
  ];

  const skillSlashCommands: SlashCommand[] = (skillItems || []).map((item) => ({
    id: item.id,
    label: item.title,
    description: item.subtitle || item.details || 'Yetenek',
    tags: item.badges ?? [],
    prefix: '$',
    kind: 'skill',
    run: () => undefined,
  }));

  const isSkillMode = composer.startsWith('$');
  const activeSlashCommands = isSkillMode ? skillSlashCommands : staticSlashCommands;
  const slashQuery = composer.startsWith('/') || composer.startsWith('$') ? composer.slice(1).trim().toLowerCase() : '';
  const slashMatches = activeSlashCommands.filter((command) => {
    if (!composer.startsWith('/') && !composer.startsWith('$')) {
      return false;
    }
    if (!slashQuery) {
      return true;
    }
    return `${command.id} ${command.label} ${command.description}`.toLowerCase().includes(slashQuery);
  });
  const visibleSlashCommands = slashMatches.length > 0 ? slashMatches : activeSlashCommands;
  const slashCommandSelectedIndex = Math.min(slashMenuIndex, Math.max(0, visibleSlashCommands.length - 1));

  function runSlashCommand(command: SlashCommand) {
    setSlashMenuOpen(false);
    setSlashMenuIndex(0);
    if (command.kind === 'skill') {
      onComposerChange(`$${command.id} `);
      composerRef.current?.focus();
      return;
    }
    command.run();
    if (command.id === 'new') {
      return;
    }
    if (composer === '/') {
      onComposerChange('');
    }
  }

  function scrollTimeline(direction: 'top' | 'bottom') {
    const element = timelineRef.current;
    if (!element) {
      return;
    }
    element.scrollTo({
      top: direction === 'top' ? 0 : element.scrollHeight,
      behavior: 'smooth',
    });
  }

  async function copyLastAssistantMessage() {
    const lastAssistantMessage = [...messages].reverse().find((message) => message.role !== 'user' && String(message.text || '').trim().length > 0);
    if (!lastAssistantMessage) {
      return;
    }
    await copyMessageText(lastAssistantMessage.text);
  }

  function normalizeComposerForSlash(value: string) {
    if (!value.startsWith('/') && !value.startsWith('$')) {
      setSlashMenuOpen(false);
      setSlashMenuIndex(0);
      return;
    }
    setSlashMenuOpen(true);
    setSlashMenuIndex(0);
  }

  useLayoutEffect(() => {
    const element = composerRef.current;
    if (!element) {
      return;
    }
    element.style.height = 'auto';
    const nextHeight = Math.max(36, Math.min(element.scrollHeight, 120));
    element.style.height = `${nextHeight}px`;
    element.style.overflowY = element.scrollHeight > 120 ? 'auto' : 'hidden';
    setIsComposerMultiline(element.scrollHeight > 48);
  }, [composer]);

  useEffect(() => {
    if (!messageMenu) {
      return;
    }
    const close = () => setMessageMenu(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close();
      }
    };
    window.addEventListener('click', close);
    window.addEventListener('scroll', close, true);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [messageMenu]);

  useLayoutEffect(() => {
    if (!slashMenuOpen) {
      return;
    }
    if (slashCommandSelectedIndex > visibleSlashCommands.length - 1) {
      setSlashMenuIndex(0);
    }
  }, [slashMenuOpen, slashCommandSelectedIndex, visibleSlashCommands.length]);

  return (
    <main className={`workspace ${isComposerFocused ? 'workspace--composer-focused' : ''}`} aria-label="Elyan chat">
      <div className="workspace-topbar">
        <img src={logoUrl} alt="Elyan" />
      </div>

      <section ref={timelineRef} className={`timeline ${messages.length === 0 ? 'timeline--empty' : ''}`} aria-live="polite">
        {messages.length === 0 ? (
          <div className="empty-state">
            <img src={emptyStateImage} alt="" aria-hidden="true" className="empty-state__graphic" />
            <h1>{emptyStateGreeting}</h1>
          </div>
        ) : (
          <div className="message-stack">
            {messages.map((message, index) => {
              const meta = asRecord(message.meta);
              const blocks = normalizeElyanBlocks((message as unknown as Record<string, unknown>).blocks ?? meta.blocks);
              const selectedArtifacts = asArray(meta.selectedArtifacts).map(asRecord);
              const planPreview = meta.planPreview;
              const isPlainAssistantMessage = message.role !== 'user';
              const isPendingUser = message.id === 'pending-user';
              const shouldType = message.role === 'assistant' && !seenMessageIds.has(message.id);
              return (
                <article
                  className={`message message--${message.role} ${isPlainAssistantMessage ? 'message--plain' : ''}`}
                  key={message.id}
                  onContextMenu={(event: MouseEvent<HTMLElement>) => {
                    if (isPendingUser) return;
                    event.preventDefault();
                    setMessageMenu({
                      x: event.clientX,
                      y: event.clientY,
                      text: message.text,
                    });
                  }}
                >
                  {message.role === 'assistant' ? (
                    blocks.length > 0 ? (
                      <BlockListRenderer
                        blocks={blocks}
                        shouldType={shouldType}
                        onFinished={() => setSeenMessageIds((prev) => new Set(prev).add(message.id))}
                      />
                    ) : (
                      <TypewriterText 
                        text={message.text} 
                        shouldType={shouldType} 
                        onFinished={() => setSeenMessageIds((prev) => new Set(prev).add(message.id))} 
                      />
                    )
                  ) : (
                    <p>{message.text}</p>
                  )}
                  {selectedArtifacts.length > 0 ? (
                    <div className="message-attachments" aria-label="Mesaj ekleri">
                      {selectedArtifacts.map((artifact, index) => {
                        const artifactKind = asString(artifact.kind);
                        const artifactPath = asString(artifact.path);
                        const artifactUrl = asString(artifact.url) || fileUrlFromPath(artifactPath);
                        const artifactName = asString(artifact.name) || `Ek ${index + 1}`;
                        const isImage = artifactKind === 'image' || /\.(png|jpe?g|gif|webp|heic|heif|avif)$/i.test(artifactPath);
                        return (
                          <div className="message-attachment" key={`${message.id}-${artifactName}-${index}`}>
                            {isImage && artifactUrl ? <img src={artifactUrl} alt="" /> : <span className="message-attachment__icon">□</span>}
                            <div className="message-attachment__copy">
                              <strong>{artifactName}</strong>
                              <small>{artifactKind || 'artifact'}</small>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  {message.needsConfirmation && message.pendingPlanId ? (
                    <div className="approval-card">
                      <strong>Onay gerekiyor</strong>
                      <span>{typeof planPreview === 'string' && planPreview ? planPreview : 'Plan yürütülmeden önce açık onay bekliyor.'}</span>
                      <div className="approval-card__actions">
                        <button type="button" disabled={busy} onClick={() => onConfirmPlan(message.pendingPlanId, true)}>
                          Onayla
                        </button>
                        <button type="button" disabled={busy} onClick={() => onConfirmPlan(message.pendingPlanId, false)}>
                          Reddet
                        </button>
                      </div>
                    </div>
                  ) : meta.permissionNeeded === true ? (
                    <div className="approval-card">
                      <strong>{asString(meta.permissionErrorCode) === 'OS_PERMISSION_REQUIRED' ? 'Sistem izni gerekiyor' : 'İzin gerekiyor'}</strong>
                      <span>{asString(meta.permissionReason) || 'Bu işlem için önce yerel izinleri açman gerekiyor.'}</span>
                      <div className="approval-card__actions">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => onOpenPermissionSettings(asString(meta.permissionKey), asString(meta.systemPermissionKey))}
                        >
                          İzinleri aç
                        </button>
                      </div>
                    </div>
                  ) : null}
                </article>
              );
            })}
            
            {busy && messages.length > 0 && messages[messages.length - 1]?.role === 'user' && (
              <article className="message message--assistant message--plain">
                <div className="typing-indicator" aria-label="Elyan yazıyor...">
                  <span className="typing-dot"></span>
                  <span className="typing-dot"></span>
                  <span className="typing-dot"></span>
                </div>
              </article>
            )}
          </div>
        )}
      </section>

      {showAgentStatus ? (
        <div className="composer-status" aria-live="polite" aria-busy="true">
          <div className="composer-status__dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </div>
      ) : null}

      {lastError ? <div className="safe-error">{lastError}</div> : null}

      {chatLocked ? (
        <section className="quota-lock-card" aria-live="polite">
          <strong>{chatLockTitle}</strong>
          <p>{chatLockDetail}</p>
        </section>
      ) : (
        <form
          className={[
            'composer',
            isComposerDragActive ? 'composer--drag-active' : '',
            busy ? 'composer--busy' : '',
            isComposerFocused ? 'composer--focused' : '',
            composer.trim().length > 0 ? 'composer--typing' : 'composer--idle',
            isComposerMultiline ? 'composer--multiline' : '',
            lastError ? 'composer--error' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
          onDragEnter={(event) => {
            event.preventDefault();
            setIsComposerDragActive(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            if (!isComposerDragActive) {
              setIsComposerDragActive(true);
            }
          }}
          onDragLeave={(event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
              return;
            }
            setIsComposerDragActive(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setIsComposerDragActive(false);
            const files = attachmentFilesFromDrop(event);
            if (files.length > 0) {
              onPasteFiles(files);
            }
          }}
        >
          <input
            ref={fileInputRef}
            className="composer__file-input"
            type="file"
            multiple
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              if (files.length > 0) {
                onPasteFiles(files);
              }
              event.currentTarget.value = '';
            }}
          />
          <input
            ref={imageInputRef}
            className="composer__file-input"
            type="file"
            multiple
            accept="image/*"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              if (files.length > 0) {
                onPasteFiles(files);
              }
              event.currentTarget.value = '';
            }}
          />
          {composerAttachments.length > 0 ? (
          <div className="composer-attachments" aria-label="Ekler">
              {composerAttachments.map((attachment) => (
                <article className="composer-attachment" key={attachmentIdentity(attachment)}>
                  {attachment.kind === 'image' && (attachment.url || attachment.path) ? (
                    <img className="composer-attachment__preview" src={attachment.url || fileUrlFromPath(attachment.path || '')} alt="" />
                  ) : (
                    <div className="composer-attachment__preview composer-attachment__preview--empty" aria-hidden="true" />
                  )}
                  <div className="composer-attachment__copy">
                    <strong>{attachment.name || 'Ek'}</strong>
                    <span>{attachment.mimeType || 'application/octet-stream'}</span>
                  </div>
                  <div className="composer-attachment__meta">{formatAttachmentSize(attachment.sizeBytes)}</div>
                  <button
                    type="button"
                    className="composer-attachment__remove"
                    onClick={() => onRemoveComposerAttachment(attachmentIdentity(attachment))}
                  >
                    Kaldır
                  </button>
                </article>
              ))}
            </div>
          ) : null}
          {slashMenuOpen && visibleSlashCommands.length > 0 ? (
            <div className="composer-slash-menu" role="menu" aria-label="Komutlar">
              {visibleSlashCommands.map((command, index) => (
                <button
                  type="button"
                  key={command.id}
                  className={index === slashCommandSelectedIndex ? 'composer-slash-menu__item is-active' : 'composer-slash-menu__item'}
                  onMouseDown={(event) => {
                    event.preventDefault();
                  }}
                  onMouseEnter={() => setSlashMenuIndex(index)}
                  onClick={() => runSlashCommand(command)}
                >
                  <div className="composer-slash-menu__item-main">
                  <strong>{command.prefix}{command.id}</strong>
                  <span> - {command.label}</span>
                </div>
              </button>
            ))}
            </div>
          ) : null}
          <div className={`composer__controls ${busy ? 'composer__controls--busy' : ''}`}>
            <button type="button" className="composer__tool" aria-label="Dosya ekle" onClick={() => fileInputRef.current?.click()}>
              +
            </button>
            <textarea
              ref={composerRef}
              aria-label="Mesaj yaz"
              value={composer}
              onChange={(event) => {
                const value = event.currentTarget.value;
                onComposerChange(value);
                normalizeComposerForSlash(value);
              }}
              onFocus={() => {
                setIsComposerFocused(true);
                if (composer.startsWith('/') || composer.startsWith('$')) {
                  setSlashMenuOpen(true);
                }
              }}
              onPaste={(event) => {
                const files = attachmentFilesFromClipboard(event);
                const hasText = event.clipboardData.getData('text/plain');
                
                // If there's text, and ALL captured "files" are just HTML/TXT representations 
                // of the copied text (which browsers often create), we should ignore the files
                // and let the default text paste happen!
                const isOnlyTextRepresentations = files.length > 0 && files.every(f => f.type === 'text/plain' || f.type === 'text/html');
                
                if (files.length === 0 || (hasText && isOnlyTextRepresentations)) {
                  return;
                }
                
                event.preventDefault();
                onPasteFiles(files);
              }}
              onKeyDown={(event) => {
                const modifier = event.metaKey || event.ctrlKey;
                if (modifier && !event.altKey) {
                  const normalizedKey = event.key.toLowerCase();
                  if (normalizedKey === 'enter') {
                    event.preventDefault();
                    if ((composer.trim().length === 0 && composerAttachments.length === 0) || busy) {
                      return;
                    }
                    onSend();
                    return;
                  }
                  if (normalizedKey === 'o') {
                    event.preventDefault();
                    fileInputRef.current?.click();
                    return;
                  }
                  if (normalizedKey === 'i' && event.shiftKey) {
                    event.preventDefault();
                    imageInputRef.current?.click();
                    return;
                  }
                  if (normalizedKey === 'backspace') {
                    event.preventDefault();
                    onClearComposer();
                    return;
                  }
                  if (normalizedKey === 'n') {
                    event.preventDefault();
                    onCreateConversation();
                    return;
                  }
                  if (normalizedKey === 'l') {
                    event.preventDefault();
                    composerRef.current?.focus();
                    return;
                  }
                  if (normalizedKey === '/') {
                    event.preventDefault();
                    setSlashMenuOpen(true);
                    return;
                  }
                }
                if (slashMenuOpen && visibleSlashCommands.length > 0) {
                  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault();
                    const delta = event.key === 'ArrowDown' ? 1 : -1;
                    const nextIndex = (slashCommandSelectedIndex + delta + visibleSlashCommands.length) % visibleSlashCommands.length;
                    setSlashMenuIndex(nextIndex);
                    return;
                  }
                  if (event.key === 'Enter' || event.key === 'Tab') {
                    event.preventDefault();
                    runSlashCommand(visibleSlashCommands[slashCommandSelectedIndex] ?? visibleSlashCommands[0]!);
                    return;
                  }
                  if (event.key === 'Escape') {
                    event.preventDefault();
                    setSlashMenuOpen(false);
                    return;
                  }
                }
                if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.metaKey || event.ctrlKey) {
                  return;
                }
                if (event.nativeEvent.isComposing) {
                  return;
                }
                if ((composer.trim().length === 0 && composerAttachments.length === 0) || busy) {
                  event.preventDefault();
                  return;
                }
                event.preventDefault();
                onSend();
              }}
              onContextMenu={() => {
                setSlashMenuOpen(false);
              }}
              onBlur={() => {
                setIsComposerFocused(false);
                window.setTimeout(() => setSlashMenuOpen(false), 100);
              }}
              placeholder="Elyan'a sor"
              rows={1}
              readOnly={busy}
            />
            {/* Microphone button for dictation */}
            <button
              type="button"
              id="composer-dictation-btn"
              className={[
                'composer__tool',
                'composer__tool--mic',
                isDictationActive ? 'composer__tool--mic-active' : '',
                dictationState.state === 'error' ? 'composer__tool--mic-error' : '',
              ].filter(Boolean).join(' ')}
              aria-label={
                dictationState.state === 'downloading_model'
                  ? `Model indiriliyor (${dictationState.downloadProgress ?? 0}%)`
                  : dictationState.state === 'listening'
                  ? 'Dikteyi durdur'
                  : dictationState.state === 'transcribing'
                  ? 'Çevriliyor...'
                  : dictationState.state === 'error'
                  ? `Hata: ${dictationState.error ?? 'Mikrofon hatası'}`
                  : 'Dikte et'
              }
              title={
                !dictationState.binaryAvailable
                  ? 'Konuşma motoru bulunamadı'
                  : !dictationState.modelAvailable && dictationState.state !== 'downloading_model'
                  ? 'Modeli indirmek için tıklayın'
                  : undefined
              }
              disabled={busy || dictationState.state === 'transcribing' || dictationState.state === 'requesting_permission' || dictationState.state === 'downloading_model'}
              onClick={async () => {
                if (dictationState.state === 'listening') {
                  await stopDictation();
                } else if (isDictationActive) {
                  await cancelDictation();
                } else {
                  await startDictation({});
                }
              }}
            >
              {dictationState.state === 'downloading_model' ? (
                <span style={{ fontSize: '10px', fontWeight: 600 }}>{dictationState.downloadProgress ?? 0}%</span>
              ) : dictationState.state === 'transcribing' ? (
                <span className="composer__send-spinner" aria-hidden="true" />
              ) : dictationState.state === 'listening' ? (
                /* Stop icon when listening */
                <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" width="14" height="14">
                  <rect x="5" y="5" width="10" height="10" rx="2" fill="currentColor" />
                </svg>
              ) : dictationState.state === 'error' ? (
                /* Error icon */
                <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" width="15" height="15">
                  <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" fill="none" />
                  <line x1="10" y1="6" x2="10" y2="11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <circle cx="10" cy="14" r="1" fill="currentColor" />
                </svg>
              ) : (
                /* Mic icon at idle */
                <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false" width="15" height="15">
                  <rect x="7" y="1" width="6" height="10" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none" />
                  <path d="M4 10a6 6 0 0 0 12 0" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
                  <line x1="10" y1="16" x2="10" y2="19" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <line x1="7" y1="19" x2="13" y2="19" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              )}
            </button>
            <button
              type="button"
              className={`composer__send ${busy ? 'composer__send--stop' : ''}`}
              aria-label={busy ? 'Durdur' : 'Mesaj gönder'}
              onClick={(e) => {
                if (busy) {
                  e.preventDefault();
                  // For now, Elyan doesn't expose a hard stop method through props, so it acts visually as a stop request.
                } else {
                  if (composer.trim().length === 0 && composerAttachments.length === 0) return;
                  onSend();
                }
              }}
              disabled={!busy && composer.trim().length === 0 && composerAttachments.length === 0}
            >
              {busy ? (
                <svg className="composer__send-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                  <rect x="6" y="6" width="8" height="8" rx="1.5" fill="currentColor" />
                </svg>
              ) : (
                <svg className="composer__send-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                  <path d="M4 10h8.5m-3.5-4.5L14.5 10l-5.5 4.5" />
                </svg>
              )}
            </button>
          </div>
          {/* Partial transcript ghost text */}
          {dictationState.partialTranscript ? (
            <div className="composer__dictation-partial" aria-live="polite" aria-label="Kısmi transkript">
              <span>{dictationState.partialTranscript}</span>
            </div>
          ) : null}
          {lastError ? (
            <div className="composer__status composer__status--error" aria-live="polite">
              <span>{lastError}</span>
              <button type="button" onClick={() => onSend()} aria-label="Yeniden dene">
                Yeniden dene
              </button>
            </div>
          ) : null}
        </form>
      )}


      {messageMenu ? (
        <div className="message-context-menu" style={{ left: `${messageMenu.x}px`, top: `${messageMenu.y}px` }} role="menu" aria-label="Mesaj menüsü" onClick={(event) => event.stopPropagation()}>
          <button
            type="button"
            onClick={async () => {
              await copyMessageText(messageMenu.text);
              setMessageMenu(null);
            }}
          >
            Kopyala
          </button>
        </div>
      ) : null}
    </main>
  );
}

const defaultDesktopTaskShell: DesktopTaskShellView = {
  readinessToken: 'offline',
  readinessLabel: 'Desktop çevrimdışı',
  readinessDetail: 'Runtime truth yükleniyor.',
  readinessTone: 'neutral',
  desktopHeadline: 'Elyan Desktop',
  connectionSummary: 'Runtime truth yükleniyor.',
  modelLabel: 'Elyan beyni',
  learningLabel: 'Öğrenme bilgisi yok',
  retrievalLabel: 'Retrieval bilgisi yok',
  pendingRemoteTaskCount: 0,
  activeRemoteTaskCount: 0,
  approvalTasks: [],
  recentTasks: [],
  canReceiveTasks: false,
  canExecuteAssignedTasks: false,
  powerCapabilityCount: 0,
  blockedCapabilityCount: 0,
};

function noop() {
  // Optional desktop task actions are injected by App in production.
}

function noopApproveTask(_taskId: string, _approved: boolean) {
  // Optional desktop task actions are injected by App in production.
}

function formatAttachmentSize(sizeBytes: number): string {
  const safeSize = Math.max(0, Math.floor(sizeBytes || 0));
  if (safeSize < 1024) {
    return `${safeSize} B`;
  }
  if (safeSize < 1024 * 1024) {
    return `${(safeSize / 1024).toFixed(1)} KB`;
  }
  return `${(safeSize / (1024 * 1024)).toFixed(1)} MB`;
}

function TypewriterText({ text, shouldType, onFinished }: { text: string; shouldType: boolean; onFinished: () => void }) {
  const displayedText = useProgressiveText(text, shouldType, onFinished);

  return <p>{displayedText}</p>;
}
