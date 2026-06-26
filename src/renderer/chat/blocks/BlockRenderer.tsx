import { memo, useMemo, useState, type ReactElement } from 'react';
import type { ElyanBlock } from '../../../shared/blocks/types';
import { asArray, asRecord, asString } from '../../lib/data';

type BlockRendererProps = {
  block: ElyanBlock;
  shouldType?: boolean;
  onFinished?: () => void;
};

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

function blockData(block: Record<string, unknown>): Record<string, unknown> {
  return asRecord(block.data ?? block.raw);
}

function blockBody(block: Record<string, unknown>): string {
  const data = blockData(block);
  return firstText(
    block.markdown,
    block.content,
    block.text,
    block.body,
    block.message,
    block.summary,
    data.markdown,
    data.content,
    data.text,
    data.body,
    data.message,
    data.summary,
  );
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

function safeHref(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (/^(https?:|file:|elyan:|data:image\/|blob:)/i.test(trimmed)) return trimmed;
  if (/^[a-zA-Z]:[\\/]/.test(trimmed)) return `file:///${encodeURI(trimmed.replace(/\\/g, '/'))}`;
  if (trimmed.startsWith('/')) return `file://${encodeURI(trimmed)}`;
  return '';
}

function maskPath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  const parts = trimmed.replace(/\\/g, '/').split('/').filter(Boolean);
  if (parts.length <= 2) return trimmed;
  return `.../${parts.slice(-2).join('/')}`;
}

