'use client';

import React, { useEffect } from 'react';
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport, type UIMessage } from 'ai';
import { AlertCircle, Sparkles } from 'lucide-react';
import { SearchBar } from '@/components/search/SearchBar';
import { ModelInfo } from '@/types/provider';
import { SearchMode } from '@/types/search';
import { ChatMessage } from '@/components/chat/ChatMessage';

type ChatInterfaceProps = {
  chatId?: string;
  initialQuery?: string;
  initialMode?: SearchMode;
  availableModels: ModelInfo[];
  apiPath?: string;
};

const starterPrompts = [
  'What changed in Next.js 15.5?',
  'Compare OpenAI and Anthropic strengths',
  'Summarize the latest AI search trends',
];

function toChatMessageContent(message: UIMessage) {
  const text = message.parts
    .filter((part): part is Extract<UIMessage['parts'][number], { type: 'text' }> => part.type === 'text')
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join('\n');

  return text.trim();
}

function normalizeTransportMessages(messages: UIMessage[]) {
  return messages
    .map((message) => ({
      role: message.role,
      content: toChatMessageContent(message),
    }))
    .filter((message) => message.content.length > 0);
}

function presentChatError(error: Error | null | undefined) {
  const message = error?.message ?? 'The current request could not be completed.';
  const normalized = message.toLowerCase();

  if (normalized.includes('no model is available')) {
    return {
      title: 'No model is available',
      detail: message,
      hint: 'Set OLLAMA_URL or one cloud API key, then reload and re-check /api/healthz.',
    };
  }

  if (normalized.includes('searxng')) {
    return {
      title: 'Search backend unavailable',
      detail: message,
      hint: 'Search is optional. Check /api/healthz if you want live retrieval and citations, or continue in local-only mode.',
    };
  }

  if (normalized.includes('hosted usage is not allowed')) {
    return {
      title: 'Hosted usage is not allowed',
      detail: message,
      hint: 'Use the local runtime path or move the account to a hosted plan with entitlements.',
    };
  }

  if (normalized.includes('control-plane session is required')) {
    return {
      title: 'Login required',
      detail: message,
      hint: 'Sign in to the hosted control plane or use the public preview surface.',
    };
  }

  if (normalized.includes('hosted usage limit reached')) {
    return {
      title: 'Hosted limit reached',
      detail: message,
      hint: 'Wait for the daily reset or upgrade to a plan with higher guardrails.',
    };
  }

  if (normalized.includes('hosted credits are exhausted')) {
    return {
      title: 'Hosted credits exhausted',
      detail: message,
      hint: 'Switch to local/BYOK usage or top up the hosted plan before retrying.',
    };
  }

  if (normalized.includes('environment configuration is invalid')) {
    return {
      title: 'Environment configuration is invalid',
      detail: message,
      hint: 'Check .env, then verify /api/healthz before sending another request.',
    };
  }

  return {
    title: 'Request failed',
    detail: message,
    hint: 'Check /api/healthz for readiness and /api/capabilities for the current runtime surface.',
  };
}

