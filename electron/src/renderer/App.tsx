import { startTransition, useEffect, useRef, useState } from 'react';
import type { BootstrapSnapshot, JsonMap, RuntimeResponse, SystemCapabilities, WindowState } from '../shared/protocol';
import logoUrl from '../../../logo.png';
import authMascotUrl from './assets/auth-mascot.png';
import { Titlebar } from './components/Titlebar';
import { getDesktopApi } from './desktop-api';
import { AuthSurface } from './panels/AuthSurface';
import { LeftRail } from './panels/LeftRail';
import { ListSurface, type ListSurfaceItem } from './panels/ListSurface';
import { SettingsSurface } from './panels/SettingsSurface';
import { Workspace } from './panels/Workspace';
import {
  accountDisplayName,
  accountEmail,
  activeConversationId,
  applyRuntimeResult,
  asRecord,
  authReady,
  runtimePayloadReady,
  runtimeReady,
  runtimeResponseErrorCode,
  snapshotConversations,
  withBackend,
  withRuntime,
  type HydrationState,
  type PlainRecord,
} from './lib/data';
import { itemsFromRuntimeList } from './lib/runtime-list-items';

const desktopApi = getDesktopApi();
const MAX_HYDRATION_RETRIES = 6;
const PAIRING_POLL_INTERVAL_MS = 1800;

const initialHydrationState: HydrationState = {
  phase: 'idle',
  attempt: 0,
  lastHydratedAt: '',
  nextRetryInMs: 0,
  lastErrorCode: '',
};

type AuthMode = 'login' | 'register';
type ActiveSurface = 'chat' | 'settings' | 'apps' | 'skills' | 'tasks' | 'history';
type ListSurfaceKey = Extract<ActiveSurface, 'apps' | 'skills' | 'tasks' | 'history'>;

interface SurfaceListState {
  items: ListSurfaceItem[];
  loading: boolean;
  error: string;
}

const initialSurfaceListState = (): Record<ListSurfaceKey, SurfaceListState> => ({
  apps: { items: [], loading: false, error: '' },
  skills: { items: [], loading: false, error: '' },
  tasks: { items: [], loading: false, error: '' },
  history: { items: [], loading: false, error: '' },
});

