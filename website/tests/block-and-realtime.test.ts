import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { ASSISTANT_BLOCK_SCHEMA_DIGEST, schemaDigestMatches, validateAssistantBlock } from '../src/lib/client/block-contract';
import { registeredAssistantBlockTypes, renderMessageContent } from '../src/lib/client/block-registry';
import { createRealtimeState, mergeRealtimeEvent } from '../src/lib/client/realtime-merge';
import { buildAttachmentPayload, buildComposerAttachments } from '../src/lib/client/attachments';
import { buildWebCompactContext } from '../src/lib/client/chat-controller';
import assistantBlockSchema from '../src/contracts/assistant-blocks.schema.json';

const textBlock = {
  type: 'text', version: 1, blockId: 'block-1', source: 'elyan', visibility: 'user_visible', renderHints: {}, data: { markdown: '**Hello**' },
};

describe('assistant block contract', () => {
  it('keeps the generated validator browser-safe ESM', () => {
    const source = readFileSync(join(process.cwd(), 'src/contracts/assistant-blocks.validator.mjs'), 'utf8');
    expect(source).not.toMatch(/\brequire\(|\bmodule\.exports\b|\bexports\./);
  });

  it('validates the versioned backend schema snapshot and digest', () => {
    expect(validateAssistantBlock(textBlock).valid).toBe(true);
    expect(validateAssistantBlock(null).valid).toBe(false);
    expect(schemaDigestMatches({ blockSchemaDigest: ASSISTANT_BLOCK_SCHEMA_DIGEST })).toBe(true);
    expect(schemaDigestMatches({ blockSchemaDigest: 'stale' })).toBe(false);
  });

  it('registers every current backend assistant block type for web rendering', () => {
    const canonicalTypes = (assistantBlockSchema as { 'x-elyan-canonical-types'?: string[] })['x-elyan-canonical-types'] ?? [];
    const userVisibleTypes = canonicalTypes.filter((type) => !['reasoning_trace', 'security_decision'].includes(type));
    expect(canonicalTypes.length).toBeGreaterThan(40);
    expect(registeredAssistantBlockTypes()).toEqual([...userVisibleTypes].sort());
  });

  it('renders blocks as primary truth and sanitizes markdown', () => {
    const target = document.createElement('div');
    renderMessageContent({ blocks: [{ ...textBlock, data: { markdown: '<script>alert(1)</script>**Block truth**' } }], content: 'legacy duplicate' }, target);
    expect(target.textContent).toContain('Block truth');
    expect(target.textContent).not.toContain('legacy duplicate');
    expect(target.querySelector('script')).toBeNull();
  });

  it('renders recognized backend widget blocks even when a legacy payload misses strict schema fields', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [
        { type: 'mail_list', visibility: 'user_visible', data: { title: 'Gmail', messages: [{ subject: 'Backend widget result' }] } },
        { type: 'calendar_agenda', visibility: 'user_visible', data: { title: 'Calendar', events: [{ title: 'Planning sync' }] } },
        { type: 'drive_files', visibility: 'user_visible', data: { title: 'Drive', files: [{ name: 'Roadmap.pdf' }] } },
        { type: 'connector_result', visibility: 'user_visible', data: { title: 'Connector', items: [{ title: 'Normalized result' }] } },
      ],
    }, target);
    expect(target.textContent).toContain('Backend widget result');
    expect(target.textContent).toContain('Planning sync');
    expect(target.textContent).toContain('Roadmap.pdf');
    expect(target.textContent).toContain('Normalized result');
  });

  it('renders function chart and 3D math surface blocks as real visual widgets', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [
        { type: 'chart', version: 1, blockId: 'chart-1', source: 'elyan', visibility: 'user_visible', renderHints: {}, data: { title: 'Polinom grafiği', chartType: 'function', expression: 'x^2 - 3*x + 2' } },
        { type: 'math_surface_3d', version: 1, blockId: 'surface-1', source: 'elyan', visibility: 'user_visible', renderHints: {}, data: { title: 'Yüzey', expression: 'sin(x)+cos(y)', resolution: 24 } },
      ],
      metadata: { blockSchemaDigest: ASSISTANT_BLOCK_SCHEMA_DIGEST },
    }, target);
    expect(target.textContent).toContain('Polinom grafiği');
    expect(target.textContent).toContain('Yüzey');
    expect(target.querySelectorAll('canvas')).toHaveLength(2);
  });

  it('renders legacy top-level chart fields and connector result arrays without waiting for a website release', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [
        { type: 'chart', visibility: 'user_visible', chartType: 'function', expression: '2x^2-3x+1', title: 'Legacy chart' },
        { type: 'connector_result', visibility: 'user_visible', title: 'MCP', results: [{ title: 'Dynamic tool result', status: 'ok' }] },
      ],
    }, target);
    expect(target.textContent).toContain('Legacy chart');
    expect(target.textContent).toContain('Dynamic tool result');
    expect(target.querySelector('canvas')).not.toBeNull();
  });

  it('renders canonical source widgets and tool telemetry with safe links', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [
        { type: 'mail_detail', version: 1, blockId: 'mail-1', source: 'gmail', visibility: 'user_visible', renderHints: {}, data: { state: 'ready', messageId: 'm1', threadId: 't1', senderName: 'Ali', recipients: [], subject: 'Contract', receivedAt: 'now', bodyRichText: '**Body**', bodyFormat: 'markdown', attachments: [] } },
        { type: 'notion_page', version: 1, blockId: 'notion-1', source: 'notion', visibility: 'user_visible', renderHints: {}, data: { state: 'ready', pageId: 'p1', title: 'Roadmap', breadcrumb: ['Elyan'], summaryBlocks: [{ kind: 'text', text: 'Ship web parity' }], action: { type: 'open_link', url: 'https://notion.so/page' } } },
        { type: 'tool_call', version: 1, blockId: 'tool-1', source: 'elyan', visibility: 'user_visible', renderHints: {}, data: { calls: [{ callId: 'c1', toolName: 'gmail.search', provider: 'gmail', status: 'ok', resultSummary: '2 results' }] } },
      ],
      metadata: { blockSchemaDigest: ASSISTANT_BLOCK_SCHEMA_DIGEST },
    }, target);
    expect(target.textContent).toContain('Contract');
    expect(target.textContent).toContain('Roadmap');
    expect(target.textContent).toContain('gmail.search');
    expect(target.querySelector('a')?.getAttribute('href')).toBe('https://notion.so/page');
  });

  it('does not fail open for connector widgets without explicit user visibility', () => {
    const target = document.createElement('div');
    renderMessageContent({ blocks: [{ type: 'mail_list', data: { title: 'Hidden mail', messages: [{ subject: 'Private subject' }] } }] }, target);
    expect(target.textContent).not.toContain('Private subject');
    expect(target.textContent).not.toContain('Hidden mail');
  });

  it('renders future user-visible block data through a safe dynamic fallback', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [{
        type: 'future_widget',
        visibility: 'user_visible',
        data: {
          title: 'Future MCP result',
          summary: 'Rendered without a website release.',
          token: 'secret-token',
          items: [{ title: 'Dynamic item', status: 'ok' }],
        },
      }],
      metadata: { blockSchemaDigest: 'future' },
    }, target);
    expect(target.textContent).toContain('Future MCP result');
    expect(target.textContent).toContain('Rendered without a website release.');
    expect(target.textContent).toContain('Dynamic item');
    expect(target.textContent).not.toContain('secret-token');
  });

  it('renders document sections as the primary block surface', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [{
        type: 'document_block',
        version: 1,
        blockId: 'doc-1',
        source: 'elyan',
        visibility: 'user_visible',
        renderHints: {},
        data: { title: 'Rapor', format: 'report', sections: [{ heading: 'Giriş', content: '**Hazır** içerik.', level: 2 }], summary: 'Kısa özet', wordCount: 120 },
      }],
      metadata: { blockSchemaDigest: ASSISTANT_BLOCK_SCHEMA_DIGEST },
      content: 'legacy duplicate',
    }, target);
    expect(target.textContent).toContain('Rapor');
    expect(target.textContent).toContain('Giriş');
    expect(target.textContent).toContain('Hazır içerik.');
    expect(target.textContent).not.toContain('legacy duplicate');
  });

  it('does not render internal reasoning and security blocks', () => {
    const target = document.createElement('div');
    renderMessageContent({ blocks: [{ ...textBlock, type: 'reasoning_trace', data: { title: 'secret' } }] }, target);
    expect(target.textContent).not.toContain('secret');

    renderMessageContent({ blocks: [{ ...textBlock, visibility: 'assistant_internal_by_default', data: { markdown: 'internal text' } }] }, target);
    expect(target.textContent).not.toContain('internal text');
  });

  it('suppresses low source confidence warning widgets', () => {
    const target = document.createElement('div');
    renderMessageContent({
      blocks: [
        { type: 'context_signal', visibility: 'user_visible', data: { title: 'Kaynak güveni düşük', status: 'Uyarı', detail: 'Bu cevap için bulunan kaynaklar sınırlıydı; kritik bir konuysa doğrulamak isteyebilirsin.' } },
        { ...textBlock, data: { markdown: 'Asıl cevap görünür.' } },
      ],
    }, target);
    expect(target.textContent).not.toContain('Kaynak güveni düşük');
    expect(target.textContent).not.toContain('Uyarı');
    expect(target.textContent).toContain('Asıl cevap görünür.');
  });
});

