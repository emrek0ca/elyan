"use client";

import { useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import {
  BarChart3,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  ExternalLink,
  File,
  FileText,
  Image as ImageIcon,
  Table2
} from 'lucide-react';
import { ChatMessageBlock } from '@/lib/chat-block-parser';

interface BlockRendererProps {
  block: ChatMessageBlock;
  onApprove?: (taskId: string) => void;
}

type ChartPoint = {
  label: string;
  value: number;
  color?: string;
};

type SortState = {
  columnIndex: number;
  ascending: boolean;
} | null;

export function BlockRenderer({ block, onApprove }: BlockRendererProps) {
  if (block.visibility === 'assistant_internal_by_default') {
    return null;
  }

  switch (block.type) {
    case 'text':
      return <MarkdownBlock markdown={block.markdown || ''} tone={block.renderHints?.tone} />;

    case 'summary':
      return (
        <div className="mb-4 rounded-lg border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.05)] p-3">
          {block.title && <h4 className="mb-1 text-sm font-bold opacity-80">{block.title}</h4>}
          <p className="text-sm">{block.summary}</p>
        </div>
      );

    case 'code':
      return <CodeBlock block={block} />;

    case 'table':
      return <TableBlock block={block} />;

    case 'chart':
      return <ChartBlock block={block} />;

    case 'file':
      return <FileBlock block={block} />;

    case 'math':
      return <MathBlock block={block} />;

    case 'artifact':
      return <ArtifactBlock block={block} />;

    case 'next_steps':
      return (
        <div className="mt-4 border-t border-[rgba(255,255,255,0.1)] pt-4">
          {block.title && <h4 className="mb-2 text-sm font-bold opacity-80">{block.title}</h4>}
          <ul className="list-disc space-y-1 pl-5">
            {Array.isArray(block.items) && block.items.map((item: any, i: number) => (
              <li key={i} className="text-sm">{typeof item === 'string' ? item : item.label}</li>
            ))}
          </ul>
        </div>
      );

    case 'status':
      return (
        <div className="my-2 flex flex-col gap-1 rounded-xl border border-blue-500/20 bg-blue-500/10 p-3 text-blue-500">
          <div className="flex items-center gap-2">
            {['running', 'waiting_approval', 'retrying'].includes(block.status || '') && (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
            )}
            <span className="text-sm font-semibold capitalize">{block.status?.replace('_', ' ')}</span>
          </div>
          {block.title && <div className="text-sm font-medium">{block.title}</div>}
          {block.detail && <div className="text-xs opacity-80">{block.detail}</div>}
        </div>
      );

    case 'actionable':
      if (block.kind === 'approval_needed') {
        return (
          <div className="my-3 rounded-xl border border-orange-500/30 bg-orange-500/10 p-4">
            {block.title && <h4 className="mb-1 font-bold text-orange-500">{block.title}</h4>}
            {block.detail && <p className="mb-3 text-sm text-orange-500/85">{block.detail}</p>}
            <button
              onClick={() => onApprove && block.raw?.taskId && onApprove(block.raw.taskId)}
              className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-orange-600"
            >
              Onay Ver
            </button>
          </div>
        );
      }
      return (
        <div className="my-2 rounded-lg border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.05)] p-3">
          <div className="text-sm font-medium">{block.title || 'Action Required'}</div>
        </div>
      );

    case 'task_trace':
    case 'attachment_context':
    case 'context_signal':
    case 'block_group':
      return (
        <div className="my-2 rounded-lg border border-[rgba(255,255,255,0.05)] bg-[rgba(255,255,255,0.02)] p-3">
          {block.title && <div className="mb-2 text-xs font-bold uppercase tracking-wider opacity-60">{block.title}</div>}
          <div className="whitespace-pre-wrap text-sm opacity-80">{block.markdown || block.detail || JSON.stringify(block.items)}</div>
        </div>
      );

    default:
      if (block.markdown || block.detail || block.summary) {
        return <MarkdownBlock markdown={block.markdown || block.detail || block.summary || ''} tone={block.renderHints?.tone} />;
      }
      return null;
  }
}

function MarkdownBlock({ markdown, tone }: { markdown: string; tone?: string }) {
  return (
    <div className={`prose prose-sm md:prose-base max-w-none text-inherit ${tone === 'caution' ? 'text-orange-500' : ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          p: ({node, ...props}: any) => <p className="mb-2 last:mb-0" {...props} />,
          a: ({node, ...props}: any) => <a className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer" {...props} />,
          code: ({node, inline, className, children, ...props}: any) => {
            const match = /language-(\w+)/.exec(className || '');
            return !inline && match ? (
              <div className="relative my-4 overflow-hidden rounded-xl border border-[rgba(255,255,255,0.1)] bg-[#1A1A1A]">
                <div className="flex items-center justify-between border-b border-[rgba(255,255,255,0.05)] bg-[rgba(255,255,255,0.05)] px-4 py-2">
                  <span className="font-mono text-xs text-[rgba(255,255,255,0.5)]">{match[1]}</span>
                </div>
                <pre className="overflow-x-auto p-4 text-sm text-[rgba(255,255,255,0.9)]">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              </div>
            ) : (
              <code className="rounded-md bg-[var(--outline)] px-1.5 py-0.5 font-mono text-sm text-pink-600" {...props}>
                {children}
              </code>
            );
          }
        } as any}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

function CodeBlock({ block }: { block: ChatMessageBlock }) {
  const [collapsed, setCollapsed] = useState(false);
  const [copied, setCopied] = useState(false);
  const raw = block.raw || {};
  const code = readString(raw, ['code', 'content', 'markdown']) || block.markdown || '';
  const language = readString(raw, ['language', 'lang']) || 'text';
  const filename = readString(raw, ['filename', 'file']);

  const copyCode = async () => {
    await navigator.clipboard?.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  if (!code.trim()) return null;

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/55">
      <div className="flex items-center gap-2 border-b border-[var(--outline)] px-3 py-2 text-xs text-[var(--text-muted)]">
        <span className="rounded bg-[var(--primary-soft)] px-2 py-0.5 font-mono text-[var(--secondary)]">{language}</span>
        {filename && <span className="truncate">{filename}</span>}
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={copyCode} className="rounded-full p-1.5 hover:bg-[var(--text)]/5" aria-label="Kodu kopyala">
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
          <button type="button" onClick={() => setCollapsed((value) => !value)} className="rounded-full p-1.5 hover:bg-[var(--text)]/5" aria-label={collapsed ? 'Kodu aç' : 'Kodu kapat'}>
            {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
        </div>
      </div>
      {!collapsed && (
        <pre className="max-h-[520px] overflow-auto p-3 text-[13px] leading-6 text-[var(--text)]">
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}

function TableBlock({ block }: { block: ChatMessageBlock }) {
  const raw = block.raw || {};
  const columns = useMemo(() => normalizeColumns(raw), [raw]);
  const rows = useMemo(() => normalizeRows(raw, columns), [raw, columns]);
  const [sort, setSort] = useState<SortState>(null);
  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => compareCells(a[sort.columnIndex] || '', b[sort.columnIndex] || '', sort.ascending));
  }, [rows, sort]);

  if (columns.length === 0 || rows.length === 0) return null;

  const toggleSort = (columnIndex: number) => {
    setSort((current) => {
      if (current?.columnIndex === columnIndex) {
        return { columnIndex, ascending: !current.ascending };
      }
      return { columnIndex, ascending: true };
    });
  };

  const copyCsv = async () => {
    const csv = [columns, ...rows]
      .map((row) => row.map(csvCell).join(','))
      .join('\n');
    await navigator.clipboard?.writeText(csv);
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/35">
      <div className="flex items-center gap-2 border-b border-[var(--outline)] px-3 py-2 text-xs text-[var(--text-muted)]">
        <Table2 size={14} />
        <span className="font-medium">{readString(raw, ['caption', 'title']) || block.title || 'Tablo'}</span>
        <button type="button" onClick={copyCsv} className="ml-auto rounded-full p-1.5 hover:bg-[var(--text)]/5" aria-label="CSV kopyala">
          <Copy size={14} />
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-left text-sm">
          <thead className="bg-[var(--surface-2)]/55 text-xs text-[var(--text-muted)]">
            <tr>
              {columns.map((column, index) => (
                <th key={`${column}-${index}`} className="whitespace-nowrap px-3 py-2 font-semibold">
                  <button type="button" onClick={() => toggleSort(index)} className="inline-flex items-center gap-1 hover:text-[var(--text)]">
                    {column}
                    {sort?.columnIndex === index && (sort.ascending ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-t border-[var(--outline)]/70">
                {columns.map((_, columnIndex) => (
                  <td key={columnIndex} className="max-w-[280px] whitespace-pre-wrap px-3 py-2 align-top text-[var(--text)]">
                    {row[columnIndex] || ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChartBlock({ block }: { block: ChatMessageBlock }) {
  const raw = block.raw || {};
  const points = normalizeChartPoints(raw);
  const title = readString(raw, ['title']) || block.title || 'Grafik';
  const chartType = (readString(raw, ['chartType', 'chart_type', 'chartKind', 'type']) || 'bar').toLowerCase();
  const expression = readString(raw, ['expression', 'expr']);

  if (points.length === 0 && !expression) return null;

  return (
    <div className="my-3 rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/35 p-3">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium text-[var(--text-muted)]">
        <BarChart3 size={14} />
        <span>{title}</span>
      </div>
      {expression ? (
        <div className="rounded-lg border border-[var(--outline)] bg-[var(--background)]/40 p-3 font-mono text-sm">
          {expression}
        </div>
      ) : chartType === 'line' ? (
        <LineChart points={points} />
      ) : chartType === 'pie' ? (
        <PieSummary points={points} />
      ) : (
        <BarSummary points={points} />
      )}
    </div>
  );
}

function FileBlock({ block }: { block: ChatMessageBlock }) {
  const raw = block.raw || {};
  const name = readString(raw, ['name', 'filename', 'fileName']) || block.title || 'Dosya';
  const mimeType = readString(raw, ['mimeType', 'mime_type', 'contentType']) || 'application/octet-stream';
  const uri = readString(raw, ['uri', 'url', 'path']);
  const preview = readString(raw, ['preview', 'previewText', 'summary']) || block.summary || block.detail || '';
  const size = raw.sizeBytes ?? raw.size ?? raw.fileSize;
  const Icon = mimeType.includes('pdf') ? FileText : mimeType.startsWith('image/') ? ImageIcon : mimeType.includes('csv') ? Table2 : File;

  const content = (
    <div className="my-2 flex items-start gap-3 rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/45 p-3 text-sm">
      <div className="rounded-lg bg-[var(--primary-soft)] p-2 text-[var(--secondary)]">
        <Icon size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold text-[var(--text)]">{name}</div>
        <div className="mt-0.5 text-xs text-[var(--text-muted)]">
          {[formatBytes(size), mimeType].filter(Boolean).join(' · ')}
        </div>
        {preview && <div className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--text-muted)]">{preview}</div>}
      </div>
      {uri && <ExternalLink size={14} className="mt-1 shrink-0 text-[var(--text-muted)]" />}
    </div>
  );

  if (!uri) return content;
  return (
    <a href={uri} target="_blank" rel="noopener noreferrer">
      {content}
    </a>
  );
}

function MathBlock({ block }: { block: ChatMessageBlock }) {
  const raw = block.raw || {};
  const content = readString(raw, ['content', 'latex', 'markdown']) || block.markdown || '';
  if (!content.trim()) return null;
  return (
    <div className="my-3 overflow-x-auto rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/35 p-3 font-mono text-sm leading-6">
      {content}
    </div>
  );
}

function ArtifactBlock({ block }: { block: ChatMessageBlock }) {
  const raw = block.raw || {};
  const url = readString(raw, ['url', 'uri', 'src']);
  const title = readString(raw, ['title']) || block.title || 'Çıktı';
  const mime = readString(raw, ['mime', 'mimeType']);
  const artifactType = readString(raw, ['artifactType', 'artifact_type']) || 'artifact';
  const isImage = artifactType.includes('image') || mime.startsWith('image/');
  if (!url) return null;

  if (isImage) {
    return (
      <figure className="my-3 overflow-hidden rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/35">
        <img src={url} alt={title} className="max-h-[520px] w-full object-contain" />
        <figcaption className="border-t border-[var(--outline)] px-3 py-2 text-xs text-[var(--text-muted)]">{title}</figcaption>
      </figure>
    );
  }

  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="my-2 flex items-center gap-2 rounded-xl border border-[var(--outline)] bg-[var(--background-deep)]/45 p-3 text-sm hover:border-[var(--outline-strong)]">
      <File size={16} />
      <span>{title}</span>
      <ExternalLink size={14} className="ml-auto text-[var(--text-muted)]" />
    </a>
  );
}

function BarSummary({ points }: { points: ChartPoint[] }) {
  const max = Math.max(...points.map((point) => Math.abs(point.value)), 1);
  return (
    <div className="space-y-2">
      {points.map((point, index) => (
        <div key={`${point.label}-${index}`} className="grid grid-cols-[minmax(72px,1fr)_3fr_auto] items-center gap-2 text-xs">
          <span className="truncate text-[var(--text-muted)]">{point.label || `Veri ${index + 1}`}</span>
          <div className="h-2 overflow-hidden rounded-full bg-[var(--surface-2)]">
            <div className="h-full rounded-full bg-[var(--secondary)]" style={{ width: `${Math.max(4, (Math.abs(point.value) / max) * 100)}%` }} />
          </div>
          <span className="font-medium text-[var(--text)]">{formatNumber(point.value)}</span>
        </div>
      ))}
    </div>
  );
}

function LineChart({ points }: { points: ChartPoint[] }) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const svgPoints = points.map((point, index) => {
    const x = points.length === 1 ? 50 : (index / (points.length - 1)) * 100;
    const y = 90 - ((point.value - min) / span) * 75;
    return `${x},${y}`;
  }).join(' ');

  return (
    <div>
      <svg viewBox="0 0 100 100" className="h-44 w-full overflow-visible">
        <polyline points={svgPoints} fill="none" stroke="var(--secondary)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {points.map((point, index) => {
          const [x, y] = svgPoints.split(' ')[index].split(',').map(Number);
          return <circle key={index} cx={x} cy={y} r="2.8" fill="var(--secondary)" />;
        })}
      </svg>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-[var(--text-muted)] md:grid-cols-3">
        {points.slice(0, 6).map((point, index) => (
          <span key={`${point.label}-${index}`} className="truncate">{point.label}: {formatNumber(point.value)}</span>
        ))}
      </div>
    </div>
  );
}

function PieSummary({ points }: { points: ChartPoint[] }) {
  const total = points.reduce((sum, point) => sum + Math.abs(point.value), 0) || 1;
  return (
    <div className="space-y-2">
      {points.map((point, index) => {
        const percent = (Math.abs(point.value) / total) * 100;
        return (
          <div key={`${point.label}-${index}`} className="flex items-center gap-2 text-xs">
            <span className="h-2.5 w-2.5 rounded-full bg-[var(--secondary)] opacity-80" style={{ opacity: 0.45 + ((index % 4) * 0.12) }} />
            <span className="min-w-0 flex-1 truncate text-[var(--text-muted)]">{point.label || `Veri ${index + 1}`}</span>
            <span className="font-medium text-[var(--text)]">{percent.toFixed(1)}%</span>
          </div>
        );
      })}
    </div>
  );
}

function readString(raw: Record<string, any>, keys: string[]): string {
  for (const key of keys) {
    const value = raw[key];
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return cleanInlineText(text);
  }
  return '';
}

function normalizeColumns(raw: Record<string, any>): string[] {
  const rawColumns = Array.isArray(raw.columns) ? raw.columns : Array.isArray(raw.headers) ? raw.headers : [];
  const columns = rawColumns
    .map((column: any) => {
      if (column && typeof column === 'object') {
        return cleanCell(column.label ?? column.title ?? column.name ?? column.key ?? column.id);
      }
      return cleanCell(column);
    })
    .filter(Boolean);

  if (columns.length > 0) return columns;

  const rawRows = Array.isArray(raw.rows) ? raw.rows : Array.isArray(raw.data) ? raw.data : Array.isArray(raw.items) ? raw.items : [];
  const firstMap = rawRows.find((row: any) => row && typeof row === 'object' && !Array.isArray(row));
  if (firstMap) return Object.keys(firstMap).map(cleanCell).filter(Boolean);
  const firstArray = rawRows.find((row: any) => Array.isArray(row));
  if (firstArray) return firstArray.map((_: any, index: number) => `Sütun ${index + 1}`);
  return [];
}

function normalizeRows(raw: Record<string, any>, columns: string[]): string[][] {
  const rawRows = Array.isArray(raw.rows) ? raw.rows : Array.isArray(raw.data) ? raw.data : Array.isArray(raw.items) ? raw.items : [];
  return rawRows.map((row: any) => {
    if (Array.isArray(row)) return row.map(cleanCell);
    if (row && typeof row === 'object') {
      if (columns.length > 0 && columns.some((column) => Object.prototype.hasOwnProperty.call(row, column))) {
        return columns.map((column) => cleanCell(row[column]));
      }
      return Object.values(row).map(cleanCell);
    }
    return [cleanCell(row)];
  }).filter((row: string[]) => row.some(Boolean));
}

function normalizeChartPoints(raw: Record<string, any>): ChartPoint[] {
  const rawPoints = Array.isArray(raw.data) ? raw.data : Array.isArray(raw.points) ? raw.points : [];
  return rawPoints
    .filter((point: any) => point && typeof point === 'object')
    .map((point: any) => ({
      label: cleanInlineText(point.label ?? point.x ?? point.name ?? ''),
      value: Number(point.value ?? point.y ?? point.v ?? 0) || 0,
      color: typeof point.color === 'string' ? point.color : undefined
    }));
}

function compareCells(a: string, b: string, ascending: boolean): number {
  const numA = Number(a);
  const numB = Number(b);
  const comparison = !Number.isNaN(numA) && !Number.isNaN(numB)
    ? numA - numB
    : a.localeCompare(b, 'tr');
  return ascending ? comparison : -comparison;
}

function cleanCell(value: any): string {
  return cleanInlineText(value)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p\s*>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function cleanInlineText(value: any): string {
  return String(value ?? '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .trim();
}

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

function formatBytes(value: any): string {
  const size = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(size) || size <= 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(value);
}
