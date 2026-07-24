import DOMPurify from 'dompurify';
import { marked } from 'marked';
import katex from 'katex';
import { createTable, getCoreRowModel, getSortedRowModel, type ColumnDef, type SortingState } from '@tanstack/table-core';
import { ASSISTANT_BLOCK_SCHEMA_DIGEST, schemaDigestMatches, validateAssistantBlock, type AssistantBlock } from './block-contract';
import { exportDocumentDocx, exportDocumentMarkdown, exportDocumentPdf, exportTableCsv, exportTablePdf, exportTableXlsx, type DocumentExportData, type TableExportData } from './block-exporters';

type RenderContext = { taskId?: string | null };
type Renderer = (block: AssistantBlock, context: RenderContext) => HTMLElement;

const internalTypes = new Set(['reasoning_trace', 'security_decision']);
const registry = new Map<string, Renderer>();
const connectorWidgetTypes = new Set(['connector_result', 'mail_list', 'mail_detail', 'calendar_agenda', 'drive_files', 'notion_page', 'github_activity', 'slack_messages', 'tool_call']);
const widgetSurface = 'rounded-[24px] bg-[var(--color-elyan-surface)] px-4 py-3 shadow-none ring-1 ring-[var(--color-elyan-outline)]/45';

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function element(tag: string, className = '', content?: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  if (content != null) node.textContent = content;
  return node;
}
function appendIfText(parent: HTMLElement, tag: string, className: string, content: string): HTMLElement | null {
  if (!content) return null;
  const node = element(tag, className, content);
  parent.append(node);
  return node;
}
const envelopeKeys = new Set(['type', 'version', 'blockId', 'stableBlockId', 'source', 'visibility', 'renderHints', 'isRenderable', 'priority', 'confidence', 'cacheDigest']);
function data(block: AssistantBlock): Record<string, unknown> {
  const raw = record(block);
  const topLevel = Object.fromEntries(Object.entries(raw).filter(([key]) => !envelopeKeys.has(key) && key !== 'data'));
  const payload = record(topLevel.payload);
  return { ...topLevel, ...payload, ...record(raw.data) };
}
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function number(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function firstText(value: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const candidate = text(value[key]);
    if (candidate) return candidate;
  }
  return '';
}
function safeUrl(value: unknown): string {
  const raw = text(value);
  if (!raw) return '';
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.href : '';
  } catch { return ''; }
}
function extractItems(value: Record<string, unknown>, preferred: string[] = []): unknown[] {
  for (const key of [...preferred, 'items', 'results', 'messages', 'events', 'files', 'activities', 'calls', 'entries', 'rows']) {
    const candidate = array(value[key]);
    if (candidate.length) return candidate;
  }
  return [];
}
function asColumnLabel(raw: unknown, index: number): { key: string; label: string } {
  if (typeof raw === 'string') return { key: raw, label: raw };
  const item = record(raw);
  const key = firstText(item, ['key', 'id', 'accessorKey', 'field', 'name']) || `c${index + 1}`;
  const label = firstText(item, ['label', 'header', 'title', 'name']) || key;
  return { key, label };
}
function normalizeTableData(value: Record<string, unknown>): TableExportData & { objects: Record<string, string>[] } {
  const rawRows = array(value.rows ?? value.data ?? value.items);
  const explicitColumns = array(value.columns ?? value.headers).map(asColumnLabel);
  const objectRows = rawRows.map(record).filter((row) => Object.keys(row).length);
  const derivedColumns = objectRows.length
    ? [...new Set(objectRows.flatMap((row) => Object.keys(row).filter((key) => !sensitiveKey(key))))].slice(0, 16).map((key) => ({ key, label: key }))
    : [];
  const columns = explicitColumns.length ? explicitColumns : derivedColumns;
  const labels = columns.map((column) => column.label);
  const keys = columns.map((column) => column.key);
  const rows = rawRows.map((entry) => {
    if (Array.isArray(entry)) return entry.slice(0, labels.length || entry.length).map((cell) => previewValue(cell));
    const row = record(entry);
    return keys.map((key) => previewValue(row[key]));
  }).filter((row) => row.some(Boolean));
  const resolvedColumns = labels.length ? labels : rows[0]?.map((_, index) => `Column ${index + 1}`) ?? [];
  const objects = rows.map((row) => Object.fromEntries(resolvedColumns.map((label, index) => [label, row[index] ?? ''])));
  return { title: firstText(value, ['title', 'name']) || 'Elyan table', columns: resolvedColumns, rows, objects };
}
function documentExportData(value: Record<string, unknown>): DocumentExportData {
  const sections: DocumentExportData['sections'] = array(value.sections).map(record).map((section) => ({
    heading: text(section.heading),
    content: firstText(section, ['content', 'markdown', 'text', 'summary']),
    level: Number(section.level) || 2,
  })).filter((section) => section.content || section.heading);
  if (!sections.length) sections.push({ content: firstText(value, ['markdown', 'content', 'text', 'summary']) || text(value.title) || '' });
  return { title: text(value.title) || 'Elyan document', summary: text(value.summary), sections };
}
function nextFrame(callback: () => void): void {
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(callback);
  else setTimeout(callback, 0);
}
function isJsdom(): boolean {
  return typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
}
function canvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D | null {
  if (isJsdom()) return null;
  try { return canvas.getContext('2d'); } catch { return null; }
}
function formatBytes(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return '';
  if (number < 1024) return `${number} B`;
  if (number < 1024 * 1024) return `${(number / 1024).toFixed(1)} KB`;
  return `${(number / (1024 * 1024)).toFixed(1)} MB`;
}
function badge(label: string, tone: 'neutral' | 'ok' | 'warn' | 'error' = 'neutral'): HTMLElement {
  const classes = {
    neutral: 'bg-zinc-100 text-zinc-600',
    ok: 'bg-emerald-50 text-emerald-700',
    warn: 'bg-amber-50 text-amber-700',
    error: 'bg-red-50 text-red-700',
  };
  return element('span', `rounded-full px-2 py-1 text-[11px] font-medium ${classes[tone]}`, label);
}
function miniButton(label: string, title = label): HTMLButtonElement {
  const button = element('button', 'rounded-full px-2.5 py-1 text-[11px] font-semibold text-zinc-500 transition hover:bg-black/5 hover:text-zinc-950 disabled:opacity-40', label) as HTMLButtonElement;
  button.type = 'button';
  button.title = title;
  return button;
}
function setBusy(button: HTMLButtonElement, busy: boolean): void {
  button.disabled = busy;
  button.style.cursor = busy ? 'wait' : '';
}
function sensitiveKey(key: string): boolean {
  return /secret|token|password|credential|authorization|cookie|private|reasoning|internal|security|nonce|csrf/i.test(key);
}
function previewValue(value: unknown): string {
  if (typeof value === 'string') return value.slice(0, 600);
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value == null) return '';
  return '';
}
function suppressLowSourceConfidence(block: AssistantBlock): boolean {
  const value = data(block);
  const haystack = [
    block.type,
    firstText(value, ['title', 'status', 'name']),
    firstText(value, ['summary', 'detail', 'message', 'content', 'markdown']),
  ].join(' ');
  return /kaynak\s+güveni\s+düşük|low\s+source\s+confidence|source\s+confidence\s+low|bulunan\s+kaynaklar\s+sınırlı|sources?\s+(were\s+)?limited/i.test(haystack);
}