export default function ChatInterface({
  chatId,
  initialQuery = '',
  initialMode = 'speed',
  availableModels,
  apiPath = '/api/chat',
}: ChatInterfaceProps) {
  const hasAvailableModels = availableModels.length > 0;
  const initialModelId = availableModels[0]?.id ?? '';
  const [selectedModelId, setSelectedModelId] = React.useState(initialModelId);
  const [lastSubmittedMode, setLastSubmittedMode] = React.useState<SearchMode>(initialMode);
  const didSubmitInitialQueryRef = React.useRef(false);
  const transport = React.useMemo(
    () =>
      new DefaultChatTransport({
        api: apiPath,
        prepareSendMessagesRequest: ({ body, messages }) => ({
          body: {
            ...body,
            messages: normalizeTransportMessages(messages),
          },
        }),
      }),
    [apiPath]
  );
  const {
    messages,
    status,
    error,
    sendMessage,
    regenerate,
    clearError,
  } = useChat({
    transport,
    id: chatId,
  });

  const isLoading = status === 'submitted' || status === 'streaming';
  const hasMessages = messages.length > 0;
  const canSubmit = hasAvailableModels && Boolean(selectedModelId);
  const isPriming = !error && !hasMessages && canSubmit && (isLoading || Boolean(initialQuery));
  const statusLabel =
    initialQuery && !hasMessages && canSubmit
      ? 'Preparing answer'
      : status === 'submitted'
        ? 'Gathering context'
        : status === 'streaming'
          ? 'Writing answer'
          : null;

  useEffect(() => {
    if (didSubmitInitialQueryRef.current || !initialQuery || messages.length > 0 || !canSubmit) {
      return;
    }

    didSubmitInitialQueryRef.current = true;
    setLastSubmittedMode(initialMode);
    void sendMessage({ text: initialQuery }, { body: { mode: initialMode, modelId: selectedModelId } });
  }, [canSubmit, initialMode, initialQuery, messages.length, selectedModelId, sendMessage]);

  useEffect(() => {
    if (!initialQuery || messages.length > 0) {
      return;
    }

    if (!canSubmit) {
      didSubmitInitialQueryRef.current = false;
    }
  }, [canSubmit, initialQuery, messages.length]);

  useEffect(() => {
    if (!hasAvailableModels) {
      return;
    }

    if (!availableModels.some((model) => model.id === selectedModelId)) {
      setSelectedModelId(availableModels[0].id);
    }
  }, [availableModels, hasAvailableModels, selectedModelId]);

  const handleSearch = (query: string, mode: SearchMode) => {
    if (!canSubmit || isLoading) {
      return;
    }

    setLastSubmittedMode(mode);
    clearError();
    void sendMessage({ text: query }, { body: { mode, modelId: selectedModelId } });
  };

  const handleRetry = () => {
    if (isLoading) {
      return;
    }

    clearError();

    if (messages.length > 0) {
      void regenerate({ body: { mode: lastSubmittedMode, modelId: selectedModelId } });
      return;
    }

    if (initialQuery && canSubmit) {
      setLastSubmittedMode(initialMode);
      sendMessage({ text: initialQuery }, { body: { mode: initialMode, modelId: selectedModelId } });
    }
  };

  const showNoModelState = !error && !hasMessages && !hasAvailableModels;
  const showEmptyState = !error && !hasMessages && !initialQuery && hasAvailableModels;
  const presentedError = presentChatError(error);

  return (
    <div className="chat-page">
      <div className="chat-page__frame">
        <div className="chat-page__stream">
          {error && (
            <div className="chat-error" role="alert">
              <div className="chat-error__icon" aria-hidden="true">
                <AlertCircle size={15} strokeWidth={2.4} />
              </div>
              <div className="chat-error__body">
                <div className="chat-error__title">{presentedError.title}</div>
                <div className="chat-error__text">{presentedError.detail}</div>
                <div className="chat-error__hint">{presentedError.hint}</div>
                <div className="chat-error__actions">
                  <button type="button" className="chat-error__button chat-error__button--primary" onClick={handleRetry}>
                    Retry
                  </button>
                  <button type="button" className="chat-error__button" onClick={clearError}>
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          )}

          {showEmptyState && (
            <section className="chat-empty">
              <div className="chat-empty__panel">
                <div className="home-page__eyebrow">
                  <Sparkles size={12} strokeWidth={2.2} />
                  Start a search
                </div>
                <h1 className="chat-empty__title">
                  Ask a question, get a grounded answer.
                </h1>
                <p className="chat-empty__lead">
                  Elyan is local-first: private context stays on your machine, while the shared control plane handles accounts, billing, and entitlements for hosted use.
                </p>
                <div className="chat-empty__meta">
                  <span className="chat-empty__meta-item">Speed mode for direct answers</span>
                  <span className="chat-empty__meta-item">Research mode for broader synthesis</span>
                  <span className="chat-empty__meta-item">Health at `/api/healthz`</span>
                  <span className="chat-empty__meta-item">Capabilities at `/api/capabilities`</span>
                </div>
                <div className="chat-empty__prompts">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className="chat-empty__prompt"
                      onClick={() => handleSearch(prompt, 'speed')}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          )}

          {showNoModelState && (
            <section className="chat-empty">
              <div className="chat-empty__panel">
                <div className="home-page__eyebrow">
                  <Sparkles size={12} strokeWidth={2.2} />
                  No model configured
                </div>
                <h1 className="chat-empty__title">
                  Configure Ollama or a cloud key to start.
                </h1>
                <p className="chat-empty__lead">
                  Elyan cannot answer until at least one provider is available. Set `OLLAMA_URL`, or add an OpenAI, Anthropic, or Groq API key, then reload.
                </p>
                <div className="chat-empty__meta">
                  <span className="chat-empty__meta-item">Local Ollama or cloud provider required</span>
                  <span className="chat-empty__meta-item">Chat input stays disabled until a model exists</span>
                </div>
                <div className="chat-empty__steps" aria-label="First run steps">
                  <div className="chat-empty__step">1. Start Ollama and pull a model, or set one cloud key.</div>
                  <div className="chat-empty__step">2. Check `/api/healthz` until models and search are ready.</div>
                  <div className="chat-empty__step">3. Inspect `/api/capabilities`, then send a real question.</div>
                </div>
              </div>
            </section>
          )}

          {isPriming && (
            <div className="chat-loading" aria-label="Loading response">
              <div className="chat-page__status">
                <div className="chat-page__status-dot" aria-hidden="true" />
                <span>{statusLabel ?? 'Preparing answer'}</span>
              </div>
              <div className="chat-loading__bar" />
              <div className="chat-loading__bar" />
              <div className="chat-loading__bar" />
            </div>
          )}

          {hasMessages && messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))}

          {isLoading && hasMessages && (
            <div className="chat-page__status" aria-live="polite">
              <div className="chat-page__status-dot" aria-hidden="true" />
              <span>{statusLabel ?? 'Working'}</span>
            </div>
          )}
        </div>

        <div className="chat-page__composer">
          <div className="chat-page__composer-inner">
            <div className="chat-model-row">
              {hasAvailableModels ? (
                <>
                  <label className="chat-model-row__label" htmlFor="model-select">
                    Model
                  </label>
                  <select
                    id="model-select"
                    className="chat-model-row__select"
                    value={selectedModelId}
                    onChange={(event) => setSelectedModelId(event.target.value)}
                  >
                    {availableModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <p className="chat-model-row__empty">
                  No model is currently available. Set `OLLAMA_URL` or one cloud API key, then check `/api/healthz`.
                </p>
              )}
            </div>
            <SearchBar
              isLoading={isLoading}
              defaultMode={initialMode}
              disabled={!canSubmit}
              onSearch={handleSearch}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
