import React from 'react';
import { UIMessage } from 'ai';
import { Bot, User } from 'lucide-react';
import { cn } from '@/lib/utils';

function getMessageText(message: UIMessage): string {
  const text = message.parts
    .filter((part): part is Extract<UIMessage['parts'][number], { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('\n');

  return text.trim();
}

function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern =
    /(\[[0-9]+\]|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__)/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    if (match[1].startsWith('[') && /^\[[0-9]+\]$/.test(match[1])) {
      nodes.push(
        <span key={`${match.index}-cite`} className="chat-message__citation">
          {match[1]}
        </span>
      );
    } else if (match[2] && match[3]) {
      nodes.push(
        <a key={`${match.index}-link`} href={match[3]} target="_blank" rel="noreferrer">
          {match[2]}
        </a>
      );
    } else if (match[4]) {
      nodes.push(
        <code key={`${match.index}-code`} className="chat-message__inline-code">
          {match[4]}
        </code>
      );
    } else if (match[5]) {
      nodes.push(
        <strong key={`${match.index}-strong`}>{match[5]}</strong>
      );
    } else if (match[6]) {
      nodes.push(
        <strong key={`${match.index}-strong-alt`}>{match[6]}</strong>
      );
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

type Block =
  | { type: 'heading'; level: 1 | 2 | 3; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'code'; text: string };

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r/g, '').split('\n');
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.startsWith('```')) {
      const codeLines: string[] = [];
      index += 1;

      while (index < lines.length && !lines[index].startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }

      if (index < lines.length && lines[index].startsWith('```')) {
        index += 1;
      }

      blocks.push({ type: 'code', text: codeLines.join('\n') });
      continue;
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length as 1 | 2 | 3,
        text: headingMatch[2].trim(),
      });
      index += 1;
      continue;
    }

    const listMatch = line.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
    if (listMatch) {
      const ordered = /\d+\./.test(listMatch[2]);
      const items: string[] = [];

      while (index < lines.length) {
        const current = lines[index].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        if (!current) {
          break;
        }

        items.push(current[3].trim());
        index += 1;
      }

      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;

    while (index < lines.length) {
      const nextLine = lines[index];
      if (!nextLine.trim()) {
        break;
      }

      if (
        nextLine.startsWith('```') ||
        /^(#{1,3})\s+/.test(nextLine) ||
        /^(\s*)([-*+]|\d+\.)\s+/.test(nextLine)
      ) {
        break;
      }

      paragraphLines.push(nextLine.trim());
      index += 1;
    }

    blocks.push({ type: 'paragraph', text: paragraphLines.join(' ') });
  }

  return blocks;
}

function renderMarkdownLite(text: string): React.ReactNode {
  const blocks = parseBlocks(text);

  return blocks.map((block, blockIndex) => {
    if (block.type === 'heading') {
      const headingTag = `h${block.level}` as 'h1' | 'h2' | 'h3';
      return React.createElement(headingTag, { key: blockIndex }, renderInline(block.text));
    }

    if (block.type === 'list') {
      const listTag = block.ordered ? 'ol' : 'ul';
      return React.createElement(
        listTag,
        { key: blockIndex },
        block.items.map((item, itemIndex) => (
          <li key={`${blockIndex}-${itemIndex}`}>{renderInline(item)}</li>
        ))
      );
    }

    if (block.type === 'code') {
      return (
        <pre key={blockIndex}>
          <code>{block.text}</code>
        </pre>
      );
    }

    return <p key={blockIndex}>{renderInline(block.text)}</p>;
  });
}

export function ChatMessage({ message }: { message: UIMessage }) {
  const isUser = message.role === 'user';
  const text = getMessageText(message);
  const hasContent = Boolean(text);

  return (
    <article className={cn('chat-message', isUser && 'chat-message--user')}>
      {!isUser && (
        <div className="chat-message__avatar chat-message__avatar--assistant" aria-hidden="true">
          <Bot size={15} strokeWidth={2.2} />
        </div>
      )}

      <div
        className={cn(
          'chat-message__bubble',
          isUser ? 'chat-message__bubble--user' : 'chat-message__bubble--assistant'
        )}
      >
        <div className="chat-message__content">
          {hasContent ? (
            isUser ? (
              <p>{text}</p>
            ) : (
              renderMarkdownLite(text)
            )
          ) : (
            <p>Working...</p>
          )}
        </div>
      </div>

      {isUser && (
        <div className="chat-message__avatar" aria-hidden="true">
          <User size={15} strokeWidth={2.2} />
        </div>
      )}
    </article>
  );
}