function safeHtml(markdown: string): string {
  const rendered = marked.parse(markdown, { async: false, gfm: true, breaks: true }) as string;
  return DOMPurify.sanitize(rendered, {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 's', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'a', 'h1', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr'],
    ALLOWED_ATTR: ['href', 'title', 'target', 'rel'],
    ALLOW_UNKNOWN_PROTOCOLS: false,
  });
}

function markdownRenderer(block: AssistantBlock): HTMLElement {
  const wrapper = element('div', 'elyan-markdown space-y-4');
  wrapper.innerHTML = safeHtml(text(data(block).markdown) || text(data(block).content) || text(data(block).summary));
  wrapper.querySelectorAll('a').forEach((link) => {
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
  });
  return wrapper;
}

function codeRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', 'elyan-code-block overflow-hidden rounded-xl border border-zinc-200 bg-zinc-950 text-zinc-100');
  const title = text(value.filename) || text(value.title) || text(value.language) || 'Code';
  wrapper.append(element('div', 'border-b border-white/10 px-4 py-2 text-xs text-zinc-400', title));
  const pre = element('pre', 'overflow-x-auto p-4 text-[13px] leading-relaxed');
  pre.append(element('code', '', text(value.code)));
  wrapper.append(pre);
  return wrapper;
}

function tableRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const model = normalizeTableData(value);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  const header = element('div', 'flex items-center justify-between gap-3');
  appendIfText(header, 'h3', 'text-sm font-semibold text-zinc-950', model.title || 'Elyan table');
  const actions = element('div', 'flex shrink-0 items-center gap-1');
  const csv = miniButton('CSV');
  csv.addEventListener('click', () => exportTableCsv(model));
  const xlsx = miniButton('XLSX');
  xlsx.addEventListener('click', async () => { setBusy(xlsx, true); try { await exportTableXlsx(model); } finally { setBusy(xlsx, false); } });
  const pdf = miniButton('PDF');
  pdf.addEventListener('click', async () => { setBusy(pdf, true); try { await exportTablePdf(model); } finally { setBusy(pdf, false); } });
  actions.append(csv, xlsx, pdf);
  header.append(actions);
  wrapper.append(header);
  const tableShell = element('div', 'overflow-x-auto rounded-[20px] bg-white/70 ring-1 ring-black/5');
  const table = element('table', 'w-full min-w-[520px] border-separate border-spacing-0 text-left text-sm');
  const head = element('thead', 'text-xs text-zinc-500');
  const headRow = element('tr');
  const body = element('tbody');
  let sorting: SortingState = [];
  const columns: ColumnDef<Record<string, string>>[] = model.columns.map((column) => ({ accessorKey: column, header: column }));
  const renderBody = () => {
    body.replaceChildren();
    const tableModel = createTable({
      data: model.objects,
      columns,
      state: { sorting },
      onStateChange: () => undefined,
      onSortingChange: (updater) => { sorting = typeof updater === 'function' ? updater(sorting) : updater; renderBody(); },
      getCoreRowModel: getCoreRowModel(),
      getSortedRowModel: getSortedRowModel(),
      renderFallbackValue: '',
    });
    tableModel.getRowModel().rows.slice(0, 240).forEach((entry) => {
      const row = element('tr', 'border-b border-black/5 last:border-0');
      entry.getVisibleCells().forEach((cell) => row.append(element('td', 'border-t border-black/5 px-4 py-3 align-top text-zinc-700', previewValue(cell.getValue()))));
      body.append(row);
    });
  };
  model.columns.forEach((column) => {
    const th = element('th', 'border-b border-black/5 px-4 py-3 font-semibold');
    const button = element('button', 'inline-flex items-center gap-1 text-left transition hover:text-zinc-950', column) as HTMLButtonElement;
    button.type = 'button';
    button.addEventListener('click', () => {
      const current = sorting[0];
      sorting = current?.id === column ? (current.desc ? [] : [{ id: column, desc: true }]) : [{ id: column, desc: false }];
      renderBody();
    });
    th.append(button); headRow.append(th);
  });
  head.append(headRow);
  table.append(head, body);
  tableShell.append(table);
  wrapper.append(tableShell);
  renderBody();
  appendIfText(wrapper, 'p', 'text-xs text-zinc-500', text(value.caption));
  return wrapper;
}

type PlotPoint = { x: number; y: number };
type MathNode = { eval: (vars: Record<string, number>) => number };

