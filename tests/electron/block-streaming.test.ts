import { describe, expect, it } from 'vitest';
import { applyBlockStreamEvent } from '../../src/shared/blocks/streaming';

describe('block streaming helpers', () => {
  it('appends markdown to only the targeted message block', () => {
    const messages = [
      { id: 'msg-1', blocks: [{ type: 'text', markdown: 'Merhaba' }] },
      { id: 'msg-2', blocks: [{ type: 'text', markdown: 'Ayrı mesaj' }] },
    ];

    const next = applyBlockStreamEvent(messages, {
      type: 'block_delta',
      messageId: 'msg-1',
      blockIndex: 0,
      appendMarkdown: ', Elyan',
    });

    expect(next).not.toBe(messages);
    expect(next[0]?.blocks?.[0]?.markdown).toBe('Merhaba, Elyan');
    expect(next[1]).toBe(messages[1]);
  });

  it('replaces a block and updates block status', () => {
    const messages = [
      {
        id: 'msg-1',
        blocks: [
          { type: 'task_trace', title: 'Plan', status: 'running' },
          { type: 'terminal', output: 'başladı' },
        ],
      },
    ];

    const replaced = applyBlockStreamEvent(messages, {
      type: 'block_replace',
      messageId: 'msg-1',
      blockIndex: 1,
      block: { type: 'desktop_action', title: 'Dosya kaydediliyor', status: 'running' },
    });
    const completed = applyBlockStreamEvent(replaced, {
      type: 'block_status',
      messageId: 'msg-1',
      blockIndex: 0,
      status: 'completed',
    });

    expect(completed[0]?.blocks?.[1]?.type).toBe('desktop_action');
    expect(completed[0]?.blocks?.[0]?.status).toBe('completed');
  });

  it('returns the original array when the target is not present', () => {
    const messages = [{ id: 'msg-1', blocks: [{ type: 'text', markdown: 'Sabit' }] }];

    const next = applyBlockStreamEvent(messages, {
      type: 'block_delta',
      messageId: 'missing',
      blockIndex: 0,
      appendMarkdown: ' yok',
    });

    expect(next).toBe(messages);
  });
});
