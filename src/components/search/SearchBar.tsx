'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import { SearchMode } from '@/types/search';
import { ArrowRight, Globe, Zap, type LucideIcon } from 'lucide-react';

interface SearchBarProps {
  onSearch: (query: string, mode: SearchMode) => void;
  isLoading?: boolean;
  defaultMode?: SearchMode;
  disabled?: boolean;
}

export function SearchBar({ onSearch, isLoading, defaultMode = 'speed', disabled = false }: SearchBarProps) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>(defaultMode);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !isLoading && !disabled) {
      onSearch(query, mode);
      setQuery('');
    }
  };

  const modes: { id: SearchMode; icon: LucideIcon; label: string }[] = [
    { id: 'speed', icon: Zap, label: 'Speed' },
    { id: 'research', icon: Globe, label: 'Research' },
  ];

  return (
    <div className="search-shell">
      <form onSubmit={handleSubmit} className="search-form">
        <label className="visually-hidden" htmlFor="elyan-query">
          Ask Elyan a question
        </label>
        <input
          id="elyan-query"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a web question, compare options, or inspect a URL..."
          className="search-input"
          aria-describedby="elyan-search-hint"
          disabled={isLoading || disabled}
        />
        <button
          type="submit"
          disabled={isLoading || disabled || !query.trim()}
          className="search-submit"
          aria-label={
            disabled
              ? 'Search disabled until a model is available'
              : isLoading
                ? 'Generating response'
                : 'Submit query'
          }
        >
          {isLoading ? <div className="search-submit__spinner" /> : <ArrowRight size={18} strokeWidth={2.4} />}
        </button>
      </form>

      <div className="search-shell__footer">
        <div className="mode-switch" role="group" aria-label="Search mode">
          {modes.map((m) => {
            const Icon = m.icon;
            return (
              <button
                type="button"
                key={m.id}
                onClick={() => setMode(m.id)}
                className={cn(
                  'mode-switch__button',
                  mode === m.id && 'mode-switch__button--active'
                )}
                aria-pressed={mode === m.id}
                disabled={disabled || isLoading}
              >
                <Icon size={14} strokeWidth={2.2} />
                {m.label}
              </button>
            );
          })}
        </div>
        <p id="elyan-search-hint" className="mode-switch__hint">
          Speed for direct answers. Research for broader synthesis with citations.
        </p>
      </div>
    </div>
  );
}
