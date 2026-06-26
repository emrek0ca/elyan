import { useState, useEffect, type MouseEvent } from 'react';
import type { BootstrapSnapshot } from '../../shared/protocol';
import { accountUsageSummary, authReady, chatAccessState, runtimeReady } from '../lib/data';
import type { ListSurfaceItem } from './ListSurface';

interface LeftRailProps {
  snapshot: BootstrapSnapshot | null;
  logoUrl: string;
  userName: string;
  userEmail: string;
  hasTrafficLights: boolean;
  activeSurface: 'chat' | 'settings' | 'apps' | 'tasks' | 'archives';
  historyItems: ListSurfaceItem[];
  selectedConversationId: string;
  isOpen: boolean;
  isCompactViewport: boolean;
  onToggleRail: () => void;
  onCreateConversation: () => void;
  onOpenApps: () => void;
  onOpenTasks?: () => void;
  onOpenSettings: () => void;
  onOpenArchives: () => void;
  onSelectConversation: (conversationId: string) => void;
  onRenameConversation: (conversationId: string, currentTitle: string) => void;
  onArchiveConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
}

export function LeftRail({
  snapshot,
  logoUrl,
  userName,
  userEmail,
  hasTrafficLights,
  activeSurface,
  historyItems,
  selectedConversationId,
  isOpen,
  isCompactViewport,
  onToggleRail,
  onCreateConversation,
  onOpenApps,
  onOpenTasks = noop,
  onOpenSettings,
  onOpenArchives,
  onSelectConversation,
  onRenameConversation,
  onArchiveConversation,
  onDeleteConversation,
}: LeftRailProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; conversationId: string; title: string } | null>(null);

  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);
  const authenticated = authReady(snapshot);
  const runtimeIsReady = runtimeReady(snapshot);
  const accessState = chatAccessState(snapshot);
  const usageSummary = accountUsageSummary(snapshot);
  const accountStatus = authenticated
    ? accessState.locked
      ? `${usageSummary.planLabel} · Kullanıma kapalı`
      : `${usageSummary.planLabel} · ${usageSummary.tokenSummaryLabel}`
    : runtimeIsReady
      ? 'Giriş yap'
      : 'Başlatılıyor';
  const shouldShowQuotaBars = authenticated && !accessState.locked && usageSummary.showQuotaCounters;
  const railLabel = isOpen ? (isCompactViewport ? 'Kenar çubuğunu kapat' : 'Kenar çubuğunu daralt') : isCompactViewport ? 'Kenar çubuğunu aç' : 'Kenar çubuğunu genişlet';
  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredHistoryItems = historyItems.filter((item) => {
    if (!normalizedQuery) {
      return true;
    }
    const haystack = `${item.title} ${item.subtitle} ${item.meta}`.toLowerCase();
    return haystack.includes(normalizedQuery);
  });

  function openContextMenu(event: MouseEvent<HTMLButtonElement>, item: ListSurfaceItem) {
    event.preventDefault();
    const menuWidth = 184;
    const menuHeight = 150;
    const margin = 12;
    const x = Math.max(margin, Math.min(event.clientX, window.innerWidth - menuWidth - margin));
    const y = Math.max(margin, Math.min(event.clientY, window.innerHeight - menuHeight - margin));
    setContextMenu({
      x,
      y,
      conversationId: item.id,
      title: item.title,
    });
  }

  return (
    <aside
      className={`left-rail ${isOpen ? 'left-rail--open' : 'left-rail--closed'} ${hasTrafficLights ? 'left-rail--traffic-lights' : ''}`}
      aria-label="Elyan sidebar"
    >
      <div className={`rail-window-row ${hasTrafficLights ? 'rail-window-row--traffic-lights' : ''}`}>
        <div className="rail-brand">
          <img src={logoUrl} alt="" aria-hidden="true" />
          <span>Elyan</span>
        </div>
        <button type="button" className="rail-toggle" onClick={onToggleRail} aria-label={railLabel}>
          {isOpen ? <IconCollapse /> : <IconExpand />}
        </button>
      </div>

      <div className="rail-search">
        <span className="rail-search__icon" aria-hidden="true">
          <IconSearch />
        </span>
        <input
          type="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.currentTarget.value)}
          placeholder="Ara"
          aria-label="Sohbetlerde ara"
        />
      </div>

      <nav className="rail-nav" aria-label="Elyan">
        <button type="button" className={`rail-nav__item rail-nav__item--primary ${activeSurface === 'chat' ? 'rail-nav__item--active' : ''}`} onClick={onCreateConversation}>
          <IconChat />
          <span>Yeni sohbet</span>
        </button>
        <button type="button" className={`rail-nav__item ${activeSurface === 'apps' ? 'rail-nav__item--active' : ''}`} onClick={onOpenApps}>
          <IconGrid />
          <span>Uygulamalar</span>
        </button>
        <button type="button" className={`rail-nav__item ${activeSurface === 'tasks' ? 'rail-nav__item--active' : ''}`} onClick={onOpenTasks}>
          <IconTasks />
          <span>Desktop görevleri</span>
        </button>
      </nav>

      <section className="rail-history" aria-label="Geçmiş sohbetler">
        <div className="rail-history__header">
          <span>Geçmiş sohbetler</span>
          <button type="button" className="rail-history__header-btn" onClick={onOpenArchives} aria-label="Arşivlenmiş sohbetler">
            <IconArchive />
          </button>
        </div>
        <div className="rail-history__list">
          {filteredHistoryItems.length > 0 ? (
            filteredHistoryItems.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`rail-history__item ${selectedConversationId === item.id ? 'rail-history__item--active' : ''}`}
                onClick={() => onSelectConversation(item.id)}
                onContextMenu={(event) => openContextMenu(event, item)}
              >
                <strong>{item.title}</strong>
                <span>{item.subtitle || 'Senkron sohbet'}</span>
                <small>{item.meta}</small>
              </button>
            ))
          ) : (
            <div className="rail-history__empty">{normalizedQuery ? 'Sonuç yok' : 'Senkron sohbet bulunamadı'}</div>
          )}
        </div>
      </section>

      <div className="rail-spacer" />

      <button
        type="button"
        className={`rail-user ${activeSurface === 'settings' ? 'rail-user--active' : ''}`}
        onClick={onOpenSettings}
        aria-label="Ayarlar"
      >
        <img src={logoUrl} alt="" aria-hidden="true" />
        <span>
          <strong>{userName}</strong>
          <small>{accountStatus}</small>
          {shouldShowQuotaBars ? (
            <div className="rail-user__quotas">
              {usageSummary.quotaWindows.map((w) => (
                <div key={w.title} className="rail-user__quota-bar" title={`${w.title}: ${w.remainingLabel}`}>
                  <div className="rail-user__quota-fill" style={{ width: `${(w.remainingFraction ?? 1) * 100}%` }} />
                </div>
              ))}
            </div>
          ) : null}
        </span>
      </button>

      {contextMenu && (
        <div className="context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="context-menu__item"
            onClick={() => {
              onSelectConversation(contextMenu.conversationId);
              setContextMenu(null);
            }}
          >
            Aç
          </button>
          <button
            type="button"
            className="context-menu__item"
            onClick={() => {
              onRenameConversation(contextMenu.conversationId, contextMenu.title);
              setContextMenu(null);
            }}
          >
            Yeniden adlandır
          </button>
          <button
            type="button"
            className="context-menu__item"
            onClick={() => {
              onArchiveConversation(contextMenu.conversationId);
              setContextMenu(null);
            }}
          >
            Arşivle
          </button>
          <button
            type="button"
            className="context-menu__item context-menu__item--danger"
            onClick={() => {
              onDeleteConversation(contextMenu.conversationId);
              setContextMenu(null);
            }}
          >
            Sil
          </button>
        </div>
      )}
    </aside>
  );
}