class MathExpressionParser {
  private index = 0;
  constructor(private readonly source: string) {}
  parse(): MathNode {
    const node = this.parseExpression();
    this.skip();
    if (this.index < this.source.length) throw new Error('unexpected_token');
    return node;
  }
  private parseExpression(): MathNode {
    let node = this.parseTerm();
    for (;;) {
      this.skip();
      const op = this.peek();
      if (op !== '+' && op !== '-') return node;
      this.index += 1;
      const right = this.parseTerm();
      const left = node;
      node = { eval: (vars) => op === '+' ? left.eval(vars) + right.eval(vars) : left.eval(vars) - right.eval(vars) };
    }
  }
  private parseTerm(): MathNode {
    let node = this.parsePower();
    for (;;) {
      this.skip();
      const op = this.peek();
      if (op !== '*' && op !== '/') {
        if (this.canImplicitMultiply()) {
          const right = this.parsePower();
          const left = node;
          node = { eval: (vars) => left.eval(vars) * right.eval(vars) };
          continue;
        }
        return node;
      }
      this.index += 1;
      const right = this.parsePower();
      const left = node;
      node = { eval: (vars) => op === '*' ? left.eval(vars) * right.eval(vars) : left.eval(vars) / right.eval(vars) };
    }
  }
  private parsePower(): MathNode {
    let node = this.parseUnary();
    this.skip();
    if (this.peek() === '^') {
      this.index += 1;
      const right = this.parsePower();
      const left = node;
      node = { eval: (vars) => Math.pow(left.eval(vars), right.eval(vars)) };
    }
    return node;
  }
  private parseUnary(): MathNode {
    this.skip();
    const op = this.peek();
    if (op === '+' || op === '-') {
      this.index += 1;
      const child = this.parseUnary();
      return { eval: (vars) => op === '-' ? -child.eval(vars) : child.eval(vars) };
    }
    return this.parsePrimary();
  }
  private parsePrimary(): MathNode {
    this.skip();
    const char = this.peek();
    if (char === '(') {
      this.index += 1;
      const node = this.parseExpression();
      this.skip();
      if (this.peek() !== ')') throw new Error('missing_paren');
      this.index += 1;
      return node;
    }
    if (/[0-9.]/.test(char)) return this.parseNumber();
    if (/[a-zA-Zπ]/.test(char)) return this.parseIdentifier();
    throw new Error('unexpected_primary');
  }
  private parseNumber(): MathNode {
    const start = this.index;
    while (/[0-9._]/.test(this.peek())) this.index += 1;
    if (/[eE]/.test(this.peek())) {
      this.index += 1;
      if (/[+-]/.test(this.peek())) this.index += 1;
      while (/[0-9]/.test(this.peek())) this.index += 1;
    }
    const value = Number(this.source.slice(start, this.index).replace(/_/g, ''));
    if (!Number.isFinite(value)) throw new Error('invalid_number');
    return { eval: () => value };
  }
  private parseIdentifier(): MathNode {
    const start = this.index;
    while (/[a-zA-Z0-9_π]/.test(this.peek())) this.index += 1;
    const name = this.source.slice(start, this.index).toLowerCase();
    if (name === 'pi' || name === 'π') return { eval: () => Math.PI };
    if (name === 'e') return { eval: () => Math.E };
    if (name === 'x' || name === 'y') return { eval: (vars) => vars[name] ?? 0 };
    this.skip();
    if (this.peek() !== '(') throw new Error('unknown_identifier');
    this.index += 1;
    const arg = this.parseExpression();
    this.skip();
    if (this.peek() !== ')') throw new Error('missing_function_paren');
    this.index += 1;
    const fn = {
      sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan,
      sqrt: Math.sqrt, abs: Math.abs, log: Math.log, ln: Math.log, exp: Math.exp, floor: Math.floor, ceil: Math.ceil, round: Math.round,
    }[name];
    if (!fn) throw new Error('unsupported_function');
    return { eval: (vars) => fn(arg.eval(vars)) };
  }
  private canImplicitMultiply(): boolean {
    this.skip();
    return this.peek() === '(' || /[a-zA-Zπ0-9.]/.test(this.peek());
  }
  private skip(): void {
    while (/\s/.test(this.peek())) this.index += 1;
  }
  private peek(): string {
    return this.source[this.index] || '';
  }
}

function parseExpression(expression: string): MathNode | null {
  const normalized = expression
    .replace(/−/g, '-')
    .replace(/×/g, '*')
    .replace(/÷/g, '/')
    .replace(/\*\*/g, '^')
    .replace(/^z\s*=\s*/i, '')
    .replace(/^f\s*\(\s*x\s*\)\s*=\s*/i, '');
  if (!/^[0-9a-zA-Zπ_\s+\-*/^().,]+$/.test(normalized)) return null;
  try { return new MathExpressionParser(normalized).parse(); } catch { return null; }
}

function rangePair(raw: unknown, fallback: [number, number]): [number, number] {
  const value = record(raw);
  const min = number(value.min ?? value.xMin ?? value.from ?? value.start);
  const max = number(value.max ?? value.xMax ?? value.to ?? value.end);
  if (min != null && max != null && max > min) return [min, max];
  if (Array.isArray(raw) && number(raw[0]) != null && number(raw[1]) != null && Number(raw[1]) > Number(raw[0])) return [Number(raw[0]), Number(raw[1])];
  return fallback;
}

function chartSeries(value: Record<string, unknown>): { labels: string[]; values: number[]; points: PlotPoint[] } {
  const labels = array(value.labels ?? value.x ?? value.xValues ?? value.categories).map((entry, index) => text(entry) || String(index + 1));
  const values = array(value.values ?? value.y ?? value.yValues).map(number).filter((entry): entry is number => entry != null);
  const points: PlotPoint[] = [];
  for (const raw of array(value.points)) {
    if (Array.isArray(raw) && number(raw[0]) != null && number(raw[1]) != null) points.push({ x: Number(raw[0]), y: Number(raw[1]) });
    const item = record(raw);
    const x = number(item.x ?? item[0]);
    const y = number(item.y ?? item.value ?? item[1]);
    if (x != null && y != null) points.push({ x, y });
  }
  if (!points.length && values.length) values.forEach((y, index) => points.push({ x: index + 1, y }));
  return { labels: labels.length ? labels : points.map((point) => String(point.x)), values: values.length ? values : points.map((point) => point.y), points };
}

function sampleFunction(expression: string, rawRange: unknown, samples = 160): PlotPoint[] {
  const root = parseExpression(expression);
  if (!root) return [];
  const [min, max] = rangePair(rawRange, [-5, 5]);
  const points: PlotPoint[] = [];
  const step = (max - min) / Math.max(1, samples - 1);
  for (let index = 0; index < samples; index += 1) {
    const x = min + step * index;
    const y = root.eval({ x });
    if (Number.isFinite(y)) points.push({ x, y });
  }
  return points;
}

function drawFallbackLine(canvas: HTMLCanvasElement, points: PlotPoint[]): void {
  const ctx = canvasContext(canvas);
  if (!ctx || !points.length) return;
  const width = canvas.width || 720;
  const height = canvas.height || 260;
  ctx.clearRect(0, 0, width, height);
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const xMin = Math.min(...xs); const xMax = Math.max(...xs);
  const yMin = Math.min(...ys); const yMax = Math.max(...ys);
  const pad = 28;
  const px = (x: number) => pad + ((x - xMin) / Math.max(1e-9, xMax - xMin)) * (width - pad * 2);
  const py = (y: number) => height - pad - ((y - yMin) / Math.max(1e-9, yMax - yMin)) * (height - pad * 2);
  ctx.strokeStyle = 'rgba(17, 24, 39, 0.10)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = pad + i * ((height - pad * 2) / 4);
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(width - pad, y); ctx.stroke();
  }
  ctx.strokeStyle = 'rgb(111, 143, 112)';
  ctx.lineWidth = 2.4;
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(px(point.x), py(point.y));
    else ctx.lineTo(px(point.x), py(point.y));
  });
  ctx.stroke();
}

