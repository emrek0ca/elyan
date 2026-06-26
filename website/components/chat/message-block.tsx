"use client";

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { motion, AnimatePresence } from 'motion/react';
import { ChatMessageBlock } from '@/lib/chat-block-parser';

interface MessageBlockProps {
  block: ChatMessageBlock;
  isUser: boolean;
}

export function MessageBlock({ block, isUser }: MessageBlockProps) {
  const [expanded, setExpanded] = useState(false);

  // If it's the standard text block, render as markdown
  if (block.type === 'text') {
    return (
      <div className={`prose prose-sm md:prose-base max-w-none ${isUser ? 'prose-invert text-inherit' : 'text-inherit'}`}>
        <ReactMarkdown 
          remarkPlugins={[remarkGfm]} 
          rehypePlugins={[rehypeRaw]}
          components={{
            p: ({node, ...props}: any) => <p className="mb-2 last:mb-0" {...props} />,
            a: ({node, ...props}: any) => <a className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer" {...props} />,
            code: ({node, inline, className, children, ...props}: any) => {
              const match = /language-(\w+)/.exec(className || '');
              return !inline && match ? (
                <div className="relative bg-[#1A1A1A] rounded-xl my-4 overflow-hidden border border-[rgba(255,255,255,0.1)]">
                  <div className="flex items-center justify-between px-4 py-2 bg-[rgba(255,255,255,0.05)] border-b border-[rgba(255,255,255,0.05)]">
                    <span className="text-xs font-mono text-[rgba(255,255,255,0.5)]">{match[1]}</span>
                  </div>
                  <pre className="p-4 overflow-x-auto text-sm text-[rgba(255,255,255,0.9)]">
                    <code className={className} {...props}>
                      {children}
                    </code>
                  </pre>
                </div>
              ) : (
                <code className="bg-[var(--outline)] px-1.5 py-0.5 rounded-md text-sm font-mono text-pink-600" {...props}>
                  {children}
                </code>
              );
            },
            think: ({node, children, ...props}: any) => (
              <div className="my-2 p-3 bg-[var(--text)/5] border-l-2 border-[var(--outline)] rounded-r-xl text-[var(--text-muted)] text-sm italic whitespace-pre-wrap" {...props}>
                {children}
              </div>
            )
          } as any}
        >
          {block.markdown}
        </ReactMarkdown>
      </div>
    );
  }

  // If it's a reasoning block (like mobile)
  if (block.type === 'reasoning') {
    return (
      <div className="my-2 flex flex-col items-start w-full">
        <button 
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 px-3 py-1.5 bg-[var(--text)/5] hover:bg-[rgba(34,28,23,0.06)] border border-[var(--outline)] rounded-full transition-colors text-sm text-[var(--text-muted)]"
        >
          <svg 
            width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            className={`transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`}
          >
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
          <span className="font-medium">Düşünce süreci</span>
        </button>
        
        <AnimatePresence>
          {expanded && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden w-full mt-2"
            >
              <div className="p-4 bg-[var(--surface-1)] border-l-2 border-[var(--outline)] text-[var(--text-muted)] text-sm rounded-r-xl">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {block.markdown}
                </ReactMarkdown>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

  // Fallback for other block types (toolResult, etc.)
  return (
    <div className="my-2 p-3 bg-[rgba(34,28,23,0.02)] border border-[var(--outline)] rounded-xl text-sm font-mono text-[var(--text-muted)] overflow-hidden">
      <div className="text-xs uppercase tracking-wider mb-1 opacity-50">{block.type}</div>
      <div className="whitespace-pre-wrap">{block.markdown}</div>
    </div>
  );
}
