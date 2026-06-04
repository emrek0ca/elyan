import type { BootstrapSnapshot } from '../../shared/protocol';
import { authReady, backendReady, runtimeReady } from '../lib/data';

interface LeftRailProps {
  snapshot: BootstrapSnapshot | null;
  logoUrl: string;
  userName: string;
  userEmail: string;
  hasTrafficLights: boolean;
  activeSurface: 'chat' | 'settings' | 'apps' | 'skills' | 'tasks' | 'history';
  isOpen: boolean;
  isCompactViewport: boolean;
  onToggleRail: () => void;
  onCreateConversation: () => void;
  onOpenApps: () => void;
  onOpenSkills: () => void;
  onOpenTasks: () => void;
  onOpenHistory: () => void;
  onOpenSettings: () => void;
}

export function LeftRail({
  snapshot,
  logoUrl,
  userName,
  userEmail,
  hasTrafficLights,
  activeSurface,
  isOpen,
  isCompactViewport,
  onToggleRail,
  onCreateConversation,
  onOpenApps,
  onOpenSkills,
  onOpenTasks,
  onOpenHistory,
  onOpenSettings,
}: LeftRailProps) {
  const authenticated = authReady(snapshot);
  const backendIsReady = backendReady(snapshot);
  const runtimeIsReady = runtimeReady(snapshot);
  const accountStatus = authenticated ? (backendIsReady ? 'Hazır' : 'Senkronize oluyor') : runtimeIsReady ? 'Giriş yap' : 'Başlatılıyor';
  const railLabel = isOpen ? (isCompactViewport ? 'Kenar çubuğunu kapat' : 'Kenar çubuğunu daralt') : isCompactViewport ? 'Kenar çubuğunu aç' : 'Kenar çubuğunu genişlet';

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

      <nav className="rail-nav" aria-label="Elyan">
        <button type="button" className={`rail-nav__item ${activeSurface === 'chat' ? 'rail-nav__item--active' : ''}`} onClick={onCreateConversation}>
          <IconChat />
          <span>Yeni sohbet</span>
        </button>
        <button type="button" className={`rail-nav__item ${activeSurface === 'apps' ? 'rail-nav__item--active' : ''}`} onClick={onOpenApps}>
          <IconGrid />
          <span>Uygulamalar</span>
        </button>
        <button type="button" className={`rail-nav__item ${activeSurface === 'skills' ? 'rail-nav__item--active' : ''}`} onClick={onOpenSkills}>
          <IconSpark />
          <span>Yetenekler</span>
        </button>
        <button type="button" className={`rail-nav__item ${activeSurface === 'tasks' ? 'rail-nav__item--active' : ''}`} onClick={onOpenTasks}>
          <IconTasks />
          <span>Görevler</span>
        </button>
        <button type="button" className={`rail-nav__item ${activeSurface === 'history' ? 'rail-nav__item--active' : ''}`} onClick={onOpenHistory}>
          <IconHistory />
          <span>Geçmiş</span>
        </button>
      </nav>

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
        </span>
        <i className={backendIsReady ? 'status-dot status-dot--ready' : 'status-dot'} aria-label={backendIsReady ? 'Backend hazır' : 'Backend bekliyor'} />
      </button>
    </aside>
  );
}

function IconChat() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4.5 4.5h11v8h-5.8L6 15.4v-2.9H4.5v-8Zm1.3 1.3v5.4h1.5v1.6l2-1.6h4.9V5.8H5.8Z" />
    </svg>
  );
}

function IconGrid() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 4h5v5H4V4Zm1.3 1.3v2.4h2.4V5.3H5.3ZM11 4h5v5h-5V4Zm1.3 1.3v2.4h2.4V5.3h-2.4ZM4 11h5v5H4v-5Zm1.3 1.3v2.4h2.4v-2.4H5.3ZM11 11h5v5h-5v-5Zm1.3 1.3v2.4h2.4v-2.4h-2.4Z" />
    </svg>
  );
}

function IconSpark() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M9.3 2.8h1.4l.7 4.1 3.1-2.7 1 1-2.7 3.1 4.1.7v1.4l-4.1.7 2.7 3.1-1 1-3.1-2.7-.7 4.1H9.3l-.7-4.1-3.1 2.7-1-1 2.7-3.1-4.1-.7V9l4.1-.7-2.7-3.1 1-1 3.1 2.7.7-4.1Z" />
    </svg>
  );
}

function IconHistory() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M9.8 3.5a6.3 6.3 0 1 1-5.5 3.3H2.2V5.5h4.4v4.4H5.3V7.7a4.9 4.9 0 1 0 4.5-2.9V3.5Zm.7 3v4l3 1.8-.7 1.1-3.6-2.2V6.5h1.3Z" />
    </svg>
  );
}

function IconTasks() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5 4.5h10v11H5v-11Zm1.3 1.3v8.4h7.4V5.8H6.3Zm1 1.4h5.4v1.3H7.3V7.2Zm0 2.6h5.4v1.3H7.3V9.8Zm0 2.6h3.2v1.3H7.3v-1.3Z" />
    </svg>
  );
}

function IconCollapse() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M12.8 4.8 8.5 9l4.3 4.2-1 1.1-5.3-5.3 5.3-5.4 1 1.2Z" />
    </svg>
  );
}

function IconExpand() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="m7.2 4.8 1-1.1 5.3 5.4-5.3 5.3-1-1.1L11.5 10 7.2 4.8Z" />
    </svg>
  );
}