function drawSurfacePreview(canvas: HTMLCanvasElement, value: Record<string, unknown>): void {
  const ctx = canvasContext(canvas);
  if (!ctx) return;
  const width = canvas.width || 760;
  const height = canvas.height || 280;
  const expression = text(value.expression) || 'sin(x)+cos(y)';
  const root = parseExpression(expression);
  if (!root) return;
  const range = record(value.range);
  const [xMin, xMax] = rangePair(range.x ?? range.xRange ?? value.xRange, [-4, 4]);
  const [yMin, yMax] = rangePair(range.y ?? range.yRange ?? value.yRange, [-4, 4]);
  const resolution = Math.min(80, Math.max(18, Math.floor(number(value.resolution) ?? 46)));
  const grid: number[][] = [];
  let zMin = Infinity; let zMax = -Infinity;
  for (let row = 0; row < resolution; row += 1) {
    const y = yMin + ((yMax - yMin) * row) / Math.max(1, resolution - 1);
    const line: number[] = [];
    for (let col = 0; col < resolution; col += 1) {
      const x = xMin + ((xMax - xMin) * col) / Math.max(1, resolution - 1);
      const z = root.eval({ x, y });
      const safe = Number.isFinite(z) ? z : 0;
      zMin = Math.min(zMin, safe); zMax = Math.max(zMax, safe);
      line.push(safe);
    }
    grid.push(line);
  }
  ctx.clearRect(0, 0, width, height);
  const cell = Math.max(2, Math.ceil(width / resolution));
  for (let row = 0; row < resolution; row += 1) {
    for (let col = 0; col < resolution; col += 1) {
      const t = (grid[row][col] - zMin) / Math.max(1e-9, zMax - zMin);
      const shade = Math.round(238 - t * 74);
      ctx.fillStyle = `rgb(${shade - 10}, ${shade}, ${Math.round(shade - 18)})`;
      const sx = ((col - row) * cell * 0.72) + width / 2;
      const sy = ((col + row) * cell * 0.24) + 12 - t * 62;
      ctx.fillRect(sx, sy, cell * 1.25, Math.max(1.4, cell * 0.86));
    }
  }
}

function chartRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const rawType = text(value.chartType) || text(value.kind) || 'line';
  const chartType = ({ line_chart: 'line', bar_chart: 'bar', pie_chart: 'pie', function_plot: 'function', mesh3d: 'surface3d' } as Record<string, string>)[rawType] || rawType;
  const parsed = chartSeries(value);
  const functionPoints = (chartType === 'function' || (text(value.expression) && !parsed.points.length)) ? sampleFunction(text(value.expression), value.range ?? value.xRange) : [];
  const points = functionPoints.length ? functionPoints : parsed.points;
  const labels = parsed.labels.length ? parsed.labels : points.map((point) => Number.isInteger(point.x) ? String(point.x) : point.x.toFixed(2));
  const values = parsed.values.length ? parsed.values : points.map((point) => point.y);
  const max = Math.max(1, ...values.map((number) => Math.abs(number)));
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold text-zinc-950', text(value.title));
  const canvas = document.createElement('canvas');
  canvas.className = 'block h-[260px] max-h-[320px] w-full rounded-[20px] bg-white/70';
  canvas.width = 760;
  canvas.height = 260;
  if (chartType === 'surface3d' || chartType === 'mesh' || chartType === 'heatmap') {
    wrapper.append(canvas);
    nextFrame(() => drawSurfacePreview(canvas, value));
  } else if (values.length && labels.length) {
    wrapper.append(canvas);
    drawFallbackLine(canvas, points.length ? points : values.map((y, index) => ({ x: index + 1, y })));
    if (!isJsdom()) import('chart.js/auto').then(({ default: Chart }) => {
      const type = chartType === 'bar' || chartType === 'pie' || chartType === 'scatter' ? chartType : 'line';
      const dataSet = type === 'scatter' ? points : values;
      new Chart(canvas, {
        type,
        data: { labels, datasets: [{ label: text(value.title) || text(value.expression) || 'Values', data: dataSet, borderColor: 'rgb(111,143,112)', backgroundColor: type === 'pie' ? ['#6f8f70', '#aeb9a9', '#d8d2c5', '#f0ebe2'] : 'rgba(111,143,112,0.22)', tension: 0.32, pointRadius: type === 'scatter' ? 3 : 0, fill: chartType === 'area' }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === 'pie' } }, scales: type === 'pie' ? {} : { x: { grid: { display: false } }, y: { grid: { color: 'rgba(35,35,32,0.07)' } } } },
      });
    }).catch(() => {});
  }
  if (chartType === 'bar' && values.length) {
    const bars = element('div', 'space-y-2');
    values.slice(0, 24).forEach((entry, index) => {
      const row = element('div', 'grid grid-cols-[minmax(72px,1fr)_3fr_64px] items-center gap-3 text-xs');
      row.append(element('span', 'truncate text-zinc-600', labels[index] || String(index + 1)));
      const track = element('div', 'h-1.5 overflow-hidden rounded-full bg-zinc-100');
      const bar = element('div', 'h-full rounded-full bg-[var(--color-elyan-primary)]');
      bar.style.width = `${Math.max(2, Math.abs(entry) / max * 100)}%`;
      track.append(bar); row.append(track); row.append(element('span', 'text-right tabular-nums text-zinc-600', String(entry)));
      bars.append(row);
    });
    wrapper.append(bars);
  }
  appendIfText(wrapper, 'p', 'text-xs text-zinc-500', text(value.caption) || text(value.expression));
  return wrapper;
}

function mathRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} overflow-x-auto space-y-2`);
  appendIfText(wrapper, 'h3', 'mb-2 text-sm font-semibold text-zinc-950', text(value.title));
  const latex = text(value.latex) || text(value.content) || text(value.result);
  const formula = element('div', 'min-w-0');
  try {
    formula.innerHTML = katex.renderToString(latex, { displayMode: value.displayMode !== false, throwOnError: false, trust: false, strict: 'warn' });
  } catch { formula.textContent = latex; }
  wrapper.append(formula);
  if (text(value.result) && text(value.result) !== latex) wrapper.append(element('p', 'mt-3 text-sm text-zinc-700', text(value.result)));
  if (text(value.explanation)) wrapper.append(element('p', 'mt-2 text-sm text-zinc-600', text(value.explanation)));
  const steps = array(value.steps);
  if (steps.length) {
    const list = element('ol', 'mt-3 space-y-1 text-sm text-zinc-700');
    steps.slice(0, 8).forEach((step, index) => list.append(element('li', '', `${index + 1}. ${typeof step === 'string' ? step : firstText(record(step), ['text', 'content', 'summary'])}`)));
    wrapper.append(list);
  }
  return wrapper;
}

function mathSurfaceRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold text-zinc-950', text(value.title));
  const canvas = document.createElement('canvas');
  canvas.className = 'block h-[280px] w-full rounded-[20px] bg-white/70';
  canvas.width = 760;
  canvas.height = 280;
  wrapper.append(canvas);
  nextFrame(() => drawSurfacePreview(canvas, value));
  appendIfText(wrapper, 'p', 'text-xs text-zinc-500', text(value.caption) || text(value.expression) || text(value.zLabel));
  return wrapper;
}

function statusRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', 'flex items-start gap-3 rounded-xl bg-zinc-50 px-4 py-3 text-sm');
  wrapper.append(element('span', 'mt-1 h-2 w-2 flex-none rounded-full bg-[var(--color-elyan-primary)]'));
  const copy = element('div');
  copy.append(element('div', 'font-medium text-zinc-900', text(value.title) || text(value.status) || 'Status'));
  if (text(value.detail)) copy.append(element('div', 'mt-0.5 text-zinc-600', text(value.detail)));
  wrapper.append(copy); return wrapper;
}

function infoCardRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const title = firstText(value, ['title', 'status', 'name']);
  const tone = /düşük|uyarı|warn|degraded|risk|failed|error/iu.test(`${title} ${text(value.status)} ${text(value.detail)}`) ? 'warn' : 'neutral';
  const wrapper = element('section', `${widgetSurface} ${tone === 'warn' ? 'bg-amber-50/50' : ''}`);
  const head = element('div', 'flex items-start justify-between gap-3');
  appendIfText(head, 'h3', 'text-sm font-semibold text-zinc-900', title);
  if (head.childNodes.length) wrapper.append(head);
  const summary = firstText(value, ['summary', 'detail', 'message', 'content', 'markdown']);
  if (summary) wrapper.append(element('p', 'mt-1 text-sm text-zinc-600', summary));
  const items = array(value.items).slice(0, 12);
  if (items.length) {
    const list = element('dl', 'mt-3 divide-y divide-zinc-100');
    items.forEach((raw) => {
      const item = record(raw);
      const row = element('div', 'grid gap-1 py-2 text-sm md:grid-cols-[150px_1fr]');
      row.append(element('dt', 'text-xs font-medium uppercase tracking-wide text-zinc-400', firstText(item, ['label', 'title', 'name']) || 'Item'));
      row.append(element('dd', 'text-zinc-700', firstText(item, ['value', 'summary', 'text', 'content']) || JSON.stringify(item).slice(0, 160)));
      list.append(row);
    });
    wrapper.append(list);
  }
  return wrapper;
}

function documentRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('article', `${widgetSurface} space-y-4`);
  const exportData = documentExportData(value);
  const header = element('header', 'space-y-2');
  const top = element('div', 'flex items-start justify-between gap-3');
  const copy = element('div', 'min-w-0 space-y-1');
  copy.append(element('div', 'text-[11px] font-medium uppercase tracking-wide text-zinc-400', text(value.format) || 'Document'));
  copy.append(element('h3', 'text-base font-semibold tracking-[-0.012em] text-zinc-950', exportData.title));
  top.append(copy);
  const actions = element('div', 'flex shrink-0 items-center gap-1');
  const md = miniButton('MD', 'Markdown');
  md.addEventListener('click', () => exportDocumentMarkdown(exportData));
  const docx = miniButton('DOCX');
  docx.addEventListener('click', async () => { setBusy(docx, true); try { await exportDocumentDocx(exportData); } finally { setBusy(docx, false); } });
  const pdf = miniButton('PDF');
  pdf.addEventListener('click', async () => { setBusy(pdf, true); try { await exportDocumentPdf(exportData); } finally { setBusy(pdf, false); } });
  actions.append(md, docx, pdf);
  top.append(actions);
  header.append(top);
  if (text(value.summary)) header.append(element('p', 'text-sm text-zinc-600', text(value.summary)));
  const meta = element('div', 'flex flex-wrap gap-2');
  if (value.wordCount != null) meta.append(badge(`${Number(value.wordCount)} words`));
  const sections = array(value.sections).map(record);
  if (sections.length) meta.append(badge(`${sections.length} sections`));
  if (meta.childNodes.length) header.append(meta);
  wrapper.append(header);
  const body = element('div', 'elyan-markdown space-y-4 text-[15px] leading-relaxed');
  if (sections.length) {
    sections.forEach((section) => {
      const sectionNode = element('section', 'space-y-2');
      const heading = text(section.heading);
      if (heading) sectionNode.append(element(Number(section.level) <= 1 ? 'h2' : 'h3', Number(section.level) <= 1 ? 'text-base font-semibold' : 'text-sm font-semibold', heading));
      const content = text(section.content);
      if (content) {
        const contentNode = element('div', 'elyan-markdown');
        contentNode.innerHTML = safeHtml(content);
        sectionNode.append(contentNode);
      }
      body.append(sectionNode);
    });
  } else {
    body.innerHTML = safeHtml(firstText(value, ['markdown', 'content', 'text']) || text(value.title));
  }
  wrapper.append(body);
  return wrapper;
}

function webSearchRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  const header = element('div', 'flex items-start justify-between gap-3');
  const copy = element('div');
  copy.append(element('h3', 'text-sm font-semibold text-zinc-900', text(value.query) || 'Web search'));
  const retrieved = text(value.retrievedAt);
  if (retrieved) copy.append(element('p', 'mt-0.5 text-xs text-zinc-500', retrieved));
  header.append(copy);
  wrapper.append(header);
  const results = array(value.results);
  const list = element('div', 'divide-y divide-zinc-100');
  results.slice(0, 8).forEach((raw) => {
    const item = record(raw);
    const url = safeUrl(item.url);
    const row = itemRow(text(item.title), [text(item.sourceHost), text(item.snippet)].filter(Boolean).join(' · '), url);
    list.append(row);
  });
  if (results.length) wrapper.append(list);
  return wrapper;
}

function attachmentAckRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} flex items-start justify-between gap-4`);
  const copy = element('div');
  appendIfText(copy, 'h3', 'text-sm font-semibold', text(value.summary) || 'Attachment received');
  const details = [
    value.attachmentCount == null ? '' : `${Number(value.attachmentCount)} attachment`,
    value.pageCount == null ? '' : `${Number(value.pageCount)} pages`,
    value.chunkCount == null ? '' : `${Number(value.chunkCount)} chunks`,
    value.hasTable === true ? 'table detected' : '',
    value.hasImage === true ? 'image detected' : '',
  ].filter(Boolean).join(' · ');
  if (details) copy.append(element('p', 'mt-1 text-xs text-zinc-500', details));
  wrapper.append(copy);
  return wrapper;
}

function imageAnalysisRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold', text(value.title) || 'Image analysis');
  appendIfText(wrapper, 'p', 'text-sm text-zinc-700', text(value.description));
  if (text(value.detectedText)) wrapper.append(element('pre', 'overflow-x-auto rounded-xl bg-zinc-50 p-3 text-xs text-zinc-700', text(value.detectedText)));
  const tags = array(value.tags).map(text).filter(Boolean);
  if (tags.length) {
    const chips = element('div', 'flex flex-wrap gap-2');
    tags.forEach((tag) => chips.append(badge(tag)));
    wrapper.append(chips);
  }
  return wrapper;
}

function goalProgressRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const step = Number(value.step) || 0;
  const total = Math.max(1, Number(value.ofSteps) || 1);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  wrapper.append(element('h3', 'text-sm font-semibold', text(value.advancedTo) || 'Goal progress'));
  const track = element('div', 'h-2 overflow-hidden rounded-full bg-zinc-100');
  const bar = element('div', 'h-full rounded-full bg-black');
  bar.style.width = `${Math.min(100, Math.max(0, step / total * 100))}%`;
  track.append(bar); wrapper.append(track);
  wrapper.append(element('p', 'text-xs text-zinc-500 tabular-nums', `${step} / ${total}${value.done === true ? ' · complete' : ''}`));
  if (text(value.blocker)) wrapper.append(element('p', 'text-sm text-amber-700', text(value.blocker)));
  return wrapper;
}

function terminalRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', 'overflow-hidden rounded-2xl bg-zinc-950 text-zinc-100 shadow-[0_1px_3px_rgba(0,0,0,0.18)]');
  wrapper.append(element('div', 'border-b border-white/10 px-4 py-2 text-xs text-zinc-400', firstText(value, ['title', 'command', 'status']) || 'Terminal'));
  const pre = element('pre', 'max-h-[420px] overflow-auto p-4 text-[12px] leading-relaxed');
  pre.textContent = firstText(value, ['output', 'stdout', 'stderr', 'content', 'summary']) || JSON.stringify(value, null, 2);
  wrapper.append(pre);
  return wrapper;
}

function compactWidgetRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-2`);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold', firstText(value, ['title', 'name', 'status']));
  const summary = firstText(value, ['summary', 'detail', 'message', 'url', 'content']);
  if (summary) wrapper.append(element('p', 'text-sm text-zinc-600', summary));
  return wrapper;
}

function taskTraceRenderer(block: AssistantBlock, context: RenderContext): HTMLElement {
  const value = data(block);
  const taskId = text(value.taskId) || context.taskId || '';
  const wrapper = element('section', 'rounded-xl border border-zinc-200 p-4');
  wrapper.dataset.taskId = taskId;
  wrapper.append(element('h3', 'text-sm font-semibold', text(value.title) || 'Task progress'));
  if (text(value.summary)) wrapper.append(element('p', 'mt-1 text-sm text-zinc-600', text(value.summary)));
  const list = element('ol', 'mt-3 space-y-2 text-sm');
  const steps = Array.isArray(value.steps) ? value.steps : [];
  steps.forEach((raw, index) => {
    const step = record(raw);
    list.append(element('li', 'flex gap-2 text-zinc-700', `${index + 1}. ${text(step.title) || text(step.label) || text(step.status) || 'Step'}`));
  });
  wrapper.append(list);
  if (taskId && ['running', 'waiting_approval'].includes(text(value.status))) {
    const actions = element('div', 'mt-4 flex flex-wrap gap-2');
    if (text(value.status) === 'waiting_approval') {
      for (const [label, action] of [['Approve', 'approve'], ['Reject', 'reject']] as const) {
        const button = element('button', action === 'approve' ? 'rounded-lg bg-black px-3 py-2 text-xs font-medium text-white' : 'rounded-lg border border-zinc-200 px-3 py-2 text-xs font-medium', label) as HTMLButtonElement;
        button.type = 'button'; button.dataset.taskAction = action; button.dataset.taskId = taskId; actions.append(button);
      }
    }
    const cancel = element('button', 'rounded-lg border border-zinc-200 px-3 py-2 text-xs font-medium text-zinc-700', 'Cancel') as HTMLButtonElement;
    cancel.type = 'button'; cancel.dataset.taskAction = 'cancel'; cancel.dataset.taskId = taskId; actions.append(cancel);
    wrapper.append(actions);
  }
  if (taskId && text(value.status) === 'completed') {
    const feedback = element('div', 'mt-4 flex gap-2');
    for (const [label, action] of [['Helpful', 'thumbs_up'], ['Not helpful', 'thumbs_down']] as const) {
      const button = element('button', 'rounded-lg border border-zinc-200 px-3 py-2 text-xs font-medium text-zinc-600 hover:bg-zinc-50', label) as HTMLButtonElement;
      button.type = 'button'; button.dataset.taskAction = action; button.dataset.taskId = taskId; feedback.append(button);
    }
    wrapper.append(feedback);
  }
  return wrapper;
}

function fileRenderer(block: AssistantBlock, context: RenderContext): HTMLElement {
  const value = data(block);
  const wrapper = element('section', 'flex items-center justify-between gap-4 rounded-xl border border-zinc-200 p-4');
  const copy = element('div', 'min-w-0');
  copy.append(element('div', 'truncate text-sm font-medium', text(value.fileName) || text(value.title) || 'Elyan artifact'));
  copy.append(element('div', 'mt-0.5 text-xs text-zinc-500', [text(value.mimeType) || text(value.mime) || text(value.artifactType), formatBytes(value.sizeBytes)].filter(Boolean).join(' · ')));
  wrapper.append(copy);
  const taskId = context.taskId || text(value.taskId);
  const artifactId = text(value.artifactId);
  const url = taskId && artifactId ? `/app/api/backend/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactId)}/content` : '';
  if (url) {
    const button = element('button', 'flex-none rounded-lg border border-zinc-200 px-3 py-2 text-xs font-medium disabled:opacity-50', 'Open') as HTMLButtonElement;
    button.type = 'button';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const response = await fetch(url, { credentials: 'same-origin', headers: { accept: 'application/json' } });
        const result = await response.json() as Record<string, unknown>;
        if (!response.ok) throw new Error('artifact_unavailable');
        const downloadUrl = text(record(result.content).downloadUrl) || text(record(result.artifact).downloadUrl);
        const target = new URL(downloadUrl);
        if (target.protocol !== 'https:') throw new Error('artifact_url_invalid');
        location.assign(target.href);
      } catch {
        button.textContent = 'Unavailable';
      } finally {
        button.disabled = false;
      }
    });
    wrapper.append(button);
  }
  return wrapper;
}

function connectorRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold', text(value.title) || text(value.provider) || text(value.tool));
  if (text(value.summary)) wrapper.append(element('p', 'mt-1 text-sm text-zinc-600', text(value.summary)));
  const items = extractItems(value);
  const list = element('div', 'divide-y divide-zinc-200/70');
  items.slice(0, 20).forEach((raw) => {
    const item = record(raw);
    appendIfText(list, 'div', 'py-2 text-sm text-zinc-700', text(item.title) || text(item.name) || text(item.subject) || text(item.summary) || text(item.status));
  });
  if (items.length) wrapper.append(list);
  return wrapper;
}

function stateHeader(value: Record<string, unknown>, fallback: string): HTMLElement {
  const header = element('div', 'mb-3 flex items-center justify-between gap-3');
  header.append(element('h3', 'text-sm font-semibold text-zinc-900', firstText(value, ['title', 'provider', 'tool']) || fallback));
  return header;
}

function itemRow(title: string, subtitle = '', href = ''): HTMLElement {
  const row = href ? element('a', 'block rounded-xl px-3 py-2 hover:bg-zinc-50') as HTMLAnchorElement : element('div', 'rounded-xl px-3 py-2');
  if (href && row instanceof HTMLAnchorElement) { row.href = href; row.target = '_blank'; row.rel = 'noopener noreferrer'; }
  row.append(element('div', 'text-sm font-medium text-zinc-900', title));
  if (subtitle) row.append(element('div', 'mt-0.5 line-clamp-2 text-xs text-zinc-500', subtitle));
  return row;
}

function sourceListRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const type = block.type;
  const wrapper = element('section', widgetSurface);
  const fallbackTitle = ({
    mail_list: 'Gmail',
    calendar_agenda: 'Calendar',
    drive_files: 'Drive',
    github_activity: 'GitHub',
    slack_messages: 'Slack',
  } as Record<string, string>)[type] || 'Connected app';
  wrapper.append(stateHeader(value, fallbackTitle));
  if (text(value.state) === 'error') {
    wrapper.append(element('p', 'text-sm text-red-600', firstText(record(value.error), ['message', 'code']) || 'Bağlantı şu an yanıt vermiyor.'));
    return wrapper;
  }
  const items = extractItems(value, type === 'calendar_agenda' ? ['events'] : type === 'drive_files' ? ['files'] : type === 'slack_messages' ? ['messages'] : []);
  if (!items.length) {
    return wrapper;
  }
  const list = element('div', 'space-y-1');
  items.slice(0, 40).forEach((raw) => {
    const item = record(raw);
    const title = firstText(item, ['subject', 'title', 'name', 'repository', 'text']) || 'Result';
    const subtitle = [
      firstText(item, ['senderName', 'authorName', 'ownerName', 'channelName', 'calendarName', 'kind', 'status']),
      firstText(item, ['preview', 'receivedAt', 'modifiedAt', 'updatedAt', 'startAt', 'timestamp']),
    ].filter(Boolean).join(' · ');
    list.append(itemRow(title, subtitle, safeUrl(item.url) || safeUrl(record(item.action).url) || safeUrl(item.permalink)));
  });
  wrapper.append(list);
  return wrapper;
}

function mailDetailRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', widgetSurface);
  wrapper.append(stateHeader(value, 'Email'));
  if (text(value.state) !== 'ready') {
    appendIfText(wrapper, 'p', 'text-sm text-red-600', text(value.state) === 'error' ? firstText(record(value.error), ['message', 'code']) : '');
    return wrapper;
  }
  wrapper.append(element('div', 'text-sm font-medium', text(value.subject) || 'Email'));
  wrapper.append(element('div', 'mt-1 text-xs text-zinc-500', [text(value.senderName), text(value.receivedAt)].filter(Boolean).join(' · ')));
  const body = element('div', 'elyan-markdown mt-4 max-h-[420px] overflow-y-auto rounded-xl bg-zinc-50 p-3 text-sm');
  const bodyText = text(value.bodyRichText);
  body.innerHTML = value.bodyFormat === 'markdown' ? safeHtml(bodyText) : DOMPurify.sanitize(bodyText.replace(/\n/g, '<br>'));
  wrapper.append(body);
  const attachments = array(value.attachments);
  if (attachments.length) {
    const files = element('div', 'mt-3 flex flex-wrap gap-2');
    attachments.slice(0, 12).forEach((raw) => {
      const item = record(raw);
      files.append(itemRow(text(item.name), [text(item.mimeType), formatBytes(item.sizeBytes)].filter(Boolean).join(' · '), safeUrl(item.downloadUrl) || safeUrl(record(item.action).url)));
    });
    wrapper.append(files);
  }
  return wrapper;
}

function notionPageRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', widgetSurface);
  wrapper.append(stateHeader(value, 'Notion'));
  if (text(value.state) !== 'ready') {
    appendIfText(wrapper, 'p', 'text-sm text-red-600', text(value.state) === 'error' ? firstText(record(value.error), ['message', 'code']) : '');
    return wrapper;
  }
  wrapper.append(itemRow(text(value.title), array(value.breadcrumb).map(text).filter(Boolean).join(' / '), safeUrl(value.url) || safeUrl(record(value.action).url)));
  const list = element('div', 'mt-3 space-y-2');
  array(value.summaryBlocks).slice(0, 16).forEach((raw) => {
    const item = record(raw);
    list.append(element('p', 'text-sm text-zinc-700', text(item.text)));
  });
  wrapper.append(list);
  return wrapper;
}

function toolCallRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', widgetSurface);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold', text(value.title));
  const list = element('div', 'mt-3 space-y-2');
  array(value.calls).slice(0, 40).forEach((raw) => {
    const call = record(raw);
    const status = text(call.status);
    const row = element('div', 'flex items-start justify-between gap-3 rounded-xl bg-zinc-50 px-3 py-2');
    const copy = element('div', 'min-w-0');
    copy.append(element('div', 'truncate text-sm font-medium', firstText(call, ['label', 'toolName']) || 'Tool'));
    copy.append(element('div', 'text-xs text-zinc-500', [text(call.provider), text(call.resultSummary), call.durationMs == null ? '' : `${Number(call.durationMs)}ms`].filter(Boolean).join(' · ')));
    if (status === 'error') row.append(copy, element('span', 'rounded-full bg-red-50 px-2 py-1 text-[11px] text-red-600', status));
    else row.append(copy);
    list.append(row);
  });
  wrapper.append(list);
  return wrapper;
}

function blockGroupRenderer(block: AssistantBlock, context: RenderContext): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  const title = firstText(value, ['title', 'summary']);
  if (title) wrapper.append(element('h3', 'text-sm font-semibold text-zinc-900', title));
  const children = array(value.children).length ? array(value.children) : array(value.blocks);
  wrapper.append(renderBlocks(children, { blockSchemaDigest: ASSISTANT_BLOCK_SCHEMA_DIGEST }, context));
  return wrapper;
}

function dynamicDataList(value: unknown, depth = 0): HTMLElement {
  const container = element(depth === 0 ? 'div' : 'div', depth === 0 ? 'space-y-2' : 'space-y-1');
  if (Array.isArray(value)) {
    value.slice(0, 24).forEach((item, index) => {
      const row = element('div', 'rounded-2xl bg-white/70 px-3 py-2');
      if (typeof item === 'object' && item != null) {
        const recordItem = record(item);
        const title = firstText(recordItem, ['title', 'name', 'subject', 'label', 'summary', 'text', 'status']);
        row.append(element('div', 'text-sm font-medium text-zinc-900', (title || `#${index + 1}`).slice(0, 180)));
        const sub = Object.entries(recordItem)
          .filter(([key, candidate]) => !sensitiveKey(key) && !['title', 'name', 'subject', 'label', 'summary', 'text', 'status'].includes(key) && previewValue(candidate))
          .slice(0, 4)
          .map(([, candidate]) => previewValue(candidate))
          .join(' · ');
        if (sub) row.append(element('div', 'mt-1 text-xs text-zinc-500', sub));
      } else {
        row.textContent = previewValue(item) || `#${index + 1}`;
      }
      container.append(row);
    });
    return container;
  }
  const source = record(value);
  Object.entries(source).forEach(([key, candidate]) => {
    if (sensitiveKey(key) || candidate == null) return;
    if (['title', 'name', 'subject', 'status', 'summary', 'detail', 'message', 'description', 'content', 'markdown'].includes(key)) return;
    const row = element('div', 'rounded-2xl bg-white/70 px-3 py-2');
    if (Array.isArray(candidate) || (typeof candidate === 'object' && candidate != null)) {
      if (depth < 1) {
        const nested = dynamicDataList(candidate, depth + 1);
        if (nested.childNodes.length) row.append(nested);
      }
    } else {
      row.append(element('div', 'min-w-0 break-words text-sm text-zinc-700', previewValue(candidate)));
    }
    if (row.childNodes.length) container.append(row);
  });
  return container;
}

