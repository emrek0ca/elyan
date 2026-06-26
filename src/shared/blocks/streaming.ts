import type { ElyanBlock, ElyanBlockStatus } from './types';

export type ElyanBlockStreamEvent =
  | {
      type: 'block_delta';
      messageId: string;
      blockIndex: number;
      appendMarkdown: string;
    }
  | {
      type: 'block_replace';
      messageId: string;
      blockIndex: number;
      block: ElyanBlock;
    }
  | {
      type: 'block_status';
      messageId: string;
      blockIndex: number;
      status: ElyanBlockStatus | string;
    };

export interface ElyanBlockStreamMessage {
  id: string;
  blocks?: ElyanBlock[];
  [key: string]: unknown;
}

function updateBlockAt(blocks: ElyanBlock[], index: number, update: (block: ElyanBlock) => ElyanBlock): ElyanBlock[] {
  if (!Number.isInteger(index) || index < 0 || index >= blocks.length) {
    return blocks;
  }
  return blocks.map((block, blockIndex) => (blockIndex === index ? update(block) : block));
}

export function applyBlockStreamEvent<T extends ElyanBlockStreamMessage>(
  messages: T[],
  event: ElyanBlockStreamEvent,
): T[] {
  let changed = false;
  const nextMessages = messages.map((message) => {
    if (message.id !== event.messageId || !Array.isArray(message.blocks)) {
      return message;
    }
    const nextBlocks = updateBlockAt(message.blocks, event.blockIndex, (block) => {
      if (event.type === 'block_replace') {
        return event.block;
      }
      if (event.type === 'block_status') {
        return { ...block, status: event.status };
      }
      const existing = typeof block.markdown === 'string'
        ? block.markdown
        : typeof block.content === 'string'
          ? block.content
          : '';
      return { ...block, type: block.type || 'text', markdown: `${existing}${event.appendMarkdown}` };
    });
    if (nextBlocks === message.blocks) {
      return message;
    }
    changed = true;
    return { ...message, blocks: nextBlocks };
  });
  return changed ? nextMessages : messages;
}
