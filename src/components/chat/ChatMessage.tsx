'use client';

import React from 'react';
import { UIMessage } from 'ai';
import { Bot, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import { cn } from '@/lib/utils';

export type ChatMessageSurface = {
  chips: Array<{
    label: string;
    tone: 'neutral' | 'accent' | 'success' | 'warning';
  }>;
  sourceSummary?: string;
  statusSummary?: string;
};

function getMessageText(message: UIMessage): string {
  const text = message.parts
    .filter((part): part is Extract<UIMessage['parts'][number], { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('\n');

  return text.trim();
}

export function ChatMessage({
  message,
  surface,
}: {
  message: UIMessage;
  surface?: ChatMessageSurface;
}) {
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
        {surface ? (
          <div className="chat-message__meta">
            {surface.chips.map((chip) => (
              <span key={`${chip.label}-${chip.tone}`} className={cn('chat-message__chip', `chat-message__chip--${chip.tone}`)}>
                {chip.label}
              </span>
            ))}
            {surface.sourceSummary ? <span className="chat-message__source">{surface.sourceSummary}</span> : null}
            {surface.statusSummary ? <span className="chat-message__status">{surface.statusSummary}</span> : null}
          </div>
        ) : null}
        <div className="chat-message__content">
          {hasContent ? (
            isUser ? (
              <p>{text}</p>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
                skipHtml
                components={{
                  a: ({ href, children }) => (
                    <a href={href ?? '#'} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {text}
              </ReactMarkdown>
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