function dynamicBlockRenderer(block: AssistantBlock): HTMLElement {
  const value = data(block);
  const wrapper = element('section', `${widgetSurface} space-y-3`);
  appendIfText(wrapper, 'h3', 'text-sm font-semibold text-zinc-900', firstText(value, ['title', 'name', 'subject', 'status']));
  const summary = firstText(value, ['summary', 'detail', 'message', 'description', 'content', 'markdown']);
  if (summary) {
    const markdown = element('div', 'elyan-markdown text-sm text-zinc-700');
    markdown.innerHTML = safeHtml(summary);
    wrapper.append(markdown);
  }
  const list = dynamicDataList(value);
  if (list.childNodes.length) wrapper.append(list);
  return wrapper;
}

function actionableRenderer(block: AssistantBlock, context: RenderContext): HTMLElement {
  const value = data(block);
  const wrapper = statusRenderer(block);
  const taskId = context.taskId || text(value.taskId);
  if (text(value.kind) === 'approval_needed' && taskId) {
    const actions = element('div', 'ml-auto flex gap-2');
    for (const [label, action] of [['Approve', 'approve'], ['Reject', 'reject']] as const) {
      const button = element('button', action === 'approve' ? 'rounded-lg bg-black px-3 py-2 text-xs text-white' : 'rounded-lg border border-zinc-200 px-3 py-2 text-xs', label) as HTMLButtonElement;
      button.type = 'button'; button.dataset.taskAction = action; button.dataset.taskId = taskId; actions.append(button);
    }
    wrapper.append(actions);
  }
  return wrapper;
}

function svgRenderer(block: AssistantBlock): HTMLElement {
  const wrapper = element('section', 'overflow-hidden rounded-xl border border-zinc-200 bg-white p-3');
  wrapper.innerHTML = DOMPurify.sanitize(text(data(block).svg) || text(data(block).content), {
    USE_PROFILES: { svg: true, svgFilters: false },
    FORBID_TAGS: ['script', 'foreignObject', 'iframe', 'style'],
    FORBID_ATTR: ['onload', 'onclick', 'onerror'],
  });
  return wrapper;
}

['text', 'summary', 'next_steps', 'clarification'].forEach((type) => registry.set(type, markdownRenderer));
['attachment_context', 'context_signal', 'memory_echo', 'proactive_touch', 'capability_unavailable', 'desktop_suggestion', 'vision', 'document_block_skeleton'].forEach((type) => registry.set(type, infoCardRenderer));
registry.set('document_block', documentRenderer);
registry.set('web_search', webSearchRenderer);
registry.set('attachment_ack', attachmentAckRenderer);
registry.set('image_analysis', imageAnalysisRenderer);
registry.set('goal_progress', goalProgressRenderer);
registry.set('terminal', terminalRenderer);
['automation', 'pdf_generate', 'pdf_viewer'].forEach((type) => registry.set(type, compactWidgetRenderer));
registry.set('code', codeRenderer); registry.set('table', tableRenderer); registry.set('chart', chartRenderer);
registry.set('math', mathRenderer); registry.set('math_surface_3d', mathSurfaceRenderer); registry.set('svg', svgRenderer);
registry.set('status', statusRenderer); registry.set('task_trace', taskTraceRenderer); registry.set('actionable', actionableRenderer);
registry.set('file', fileRenderer); registry.set('artifact', fileRenderer);
registry.set('block_group', blockGroupRenderer);
registry.set('mail_detail', mailDetailRenderer);
registry.set('notion_page', notionPageRenderer);
registry.set('tool_call', toolCallRenderer);
['mail_list', 'calendar_agenda', 'drive_files', 'github_activity', 'slack_messages'].forEach((type) => registry.set(type, sourceListRenderer));
registry.set('connector_result', connectorRenderer);

export function registeredAssistantBlockTypes(): string[] {
  return [...registry.keys()].sort();
}

export function renderBlocks(blocks: unknown, metadata: unknown, context: RenderContext = {}): DocumentFragment {
  const fragment = document.createDocumentFragment();
  if (!Array.isArray(blocks)) return fragment;
  const trustedDigest = schemaDigestMatches(metadata);
  for (const raw of blocks) {
    const type = raw && typeof raw === 'object' ? text((raw as Record<string, unknown>).type) : '';
    if (internalTypes.has(type)) continue;
    const validation = validateAssistantBlock(raw);
    const block = validation.block || (raw && typeof raw === 'object' ? raw as AssistantBlock : null);
    if (!block || block.visibility === 'internal' || block.visibility === 'assistant_internal_by_default' || block.isRenderable === false) continue;
    if (suppressLowSourceConfidence(block)) continue;
    const legacyConnector = !validation.valid && connectorWidgetTypes.has(block.type);
    if (legacyConnector && block.visibility !== 'user_visible') continue;
    const canRenderKnown = trustedDigest && (validation.valid || legacyConnector);
    const renderer = canRenderKnown ? registry.get(block.type) || dynamicBlockRenderer : registry.get(block.type) || dynamicBlockRenderer;
    const node = renderer(block, context);
    node.dataset.blockType = block.type || 'unknown';
    if (block.blockId) node.dataset.blockId = block.blockId;
    fragment.append(node);
  }
  return fragment;
}

export function renderMessageContent(message: Record<string, unknown>, target: HTMLElement): void {
  target.replaceChildren();
  const blocks = message.blocks;
  if (Array.isArray(blocks) && blocks.length > 0) {
    target.append(renderBlocks(blocks, message.metadata, { taskId: text(message.taskId) }));
    if (!target.childNodes.length && text(message.content)) {
      const wrapper = element('div', 'elyan-markdown space-y-4');
      wrapper.innerHTML = safeHtml(text(message.content));
      target.append(wrapper);
    }
    return;
  }
  const content = text(message.content);
  const wrapper = element('div', 'elyan-markdown space-y-4');
  wrapper.innerHTML = safeHtml(content);
  target.append(wrapper);
}