describe('web composer attachments', () => {
  it('builds backend-compatible derived attachment manifests without raw upload hints', async () => {
    const file = new File(['Elyan attachment text'], 'notes.md', { type: 'text/markdown' });
    const prepared = await buildComposerAttachments([file]);
    const payload = buildAttachmentPayload(prepared);
    expect(payload.promptSuffix).toContain('Readable preview from notes.md');
    expect(payload.attachments[0]).toMatchObject({
      fileName: 'notes.md',
      mimeType: 'text/markdown',
      raw_file_uploaded: false,
      data_origin: 'local_derived',
      privacy_level: 'local_derived',
      hasReadableText: true,
    });
    expect(JSON.stringify(payload.attachments)).not.toMatch(/base64|rawBinary|raw_file_uploaded\":true/);
  });
});

describe('web chat continuity metadata', () => {
  it('builds mobile-compatible compact context for follow-up messages', () => {
    const compact = buildWebCompactContext([
      { id: 'm1', role: 'user', content: 'Atatürk hakkında rapor yaz.' },
      { id: 'm2', role: 'assistant', content: 'Rapor hazırlandı. Ana başlıklar: giriş, reformlar, sonuç.' },
      { id: 'm3', role: 'user', content: 'Grafiğini de çiz.' },
    ], '11111111-1111-4111-8111-111111111111', 'bunu genişlet', 0);
    expect(compact).toMatchObject({
      mode: 'complete_adaptive',
      source: 'web',
      requireCompleteResponse: true,
      sessionScope: { sessionId: '11111111-1111-4111-8111-111111111111' },
      lastAssistantBlocksDigest: 'Rapor hazırlandı. Ana başlıklar: giriş, reformlar, sonuç.',
    });
    expect(JSON.stringify(compact)).toContain('Grafiğini de çiz.');
  });

  it('does not attach compact context to a brand new session', () => {
    expect(buildWebCompactContext([], null, 'merhaba')).toBeNull();
  });
});

describe('terminal realtime merge', () => {
  it('treats message.completed as terminal and fences stale ACK/delta', () => {
    const state = createRealtimeState();
    mergeRealtimeEvent(state, { eventId: '1', type: 'message.delta', payload: { assistantMessageId: 'm1', delta: 'draft' } });
    mergeRealtimeEvent(state, { eventId: '2', type: 'message.completed', payload: { assistantMessageId: 'm1', content: 'final' } });
    mergeRealtimeEvent(state, { eventId: '3', type: 'message.delta', payload: { assistantMessageId: 'm1', delta: ' stale' } });
    expect(state.messages.get('m1')?.content).toBe('final');
    expect(state.messages.get('m1')?.status).toBe('completed');
  });

  it('deduplicates replayed event ids and requests REST resync', () => {
    const state = createRealtimeState();
    const first = mergeRealtimeEvent(state, { eventId: '9', type: 'message.delta', payload: { assistantMessageId: 'm1', delta: 'A' } });
    const duplicate = mergeRealtimeEvent(state, { eventId: '9', type: 'message.delta', payload: { assistantMessageId: 'm1', delta: 'A' } });
    expect(first.changedId).toBe('m1'); expect(duplicate.changedId).toBeNull();
    expect(mergeRealtimeEvent(state, { eventId: '10', type: 'resync_required' }).resync).toBe(true);
  });

  it('uses cumulative snapshots, carries outer task blocks, and reports the owning session', () => {
    const state = createRealtimeState();
    mergeRealtimeEvent(state, { eventId: '11', type: 'message.delta', payload: { sessionId: 'session-a', assistantMessageId: 'm2', delta: 'A' } });
    const merged = mergeRealtimeEvent(state, { eventId: '12', type: 'message.delta', payload: { sessionId: 'session-a', assistantMessageId: 'm2', content: 'Authoritative snapshot', blocks: [textBlock] } });
    expect(merged.sessionId).toBe('session-a');
    expect(state.messages.get('m2')?.content).toBe('Authoritative snapshot');
    expect(state.messages.get('m2')?.blocks).toEqual([textBlock]);
  });
});
