'use client';

import React, { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import { SearchMode } from '@/types/search';
import { ArrowRight, Globe, Mic, Square, Zap, type LucideIcon } from 'lucide-react';

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
};

type SpeechRecognitionAlternativeLike = {
  transcript: string;
};

type SpeechRecognitionResultLike = ArrayLike<SpeechRecognitionAlternativeLike> & {
  isFinal: boolean;
};

type SpeechRecognitionEventLike = {
  results: SpeechRecognitionResultLike[];
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

interface SearchBarProps {
  onSearch: (query: string, mode: SearchMode) => void;
  isLoading?: boolean;
  defaultMode?: SearchMode;
  disabled?: boolean;
}

export function SearchBar({ onSearch, isLoading, defaultMode = 'speed', disabled = false }: SearchBarProps) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>(defaultMode);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const constructor = (window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    }).SpeechRecognition ?? (window as Window & {
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    }).webkitSpeechRecognition;

    setVoiceSupported(Boolean(constructor));

    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim() && !isLoading && !disabled) {
      onSearch(query, mode);
      setQuery('');
    }
  };

  const stopVoice = () => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setVoiceListening(false);
  };

  const startVoice = () => {
    if (!voiceSupported || disabled || isLoading) {
      return;
    }

    const constructor = (window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    }).SpeechRecognition ?? (window as Window & {
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    }).webkitSpeechRecognition;

    if (!constructor) {
      return;
    }

    const recognition = new constructor();
    recognition.lang = 'en-US';
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? '')
        .join(' ')
        .trim();

      if (!transcript) {
        return;
      }

      setQuery(transcript);

      if (event.results?.[event.results.length - 1]?.isFinal) {
        onSearch(transcript, mode);
        setQuery('');
        stopVoice();
      }
    };
    recognition.onend = () => {
      setVoiceListening(false);
      recognitionRef.current = null;
    };
    recognition.onerror = () => {
      setVoiceListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = recognition;
    setVoiceListening(true);
    recognition.start();
  };

  const toggleVoice = () => {
    if (voiceListening) {
      stopVoice();
      return;
    }

    startVoice();
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
          placeholder="Ask Elyan..."
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
        <button
          type="button"
          onClick={toggleVoice}
          className={cn('search-submit', 'search-submit--voice', voiceListening && 'search-submit--active')}
          disabled={disabled || isLoading || !voiceSupported}
          aria-label={
            !voiceSupported
              ? 'Voice input is unavailable in this browser'
              : voiceListening
                ? 'Stop voice input'
                : 'Start voice input'
          }
        >
          {voiceListening ? <Square size={15} strokeWidth={2.6} /> : <Mic size={17} strokeWidth={2.4} />}
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
          Fast answer or quiet research. No extra steps.
        </p>
      </div>
    </div>
  );
}
