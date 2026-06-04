import type { BootstrapSnapshot } from '../../shared/protocol';
import { activeConversationId, agentStatusRecord, asRecord, asString, selectedConversation } from '../lib/data';

interface WorkspaceProps {
  snapshot: BootstrapSnapshot | null;
  selectedConversationId: string;
  composer: string;
  busy: boolean;
  lastError: string;
  logoUrl: string;
  userName: string;
  onComposerChange: (value: string) => void;
  onSend: () => void;
  onConfirmPlan: (pendingPlanId: string, approved: boolean) => void;
}

export function Workspace({
  snapshot,
  selectedConversationId,
  composer,
  busy,
  lastError,
  logoUrl,
  userName,
  onComposerChange,
  onSend,
  onConfirmPlan,
}: WorkspaceProps) {
  const activeId = selectedConversationId || activeConversationId(snapshot);
  const conversation = selectedConversation(snapshot, activeId);
  const messages = conversation?.messages ?? [];
  const firstName = userName.split(' ')[0] || 'Elyan';
  const latestMessage = messages.at(-1);
  const latestMessageAgentStatus = asRecord(asRecord(latestMessage?.meta).agentStatus);
  const runtimeAgentStatus = agentStatusRecord(snapshot);
  const displayStage = asString(
    busy ? runtimeAgentStatus.displayStage ?? 'Bakıyor' : latestMessageAgentStatus.displayStage ?? runtimeAgentStatus.displayStage,
  );
  const displayAction = asString(
    busy ? runtimeAgentStatus.displayAction ?? displayStage : latestMessageAgentStatus.displayAction ?? runtimeAgentStatus.displayAction,
  );
  const showAgentStatus =
    busy ||
    displayStage.length > 0 ||
    asRecord(latestMessage?.meta).needsConfirmation === true;

  return (
    <main className="workspace" aria-label="Elyan chat">
      <div className="workspace-topbar">
        <img src={logoUrl} alt="Elyan" />
      </div>

      <section className={`timeline ${messages.length === 0 ? 'timeline--empty' : ''}`} aria-live="polite">
        {messages.length === 0 ? (
          <div className="empty-state">
            <img src={logoUrl} alt="" aria-hidden="true" />
            <h1>
              Merhaba {firstName},
              <br />
              Aklınızda ne var?
            </h1>
          </div>
        ) : (
          <div className="message-stack">
            {messages.map((message) => {
              const meta = asRecord(message.meta);
              const planPreview = meta.planPreview;
              return (
                <article className={`message message--${message.role}`} key={message.id}>
                  <p>{message.text}</p>
                  {message.needsConfirmation && message.pendingPlanId ? (
                    <div className="approval-card">
                      <strong>Onay gerekiyor</strong>
                      <span>{typeof planPreview === 'string' && planPreview ? planPreview : 'Plan yürütülmeden önce açık onay bekliyor.'}</span>
                      <div className="approval-card__actions">
                        <button type="button" disabled={busy} onClick={() => onConfirmPlan(message.pendingPlanId, true)}>
                          Onayla
                        </button>
                        <button type="button" disabled={busy} onClick={() => onConfirmPlan(message.pendingPlanId, false)}>
                          Reddet
                        </button>
                      </div>
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {showAgentStatus ? (
        <div className="agent-status-line" aria-live="polite">
          <strong>{displayStage || 'Bakıyor'}</strong>
          {displayAction && displayAction !== displayStage ? <span>{displayAction}</span> : null}
        </div>
      ) : null}

      {lastError ? <div className="safe-error">{lastError}</div> : null}

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <textarea
          value={composer}
          onChange={(event) => onComposerChange(event.currentTarget.value)}
          placeholder="Elyan'a sor"
          rows={1}
        />
        <button type="submit" className="composer__send" disabled={busy || composer.trim().length === 0}>
          {busy ? '...' : 'Gönder'}
        </button>
      </form>
    </main>
  );
}