function IconArchive() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: '1em', height: '1em' }}>
      <rect width="20" height="5" x="2" y="4" rx="1" />
      <path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" />
      <path d="M10 13h4" />
    </svg>
  );
}

function noop() {
  // Optional in focused component tests.
}

function IconChat() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
      <line x1="9" y1="10" x2="15" y2="10"></line>
      <line x1="12" y1="7" x2="12" y2="13"></line>
    </svg>
  );
}

function IconGrid() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1.5"></rect>
      <rect x="14" y="3" width="7" height="7" rx="1.5"></rect>
      <rect x="14" y="14" width="7" height="7" rx="1.5"></rect>
      <rect x="3" y="14" width="7" height="7" rx="1.5"></rect>
    </svg>
  );
}

function IconTasks() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 6h11" />
      <path d="M9 12h11" />
      <path d="M9 18h11" />
      <path d="m4 6 1 1 2-2" />
      <path d="m4 12 1 1 2-2" />
      <path d="m4 18 1 1 2-2" />
    </svg>
  );
}

function IconSearch() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="8"></circle>
      <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </svg>
  );
}

function IconCollapse() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
      <line x1="9" y1="3" x2="9" y2="21"></line>
      <path d="M5.5 9h1M5.5 12h1M5.5 15h1"></path>
    </svg>
  );
}

function IconExpand() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
      <line x1="9" y1="3" x2="9" y2="21"></line>
      <path d="M5.5 9h1M5.5 12h1M5.5 15h1"></path>
    </svg>
  );
}