export function App() {
  const [snapshot, setSnapshot] = useState<BootstrapSnapshot | null>(null);
  const [systemCapabilities, setSystemCapabilities] = useState<SystemCapabilities | null>(null);
  const [windowState, setWindowState] = useState<WindowState | null>(null);
  const [isRailOpen, setIsRailOpen] = useState(true);
  const [isCompactViewport, setIsCompactViewport] = useState(false);
  const [selectedConversationId, setSelectedConversationId] = useState('');
  const [composer, setComposer] = useState('');
  const [busy, setBusy] = useState(false);
  const [lastError, setLastError] = useState('');
  const [, setHydrationState] = useState<HydrationState>(initialHydrationState);
  const [activeSurface, setActiveSurface] = useState<ActiveSurface>('chat');
  const [surfaceLists, setSurfaceLists] = useState<Record<ListSurfaceKey, SurfaceListState>>(initialSurfaceListState);
  const [authMode, setAuthMode] = useState<AuthMode>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authDisplayName, setAuthDisplayName] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');
  const [isClosing, setIsClosing] = useState(false);
  const hydratedRef = useRef(false);
  const hydrationRetryRef = useRef(0);
  const listRequestRef = useRef(0);
  const hydrationTimerRef = useRef<number | null>(null);
  const pairingPollTimerRef = useRef<number | null>(null);
  const pairingPollSessionRef = useRef('');

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 720px)');
    const syncViewport = () => {
      setIsCompactViewport(mediaQuery.matches);
    };
    syncViewport();
    mediaQuery.addEventListener('change', syncViewport);

    const unsubscribers = [
      desktopApi.subscribe('runtime-status', (payload) => {
        setSnapshot((current) => (current ? withRuntime(current, payload) : current));
      }),
      desktopApi.subscribe('backend-truth', (payload) => {
        setSnapshot((current) => (current ? withBackend(current, payload) : current));
      }),
      desktopApi.subscribe('window-lifecycle', (payload) => {
        const state = asRecord(payload).state;
        if (state) {
          setWindowState(state as WindowState);
        }
      }),
      desktopApi.subscribe('close-handshake', (payload) => {
        if (asRecord(payload).phase === 'requested') {
          setIsClosing(true);
          window.setTimeout(() => {
            void desktopApi.window.acknowledgeCloseAnimation();
          }, 170);
        }
      }),
    ];

    void bootstrap();
    return () => {
      clearPairingPoll();
      clearHydrationRetry();
      mediaQuery.removeEventListener('change', syncViewport);
      for (const unsubscribe of unsubscribers) {
        unsubscribe();
      }
    };
  }, []);

  useEffect(() => {
    if (!isCompactViewport) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') {
        return;
      }
      if (activeSurface === 'settings') {
        setActiveSurface('chat');
        return;
      }
      setIsRailOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [activeSurface, isCompactViewport]);

  useEffect(() => {
    const pairing = asRecord(asRecord(snapshot?.state).pairing);
    const sessionId = String(pairing.lastSessionId ?? '').trim();
    const status = String(pairing.lastSessionStatus ?? '').trim().toLowerCase();
    if (!authReady(snapshot) || !sessionId || status !== 'pending') {
      clearPairingPoll();
      return;
    }
    if (pairingPollSessionRef.current !== sessionId) {
      schedulePairingPoll(sessionId, 900);
    }
  }, [snapshot]);

  async function bootstrap() {
    try {
      const [bootSnapshot, capabilities, state] = await Promise.all([
        desktopApi.bootstrap(),
        desktopApi.system.getCapabilities(),
        desktopApi.window.getState(),
      ]);
      startTransition(() => {
        setSnapshot(bootSnapshot);
        setSystemCapabilities(capabilities);
        setWindowState(state);
        setSelectedConversationId(activeConversationId(bootSnapshot));
        setAuthEmail(accountEmail(bootSnapshot));
      });
      if (!hydratedRef.current) {
        hydratedRef.current = true;
        void hydrateTruth('bootstrap');
      }
    } catch (error) {
      setLastError(error instanceof Error ? error.message : 'Electron bootstrap başarısız.');
      scheduleHydrationRetry('bootstrap_failed');
    }
  }

  async function hydrateTruth(reason: 'bootstrap' | 'manual' | 'retry' = 'manual') {
    clearHydrationRetry();
    setHydrationState((current) => ({
      ...current,
      phase: 'hydrating',
      nextRetryInMs: 0,
      lastErrorCode: '',
    }));
    try {
      const [runtimeStatus, authMe, mobileBootstrap, runtimeSession] = await Promise.all([
        desktopApi.request({ capability: 'runtime.status', payload: {} }),
        desktopApi.request({ capability: 'backend.auth_me', payload: {} }),
        desktopApi.request({ capability: 'backend.mobile_bootstrap', payload: {} }),
        desktopApi.request({ capability: 'runtime.session', payload: {} }),
      ]);
      setSnapshot((current) => {
        if (!current) {
          return current;
        }
        let next = current;
        if (runtimeStatus.ok) {
          next = withRuntime(next, runtimeStatus.result);
          const runtimeResult = asRecord(runtimeStatus.result);
          if (Object.keys(asRecord(runtimeResult.controlPlane)).length > 0) {
            next = withBackend(next, { controlPlane: runtimeResult.controlPlane });
          }
        }
        if (authMe.ok) {
          next = withBackend(next, { authMe: authMe.result });
        }
        if (mobileBootstrap.ok) {
          next = withBackend(next, { mobileBootstrap: mobileBootstrap.result });
        }
        if (runtimeSession.ok) {
          next = withBackend(next, { runtimeSession: runtimeSession.result });
        }
        return next;
      });
      if (runtimePayloadReady(runtimeStatus.result)) {
        hydrationRetryRef.current = 0;
        setHydrationState({
          phase: 'ready',
          attempt: 0,
          lastHydratedAt: new Date().toISOString(),
          nextRetryInMs: 0,
          lastErrorCode: '',
        });
        return;
      }
      scheduleHydrationRetry(runtimeResponseErrorCode(runtimeStatus) || reason);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : 'Runtime hydration başarısız.');
      scheduleHydrationRetry('hydration_failed');
    }
  }

  async function refreshShell() {
    clearPairingPoll();
    clearHydrationRetry();
    hydrationRetryRef.current = 0;
    hydratedRef.current = false;
    setLastError('');
    await bootstrap();
  }

  function clearHydrationRetry() {
    if (hydrationTimerRef.current !== null) {
      window.clearTimeout(hydrationTimerRef.current);
      hydrationTimerRef.current = null;
    }
  }

  function clearPairingPoll() {
    if (pairingPollTimerRef.current !== null) {
      window.clearTimeout(pairingPollTimerRef.current);
      pairingPollTimerRef.current = null;
    }
    pairingPollSessionRef.current = '';
  }

  async function refreshBootstrapSnapshot() {
    const nextSnapshot = await desktopApi.bootstrap();
    setSnapshot(nextSnapshot);
    return nextSnapshot;
  }

  function schedulePairingPoll(sessionId: string, delayMs = PAIRING_POLL_INTERVAL_MS) {
    if (!sessionId) {
      clearPairingPoll();
      return;
    }
    if (pairingPollTimerRef.current !== null) {
      window.clearTimeout(pairingPollTimerRef.current);
    }
    pairingPollSessionRef.current = sessionId;
    pairingPollTimerRef.current = window.setTimeout(() => {
      pairingPollTimerRef.current = null;
      void pollPairingSession(sessionId);
    }, delayMs);
  }

  async function pollPairingSession(sessionId: string) {
    if (!sessionId || pairingPollSessionRef.current !== sessionId) {
      return;
    }
    try {
      const response = await desktopApi.request({
        capability: 'pairing.get_session',
        payload: { sessionId },
      });
      const nextSnapshot = await refreshBootstrapSnapshot();
      const pairing = asRecord(asRecord(nextSnapshot.state).pairing);
      const nextSessionId = String(pairing.lastSessionId ?? '').trim();
      const nextStatus = String(pairing.lastSessionStatus ?? '').trim().toLowerCase();
      if (pairingPollSessionRef.current !== sessionId) {
        return;
      }
      if (response.ok && nextSessionId === sessionId && nextStatus === 'pending') {
        schedulePairingPoll(sessionId);
        return;
      }
      clearPairingPoll();
      if (nextStatus === 'claimed' || nextStatus === 'active' || nextStatus === 'ready') {
        await hydrateTruth('manual');
      }
    } catch {
      if (pairingPollSessionRef.current === sessionId) {
        schedulePairingPoll(sessionId, 2600);
      }
    }
  }

  function scheduleHydrationRetry(errorCode: string) {
    if (hydrationRetryRef.current >= MAX_HYDRATION_RETRIES) {
      setHydrationState((current) => ({
        ...current,
        phase: 'degraded',
        nextRetryInMs: 0,
        lastErrorCode: errorCode,
      }));
      return;
    }
    const attempt = hydrationRetryRef.current + 1;
    hydrationRetryRef.current = attempt;
    const nextRetryInMs = Math.min(30000, 900 * 2 ** (attempt - 1));
    setHydrationState((current) => ({
      ...current,
      phase: 'retrying',
      attempt,
      nextRetryInMs,
      lastErrorCode: errorCode,
    }));
    hydrationTimerRef.current = window.setTimeout(() => {
      hydrationTimerRef.current = null;
      void hydrateTruth('retry');
    }, nextRetryInMs);
  }

  async function sendComposer() {
    const text = composer.trim();
    if (!text || busy) {
      return;
    }
    setBusy(true);
    setLastError('');
    try {
      const response = await desktopApi.request({
        capability: 'conversation.send',
        payload: {
          conversationId: selectedConversationId || activeConversationId(snapshot),
          text,
        },
      });
      if (!response.ok) {
        setLastError(response.error?.message ?? 'Mesaj gönderilemedi.');
        return;
      }
      setComposer('');
      setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
      const result = asRecord(response.result);
      const conversationId = String(result.conversationId ?? '');
      if (conversationId) {
        setSelectedConversationId(conversationId);
      }
    } finally {
      setBusy(false);
    }
  }

  async function createConversation() {
    setBusy(true);
    setActiveSurface('chat');
    try {
      const response = await desktopApi.request({ capability: 'conversation.create', payload: { title: '' } });
      if (response.ok) {
        setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
        const result = asRecord(response.result);
        const id = String(result.conversationId ?? asRecord(result.conversation).id ?? '');
        if (id) {
          setSelectedConversationId(id);
        }
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmPlan(pendingPlanId: string, approved: boolean) {
    setBusy(true);
    try {
      const response = await desktopApi.request({
        capability: 'conversation.confirm_plan',
        payload: {
          conversationId: selectedConversationId || activeConversationId(snapshot),
          pendingPlanId,
          approved,
        },
      });
      if (response.ok) {
        setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
      }
    } finally {
      setBusy(false);
    }
  }

  async function submitAuth() {
    if (authBusy) {
      return;
    }
    setAuthBusy(true);
    setAuthError('');
    try {
      const response = await desktopApi.request({
        capability: authMode === 'login' ? 'backend.auth_login' : 'backend.auth_register',
        payload: {
          email: authEmail.trim(),
          password: authPassword,
          displayName: authDisplayName.trim(),
        },
      });
      const safeError = authErrorFromResponse(response);
      if (safeError) {
        setAuthError(safeError);
        return;
      }
      setAuthPassword('');
      setSnapshot((current) => (current ? mergeHydratedRuntimeResult(current, response) : current));
      await hydrateTruth('manual');
    } finally {
      setAuthBusy(false);
    }
  }

  async function logout() {
    clearPairingPoll();
    setAuthBusy(true);
    setAuthError('');
    try {
      const response = await desktopApi.request({ capability: 'backend.auth_logout', payload: {} });
      if (!response.ok) {
        setAuthError(response.error?.message ?? 'Çıkış yapılamadı.');
        return;
      }
      setAuthPassword('');
      setSnapshot((current) => (current ? mergeHydratedRuntimeResult(current, response) : current));
      await hydrateTruth('manual');
    } finally {
      setAuthBusy(false);
    }
  }

  async function ensureRegistered() {
    const response = await desktopApi.request({ capability: 'runtime.ensure_registered', payload: {} });
    await hydrateTruth();
  }

  async function createPairingSession() {
    clearPairingPoll();
    const response = await desktopApi.request({
      capability: 'pairing.create_session',
      payload: {
        deviceLabel: 'Elyan',
        platform: systemCapabilities?.platform ?? 'desktop',
        runtimeVersion: '1.0.0',
      },
    });
    if (response.ok) {
      const refreshed = await refreshBootstrapSnapshot();
      const pairing = asRecord(asRecord(refreshed.state).pairing);
      const sessionId = String(pairing.lastSessionId ?? pairing.sessionId ?? pairing.id ?? '').trim();
      const status = String(pairing.lastSessionStatus ?? pairing.status ?? '').trim().toLowerCase();
      if (sessionId && status === 'pending') {
        schedulePairingPoll(sessionId, 700);
      }
    }
  }

  async function openAppsSurface() {
    setActiveSurface('apps');
    await loadRuntimeList('apps');
  }

  async function openSkillsSurface() {
    setActiveSurface('skills');
    await loadRuntimeList('skills');
  }

  async function openHistorySurface() {
    setActiveSurface('history');
    await loadRuntimeList('history');
  }

  async function openTasksSurface() {
    setActiveSurface('tasks');
    await loadRuntimeList('tasks');
  }

  function dismissRailOnCompact() {
    if (isCompactViewport) {
      setIsRailOpen(false);
    }
  }

  function toggleRail() {
    setIsRailOpen((current) => !current);
  }

  async function refreshActiveList() {
    if (activeSurface === 'apps' || activeSurface === 'skills' || activeSurface === 'tasks' || activeSurface === 'history') {
      await loadRuntimeList(activeSurface);
    }
  }

  async function loadRuntimeList(surface: ListSurfaceKey) {
    const requestId = ++listRequestRef.current;
    setSurfaceLists((current) => ({
      ...current,
      [surface]: {
        ...current[surface],
        loading: true,
        error: '',
      },
    }));
    try {
      const capability =
        surface === 'apps'
          ? 'mcp.tools.list'
          : surface === 'skills'
            ? 'skill.list'
            : surface === 'tasks'
              ? 'backend.tasks.list'
              : 'conversation.list';
      const payload: JsonMap =
        surface === 'tasks'
          ? { limit: 20, hydrateDetails: true, refresh: false }
          : { refresh: false };
      const response = await desktopApi.request({ capability, payload });
      if (!response.ok) {
        setSurfaceLists((current) => ({
          ...current,
          [surface]: {
            items: [],
            loading: false,
            error: response.error?.message ?? 'Liste alınamadı.',
          },
        }));
        return;
      }
      let nextSnapshot = snapshot;
      setSnapshot((current) => {
        nextSnapshot = current ? applyRuntimeResult(current, response) : current;
        return nextSnapshot;
      });
      if (requestId !== listRequestRef.current) {
        return;
      }
      setSurfaceLists((current) => ({
        ...current,
        [surface]: {
          items: itemsFromRuntimeList(surface, response.result, nextSnapshot),
          loading: false,
          error: '',
        },
      }));
    } finally {
      if (requestId === listRequestRef.current) {
        setSurfaceLists((current) => ({
          ...current,
          [surface]: {
            ...current[surface],
            loading: false,
          },
        }));
      }
    }
  }

  const visibleListState =
    activeSurface === 'apps' || activeSurface === 'skills' || activeSurface === 'tasks' || activeSurface === 'history'
      ? surfaceLists[activeSurface]
      : null;

  const userName = accountDisplayName(snapshot);
  const userEmail = accountEmail(snapshot);
  const signedIn = authReady(snapshot);

  return (
    <div
      className={[
        'app-shell',
        isClosing ? 'app-shell--closing' : '',
        isRailOpen ? 'app-shell--rail-open' : 'app-shell--rail-closed',
        isCompactViewport ? 'app-shell--compact' : 'app-shell--desktop',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <Titlebar
        appReady={runtimeReady(snapshot)}
        systemCapabilities={systemCapabilities}
        windowState={windowState}
        onMinimize={() => void desktopApi.window.minimize()}
        onMaximize={() => {
          void desktopApi.window.maximizeOrRestore().then(setWindowState);
        }}
        onClose={() => void desktopApi.window.close()}
      />
      {signedIn ? (
        <div className="shell-grid">
          {isCompactViewport ? (
            <button
              type="button"
              className={`shell-backdrop ${isRailOpen ? 'shell-backdrop--visible' : ''}`}
              aria-label="Kenar çubuğunu kapat"
              onClick={() => setIsRailOpen(false)}
            />
          ) : null}
          <LeftRail
            snapshot={snapshot}
            logoUrl={logoUrl}
            userName={userName}
            userEmail={userEmail}
            hasTrafficLights={systemCapabilities?.windowChrome.trafficLights === true}
            activeSurface={activeSurface}
            isOpen={isRailOpen}
            isCompactViewport={isCompactViewport}
            onToggleRail={toggleRail}
            onCreateConversation={() => {
              void createConversation();
              dismissRailOnCompact();
            }}
            onOpenApps={() => {
              void openAppsSurface();
              dismissRailOnCompact();
            }}
            onOpenSkills={() => {
              void openSkillsSurface();
              dismissRailOnCompact();
            }}
            onOpenTasks={() => {
              void openTasksSurface();
              dismissRailOnCompact();
            }}
            onOpenHistory={() => {
              void openHistorySurface();
              dismissRailOnCompact();
            }}
            onOpenSettings={() => {
              setActiveSurface('settings');
              dismissRailOnCompact();
            }}
          />
          {activeSurface === 'settings' ? (
          <SettingsSurface
            snapshot={snapshot}
            systemCapabilities={systemCapabilities}
            logoUrl={logoUrl}
            onBack={() => setActiveSurface('chat')}
            onLogout={logout}
            onRefresh={refreshShell}
            onEnsureRegistered={ensureRegistered}
            onCreatePairingSession={createPairingSession}
          />
          ) : activeSurface === 'apps' || activeSurface === 'skills' || activeSurface === 'tasks' || activeSurface === 'history' ? (
            <ListSurface
              title={
                activeSurface === 'apps'
                  ? 'Uygulamalar'
                  : activeSurface === 'skills'
                    ? 'Yetenekler'
                    : activeSurface === 'tasks'
                      ? 'Görevler'
                      : 'Geçmiş'
              }
              subtitle={
                activeSurface === 'apps'
                  ? 'Runtime MCP araçları'
                  : activeSurface === 'skills'
                    ? 'Runtime yetenekleri'
                    : activeSurface === 'tasks'
                      ? 'Backend üzerinden yönlendirilen masaüstü görevleri'
                      : 'Konuşma geçmişi'
              }
              items={activeSurface === 'history' && (visibleListState?.items.length ?? 0) === 0 ? conversationItems(snapshot) : visibleListState?.items ?? []}
              loading={visibleListState?.loading ?? false}
              error={visibleListState?.error ?? ''}
              onRefresh={() => void refreshActiveList()}
              onBack={() => setActiveSurface('chat')}
              onSelectItem={
                activeSurface === 'history'
                  ? (id) => {
                      setSelectedConversationId(id);
                      setActiveSurface('chat');
                    }
                  : undefined
              }
            />
          ) : (
            <Workspace
              snapshot={snapshot}
              selectedConversationId={selectedConversationId}
              composer={composer}
              busy={busy}
              lastError={lastError}
              logoUrl={logoUrl}
              userName={userName}
              onComposerChange={setComposer}
              onSend={() => void sendComposer()}
              onConfirmPlan={(pendingPlanId, approved) => void confirmPlan(pendingPlanId, approved)}
            />
          )}
        </div>
      ) : (
        <AuthSurface
          heroImageUrl={authMascotUrl}
          authMode={authMode}
          authEmail={authEmail}
          authPassword={authPassword}
          authDisplayName={authDisplayName}
          authBusy={authBusy}
          authError={authError}
          onAuthModeChange={setAuthMode}
          onAuthEmailChange={setAuthEmail}
          onAuthPasswordChange={setAuthPassword}
          onAuthDisplayNameChange={setAuthDisplayName}
          onSubmitAuth={() => void submitAuth()}
        />
      )}
    </div>
  );
}

function mergeHydratedRuntimeResult(snapshot: BootstrapSnapshot, response: RuntimeResponse): BootstrapSnapshot {
  const result = asRecord(response.result);
  let next = applyRuntimeResult(snapshot, response);
  if (Object.keys(asRecord(result.state)).length > 0) {
    next = {
      ...next,
      state: asRecord(result.state) as BootstrapSnapshot['state'],
    };
  }
  if (Object.keys(asRecord(result.runtime)).length > 0) {
    next = withRuntime(next, result.runtime);
  }
  const backendPatch: PlainRecord = {};
  for (const key of ['authMe', 'mobileBootstrap', 'health', 'brainProfile', 'runtimeSession', 'controlPlane']) {
    const value = result[key];
    if (Object.keys(asRecord(value)).length > 0) {
      backendPatch[key] = value;
    }
  }
  if (Object.keys(backendPatch).length > 0) {
    next = withBackend(next, backendPatch);
  }
  return next;
}

function authErrorFromResponse(response: RuntimeResponse): string {
  if (response.error?.message) {
    return response.error.message;
  }
  const result = asRecord(response.result);
  if (result.ok === false) {
    const nestedResult = asRecord(result.result);
    return String(asRecord(nestedResult.error).message ?? nestedResult.error ?? 'Kimlik doğrulama tamamlanamadı.');
  }
  return '';
}

function conversationItems(snapshot: BootstrapSnapshot | null): ListSurfaceItem[] {
  return snapshotConversations(snapshot).map((conversation) => ({
    id: conversation.id,
    title: conversation.title,
    subtitle: conversation.preview,
    meta: conversation.updatedAt,
  }));
}