function redactSecrets(value: string): string {
  return value
    .replace(/(api[_-]?key|token|secret|cookie|authorization)\s*[:=]\s*["']?[^"'\s]+/gi, '$1=[redacted]')
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/g, 'Bearer [redacted]');
}

function formatSize(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
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
    if (match.index > last) nodes.push({ kind: 'text', value: text.slice(last, match.index) });
    const bold = match[2] ?? match[3];
    const italic = match[4] ?? match[5];
    const code = match[6];
    const linkLabel = match[7];
    const linkHref = match[8];
    if (bold != null) nodes.push({ kind: 'bold', value: bold });
    else if (italic != null) nodes.push({ kind: 'italic', value: italic });
    else if (code != null) nodes.push({ kind: 'code', value: code });
    else if (linkLabel != null && linkHref != null) nodes.push({ kind: 'link', href: linkHref, label: linkLabel });
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push({ kind: 'text', value: text.slice(last) });
  return nodes;
}

function InlineMarkdown({ text }: { text: string }) {
  return (
    <>
      {parseInlineMarkdown(text).map((node, index) => {
        if (node.kind === 'bold') return <strong key={index}>{node.value}</strong>;
        if (node.kind === 'italic') return <em key={index}>{node.value}</em>;
        if (node.kind === 'code') return <code key={index}>{node.value}</code>;
        if (node.kind === 'link') {
          const href = safeHref(node.href);
          return href ? <a key={index} href={href} target="_blank" rel="noopener noreferrer">{node.label}</a> : <span key={index}>{node.label}</span>;
        }
        return <span key={index}>{node.value}</span>;
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
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? '';
    const trimmed = line.trim();
    if (!trimmed) { result.push({ kind: 'blank' }); index += 1; continue; }
    if (/^#\s/.test(trimmed)) { result.push({ kind: 'h1', text: trimmed.replace(/^#\s+/, '') }); index += 1; continue; }
    if (/^##\s/.test(trimmed)) { result.push({ kind: 'h2', text: trimmed.replace(/^##\s+/, '') }); index += 1; continue; }
    if (/^###\s/.test(trimmed)) { result.push({ kind: 'h3', text: trimmed.replace(/^###\s+/, '') }); index += 1; continue; }
    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) { result.push({ kind: 'hr' }); index += 1; continue; }
    if (/^```/.test(trimmed)) {
      const lang = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !/^```/.test((lines[index] ?? '').trim())) {
        codeLines.push(lines[index] ?? '');
        index += 1;
      }
      index += 1;
      result.push({ kind: 'code_fence', lang, lines: codeLines });
      continue;
    }
    if (/^[-*+]\s/.test(trimmed)) { result.push({ kind: 'ul', text: trimmed.replace(/^[-*+]\s+/, '') }); index += 1; continue; }
    const ordered = /^(\d+)\.\s(.+)/.exec(trimmed);
    if (ordered) { result.push({ kind: 'ol', num: Number.parseInt(ordered[1] ?? '0', 10), text: ordered[2] ?? '' }); index += 1; continue; }
    if (/^>\s/.test(trimmed)) { result.push({ kind: 'blockquote', text: trimmed.replace(/^>\s+/, '') }); index += 1; continue; }
    result.push({ kind: 'para', text: trimmed });
    index += 1;
  }
  return result;
}

function RichMarkdown({ text, compact = false }: { text: string; compact?: boolean }) {
  const blocks = parseMarkdownBlocks(text);
  const elements: ReactElement[] = [];
  let unordered: string[] = [];
  let ordered: Array<{ num: number; text: string }> = [];
  const flushUnordered = () => {
    if (unordered.length === 0) return;
    elements.push(<ul key={`ul-${elements.length}`}>{unordered.map((item, index) => <li key={index}><InlineMarkdown text={item} /></li>)}</ul>);
    unordered = [];
  };
  const flushOrdered = () => {
    if (ordered.length === 0) return;
    elements.push(<ol key={`ol-${elements.length}`} start={ordered[0]!.num}>{ordered.map((item, index) => <li key={index}><InlineMarkdown text={item.text} /></li>)}</ol>);
    ordered = [];
  };
  for (const block of blocks) {
    if (block.kind === 'ul') { flushOrdered(); unordered.push(block.text); continue; }
    if (block.kind === 'ol') { flushUnordered(); ordered.push({ num: block.num, text: block.text }); continue; }
    flushUnordered();
    flushOrdered();
    if (block.kind === 'blank') { if (!compact) elements.push(<div key={`br-${elements.length}`} className="md-spacer" />); continue; }
    if (block.kind === 'h1') { elements.push(<h2 key={`h1-${elements.length}`}><InlineMarkdown text={block.text} /></h2>); continue; }
    if (block.kind === 'h2') { elements.push(<h3 key={`h2-${elements.length}`}><InlineMarkdown text={block.text} /></h3>); continue; }
    if (block.kind === 'h3') { elements.push(<h4 key={`h3-${elements.length}`}><InlineMarkdown text={block.text} /></h4>); continue; }
    if (block.kind === 'hr') { elements.push(<hr key={`hr-${elements.length}`} />); continue; }
    if (block.kind === 'code_fence') { elements.push(<pre key={`pre-${elements.length}`} data-lang={block.lang || undefined}><code>{block.lines.join('\n')}</code></pre>); continue; }
    if (block.kind === 'blockquote') { elements.push(<blockquote key={`bq-${elements.length}`}><InlineMarkdown text={block.text} /></blockquote>); continue; }
    elements.push(<p key={`p-${elements.length}`}><InlineMarkdown text={block.text} /></p>);
  }
  flushUnordered();
  flushOrdered();
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
          : normalized === 'skipped'
            ? 'atlandı'
            : ['running', 'in_progress', 'started'].includes(normalized)
              ? 'sürüyor'
              : normalized || 'durum';
  const variant = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(normalized) ? 'success'
    : ['failed', 'error', 'cancelled', 'canceled'].includes(normalized) ? 'error'
    : ['running', 'started', 'in_progress'].includes(normalized) ? 'active'
    : normalized === 'waiting_approval' ? 'warn'
    : 'neutral';
  return <span className={`message-block__pill message-block__pill--${variant}`} title={normalized}>{label}</span>;
}

function TextBlock({ block }: { block: ElyanBlock }) {
  const title = firstText(block.title);
  const body = blockBody(block);
  if (!title && !body) return null;
  return (
    <section className="message-block message-block--text" aria-label={title || undefined}>
      {title ? <strong className="message-block__title">{title}</strong> : null}
      {body ? <div className="message-block__markdown"><RichMarkdown text={body} /></div> : null}
    </section>
  );
}

function CodeBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const code = firstText(block.code, data.code, block.content, data.content, block.markdown, data.markdown);
  const language = firstText(block.language, block.lang, data.language, data.lang);
  const filename = firstText(block.filename, block.file, data.filename, data.file);
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  if (!code) return null;
  return (
    <section className="message-block message-block--code" aria-label={filename || language || 'Kod'}>
      <div className="message-block__code-header">
        <span>{filename || language || 'Kod'}</span>
        <button type="button" className="message-block__copy" onClick={() => setCollapsed((value) => !value)}>
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

function TableBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const style = asRecord(block.style ?? data.style);
  const rawHighlightRules = asArray(block.highlightRules).length > 0
    ? asArray(block.highlightRules)
    : asArray(data.highlightRules).length > 0
      ? asArray(data.highlightRules)
      : asArray(style.highlightRules);
  const highlightRules = rawHighlightRules.map(asRecord).map((rule) => ({
    column: firstText(rule.column, rule.key, rule.field).toLowerCase(),
    match: firstText(rule.match, rule.value, rule.equals).toLowerCase(),
    tone: firstText(rule.tone, rule.variant).toLowerCase() || 'neutral',
  }));
  const rawColumns = asArray(block.columns).length > 0 ? asArray(block.columns) : asArray(data.columns ?? data.headers);
  const rawRows = asArray(block.rows).length > 0
    ? asArray(block.rows)
    : asArray(block.items).length > 0
      ? asArray(block.items)
      : asArray(data.rows ?? data.items);
  const columns = rawColumns.map(cleanStructuredText).filter(Boolean);
  const inferredColumns = columns.length > 0
    ? columns
    : rawRows.reduce<string[]>((acc, row) => {
      if (acc.length > 0) return acc;
      const record = asRecord(row);
      if (Object.keys(record).length > 0) return Object.keys(record);
      if (Array.isArray(row)) return Array.from({ length: row.length }, (_, index) => `Sütun ${index + 1}`);
      return acc;
    }, []);
  const rows = rawRows
    .map((row) => {
      if (Array.isArray(row)) return row.map(cleanStructuredText);
      const record = asRecord(row);
      if (Object.keys(record).length === 0) return [cleanStructuredText(row)].filter(Boolean);
      return inferredColumns.length > 0
        ? inferredColumns.map((column) => cleanStructuredText(record[column] ?? record[column.toLowerCase()]))
        : Object.values(record).map(cleanStructuredText);
    })
    .filter((row) => row.some(Boolean));
  const safeColumns = inferredColumns.length > 0
    ? inferredColumns
    : Array.from({ length: Math.max(...rows.map((row) => row.length), 0) }, (_, index) => `Sütun ${index + 1}`);
  const title = firstText(block.title, data.title);
  const csv = useMemo(() => {
    const escape = (value: string) => `"${String(value).replace(/"/g, '""')}"`;
    return [safeColumns, ...rows].map((row) => row.map(escape).join(',')).join('\n');
  }, [rows, safeColumns]);
  const [copied, setCopied] = useState(false);
  if (safeColumns.length === 0 || rows.length === 0) return null;
  return (
    <section className="message-block message-block--table" aria-label={title || 'Tablo'}>
      <div className="message-block__table-header">
        {title ? <strong className="message-block__title">{title}</strong> : <span />}
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
          <thead><tr>{safeColumns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead>
          <tbody>{rows.slice(0, 300).map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>{safeColumns.map((column, cellIndex) => {
              const cell = row[cellIndex] ?? '';
              const rule = highlightRules.find((candidate) => candidate.column === column.toLowerCase() && candidate.match === cell.toLowerCase());
              const tone = ['success', 'warning', 'danger', 'info', 'neutral'].includes(rule?.tone ?? '') ? rule?.tone : '';
              return (
                <td key={`cell-${rowIndex}-${cellIndex}`}>
                  {tone ? <span className={`message-block__tone message-block__tone--${tone}`}>{cell}</span> : cell}
                </td>
              );
            })}</tr>
          ))}</tbody>
        </table>
      </div>
      {rows.length > 300 ? <p className="message-block__summary">İlk 300 satır gösteriliyor.</p> : null}
    </section>
  );
}

function ChartBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const title = firstText(block.title, data.title);
  const type = firstText(block.chartType, block.chart_type, data.chartType, data.type).toLowerCase() || 'bar';
  const rawPoints = asArray(block.points).length > 0 ? asArray(block.points) : asArray(block.data ?? data.points ?? data.data);
  const points = rawPoints
    .map((point, index) => {
      const record = asRecord(point);
      const value = numberFrom(record.value ?? record.y ?? record.count ?? record.total);
      if (value === null) return null;
      return {
        label: firstText(record.label, record.x, record.name, record.key) || `${index + 1}`,
        value,
        color: firstText(record.color, record.fill) || ['#6f8f72', '#b28b57', '#7f8ea3', '#5f8f97'][index % 4]!,
      };
    })
    .filter((point): point is { label: string; value: number; color: string } => point !== null);
  const maxValue = Math.max(...points.map((point) => Math.abs(point.value)), 1);
  if (points.length === 0) return <UnknownBlock block={block} label="Grafik verisi alınamadı." />;
  return (
    <section className="message-block message-block--chart" aria-label={title || 'Grafik'}>
      {title ? <strong className="message-block__title">{title}</strong> : null}
      {type === 'pie' ? (
        <div className="message-block__chart-legend">
          {points.map((point) => <span key={point.label}><i style={{ background: point.color }} aria-hidden="true" />{point.label}<strong>{point.value}</strong></span>)}
        </div>
      ) : (
        <div className="message-block__chart-bars">
          {points.map((point) => (
            <div className="message-block__bar" key={point.label}>
              <div className="message-block__bar-track"><span style={{ height: `${Math.max(6, Math.min(100, (Math.abs(point.value) / maxValue) * 100))}%`, background: point.color }} /></div>
              <small title={point.label}>{point.label}</small>
              <strong>{point.value}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function FileBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const name = firstText(block.name, block.filename, block.fileName, data.name, data.filename, data.fileName) || 'Dosya';
  const mime = firstText(block.mime, block.mimeType, block.mime_type, data.mime, data.mimeType, data.mime_type);
  const uri = firstText(block.previewUrl, block.url, block.uri, block.path, data.previewUrl, data.url, data.uri, data.path);
  const href = safeHref(uri);
  const size = formatSize(numberFrom(block.sizeBytes ?? block.size ?? data.sizeBytes ?? data.size));
  const summary = firstText(block.summary, block.preview, data.summary, data.preview);
  const content = (
    <>
      <span className="message-block__file-icon">{mime.includes('pdf') ? 'PDF' : mime.startsWith('image/') ? 'IMG' : 'FILE'}</span>
      <span className="message-block__file-copy">
        <strong>{name}</strong>
        <small>{[mime || 'dosya', size].filter(Boolean).join(' · ')}</small>
        {summary ? <em>{summary}</em> : null}
        {uri && !href ? <em>{maskPath(uri)}</em> : null}
      </span>
    </>
  );
  return (
    <section className="message-block message-block--file" aria-label={name}>
      {href ? <a className="message-block__file-link" href={href} target="_blank" rel="noreferrer">{content}</a> : <div className="message-block__file-link">{content}</div>}
    </section>
  );
}

function TaskTraceBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const title = firstText(block.title, data.title) || 'Görev durumu';
  const status = firstText(block.status, block.state, data.status, data.state).toLowerCase();
  const summary = firstText(block.summary, block.description, data.summary, data.description);
  const rawSteps = asArray(block.steps).length > 0 ? asArray(block.steps) : asArray(block.items ?? data.steps ?? data.items);
  const steps = rawSteps.map(asRecord).map((step, index) => ({
    id: firstText(step.id, step.key) || `step-${index}`,
    label: firstText(step.label, step.title, step.phase, step.capability) || `Adım ${index + 1}`,
    detail: firstText(step.detail, step.description, step.summary),
    status: firstText(step.status, step.state),
  })).slice(0, 12);
  const isRunning = ['running', 'started', 'in_progress'].includes(status);
  const isCompleted = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(status);
  return (
    <section className={`message-block message-block--task-trace${isRunning ? ' message-block--running' : ''}`} aria-label={title}>
      <div className="message-block__header">
        <span className="message-block__task-icon" aria-hidden="true" />
        <strong>{title}</strong>
        {status && !isCompleted ? <StepStatusPill status={status} /> : null}
        {isCompleted ? <StepStatusPill status="completed" /> : null}
      </div>
      {summary ? <p className="message-block__summary">{summary}</p> : null}
      {steps.length > 0 ? (
        <ol className="message-block__steps">
          {steps.map((step) => {
            const ss = step.status.toLowerCase();
            const isDone = ['completed', 'complete', 'succeeded', 'success', 'done'].includes(ss);
            const isStepFailed = ['failed', 'error', 'cancelled', 'canceled'].includes(ss);
            const isActive = ['running', 'started', 'in_progress'].includes(ss);
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
                <span className="step__label">{step.label}</span>
                {isActive ? <StepStatusPill status="running" /> : null}
                {isStepFailed ? <StepStatusPill status="failed" /> : null}
                {step.detail ? <small className="step__detail">{step.detail}</small> : null}
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

function ApprovalBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const title = firstText(block.title, data.title) || 'Onay gerekiyor';
  const summary = firstText(block.actionSummary, block.summary, data.actionSummary, data.summary) || 'Bu işlem devam etmeden önce açık izin bekliyor.';
  const risk = firstText(block.riskLevel, data.riskLevel);
  return (
    <section className="message-block message-block--actionable" aria-label={title}>
      <strong className="message-block__title">{title}</strong>
      <p>{summary}</p>
      {risk ? <StepStatusPill status={risk === 'high' ? 'waiting_approval' : 'queued'} /> : null}
    </section>
  );
}

function TerminalBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const rawLines = asArray(block.lines).map(scalarText).filter(Boolean);
  const output = rawLines.length > 0 ? rawLines.join('\n') : firstText(block.output, block.content, data.output, data.content);
  const redacted = redactSecrets(output);
  const lines = redacted.split('\n');
  const maxVisible = Math.max(20, Math.min(240, Number(block.maxVisibleLines ?? data.maxVisibleLines ?? 120) || 120));
  const [expanded, setExpanded] = useState(false);
  const visibleLines = expanded ? lines : lines.slice(Math.max(0, lines.length - maxVisible));
  if (!redacted.trim()) return null;
  return (
    <section className="message-block message-block--code message-block--terminal" aria-label={firstText(block.title, data.title) || 'Terminal'}>
      <div className="message-block__code-header">
        <span>{firstText(block.title, data.title) || 'Terminal'}</span>
        {lines.length > maxVisible ? (
          <button type="button" className="message-block__copy" onClick={() => setExpanded((value) => !value)}>
            {expanded ? 'Kısalt' : `Son ${maxVisible} satır`}
          </button>
        ) : null}
      </div>
      <pre className="message-block__code"><code>{visibleLines.join('\n')}</code></pre>
    </section>
  );
}

function BrowserBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const title = firstText(block.title, data.title) || 'Tarayıcı işlemi';
  const summary = firstText(block.summary, data.summary, block.description, data.description);
  const url = firstText(block.currentUrl, data.currentUrl, block.url, data.url);
  const screenshotUrl = safeHref(firstText(block.screenshotUrl, data.screenshotUrl));
  return (
    <section className="message-block message-block--context" aria-label={title}>
      <strong className="message-block__title">{title}</strong>
      {summary ? <p>{summary}</p> : null}
      {url ? <p><strong>URL</strong>: {url.replace(/[?#].*$/, '')}</p> : null}
      {screenshotUrl ? <img className="message-block__artifact-image" src={screenshotUrl} alt="" /> : null}
    </section>
  );
}

function DesktopActionBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const fallback = asRecord(block.mobileFallback);
  const title = firstText(block.title, data.title, fallback.title) || 'Desktop işlemi';
  const summary = firstText(block.summary, data.summary, fallback.markdown, fallback.summary) || 'Bağlı masaüstü cihazında bir işlem yürütülüyor.';
  const app = firstText(block.app, data.app);
  const status = firstText(block.status, data.status);
  return (
    <section className="message-block message-block--task-trace" aria-label={title}>
      <div className="message-block__header">
        <span className="message-block__task-icon" aria-hidden="true">●</span>
        <strong>{title}</strong>
        {status ? <StepStatusPill status={status} /> : null}
      </div>
      <p className="message-block__summary">{summary}</p>
      {app ? <p className="message-block__summary">Uygulama: {app}</p> : null}
    </section>
  );
}

function ArtifactBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const title = firstText(block.title, data.title) || firstText(block.artifactId, data.artifactId) || 'Artifact';
  const mime = firstText(block.mime, block.mimeType, data.mime, data.mimeType);
  const url = safeHref(firstText(block.url, block.uri, data.url, data.uri));
  const summary = firstText(block.summary, data.summary);
  if (mime.startsWith('image/') && url) {
    return (
      <section className="message-block message-block--artifact message-block--artifact-image" aria-label={title}>
        <strong className="message-block__title">{title}</strong>
        <img className="message-block__artifact-image" src={url} alt={title} />
      </section>
    );
  }
  return <FileBlock block={{ ...block, type: 'file', name: title, mimeType: mime, preview: summary, uri: url }} />;
}

function ErrorBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const title = firstText(block.title, data.title) || 'İşlem tamamlanamadı';
  const message = firstText(block.message, block.summary, data.message, data.summary) || 'Güvenli şekilde tamamlanamayan bir işlem oldu.';
  return (
    <section className="message-block message-block--text message-block--tone-danger" aria-label={title}>
      <strong className="message-block__title">{title}</strong>
      <p>{message}</p>
      {firstText(block.retryActionId, data.retryActionId) ? <small>Tekrar denenebilir.</small> : null}
    </section>
  );
}

function MemoryEchoBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const question = firstText(block.question, block.markdown, data.question, data.markdown) || '';
  const recall = firstText(block.recall, data.recall, block.memory, data.memory) || '';
  const display = question || recall;
  if (!display) return null;
  return (
    <section className="message-block message-block--memory-echo" aria-label="Elyan hatırladı">
      <p className="message-block__memory-echo-text">{display}</p>
    </section>
  );
}

function ProactiveTouchBlock({ block }: { block: ElyanBlock }) {
  const data = blockData(block);
  const suggestion = firstText(block.suggestion, block.markdown, data.suggestion, data.markdown) || '';
  const cta = firstText(block.cta, block.action, data.cta, data.action) || '';
  if (!suggestion) return null;
  return (
    <section className="message-block message-block--proactive" aria-label="Elyan önerisi">
      <p className="message-block__proactive-text">{suggestion}</p>
      {cta ? <span className="message-block__proactive-cta">{cta}</span> : null}
    </section>
  );
}

function UnknownBlock({ block, label = 'Bu blok bu desktop sürümünde desteklenmiyor.' }: { block: ElyanBlock; label?: string }) {
  const fallback = asRecord(block.mobileFallback);
  const fallbackText = firstText(fallback.markdown, fallback.summary, fallback.title);
  const title = firstText(block.title, fallback.title) || `Block: ${String(block.type || 'unknown')}`;
  const summary = firstText(block.summary, blockBody(block), fallbackText) || label;
  return (
    <section className="message-block message-block--context" aria-label={title}>
      <strong className="message-block__title">{title}</strong>
      <p>{summary}</p>
    </section>
  );
}

export const BlockRenderer = memo(function BlockRenderer({
  block,
}: BlockRendererProps) {
  switch (block.type) {
    case 'text':
      return <TextBlock block={block} />;
    case 'code':
      return <CodeBlock block={block} />;
    case 'table':
      return <TableBlock block={block} />;
    case 'chart':
      return <ChartBlock block={block} />;
    case 'file':
      return <FileBlock block={block} />;
    case 'task_trace':
      return <TaskTraceBlock block={block} />;
    case 'approval':
      return <ApprovalBlock block={block} />;
    case 'artifact':
      return <ArtifactBlock block={block} />;
    case 'terminal':
      return <TerminalBlock block={block} />;
    case 'browser':
      return <BrowserBlock block={block} />;
    case 'desktop_action':
      return <DesktopActionBlock block={block} />;
    case 'error':
      return <ErrorBlock block={block} />;
    case 'memory_echo':
    case 'memory_surface':
    case 'memory_recall':
      return <MemoryEchoBlock block={block} />;
    case 'proactive_touch':
    case 'proactive':
    case 'proactive_surface':
      return <ProactiveTouchBlock block={block} />;
    default:
      return <UnknownBlock block={block} />;
  }
});

export const BlockListRenderer = memo(function BlockListRenderer({
  blocks,
}: {
  blocks: ElyanBlock[];
  shouldType?: boolean;
  onFinished?: () => void;
}) {
  return (
    <div className="message-blocks">
      {blocks.map((block, index) => {
        const key = firstText(block.stableBlockId, block.cacheDigest, block.id) || `${block.type}-${index}`;
        return <BlockRenderer key={key} block={block} />;
      })}
    </div>
  );
});
