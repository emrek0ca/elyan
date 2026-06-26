import { startTransition, useEffect, useRef, useState } from 'react';
import type {
  BootstrapSnapshot,
  JsonMap,
  RuntimeArtifact,
  RuntimeResponse,
  SystemCapabilities,
  WindowState,
} from '../shared/protocol';
import logoUrl from '../../logo.png';
import authMascotUrl from './assets/auth-mascot.png';
import { Titlebar } from './components/Titlebar';
import { getDesktopApi } from './desktop-api';
import { AuthSurface, type LegalAcceptance } from './panels/AuthSurface';
import { LeftRail } from './panels/LeftRail';
import { ListSurface, type ListSurfaceItem } from './panels/ListSurface';
import { SettingsSurface } from './panels/SettingsSurface';
import { Workspace } from './panels/Workspace';
import { applyBlockStreamEvent, type ElyanBlockStreamEvent } from '../shared/blocks/streaming';
import {
  accountDisplayName,
  accountId,
  accountEmail,
  accountUsageSummary,
  activeConversationId,
  applyRuntimeResult,
  asArray,
  asRecord,
  asString,
  authReady,
  chatAccessState,
  runtimePayloadReady,
  runtimeReady,
  runtimeResponseErrorCode,
  snapshotArchivedConversations,
  snapshotConversations,
  stateRecord,
  withBackend,
  withRuntime,
  type HydrationState,
  type PlainRecord,
} from './lib/data';
import { itemsFromRuntimeList } from './lib/runtime-list-items';
import { deriveDesktopTaskShell } from './lib/desktop-task-shell';

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

function fileUrlFromPath(pathValue: string): string {
  const normalized = String(pathValue || '').trim().replace(/\\/g, '/');
  if (!normalized) {
    return '';
  }
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return `file:///${encodeURI(normalized)}`;
  }
  if (normalized.startsWith('/')) {
    return `file://${encodeURI(normalized)}`;
  }
  return `file://${encodeURI(normalized)}`;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error('clipboard_file_read_failed'));
    reader.readAsDataURL(file);
  });
}

function base64FromDataUrl(dataUrl: string): string {
  return String(dataUrl || '').split(',', 2)[1] ?? '';
}

function attachmentKindFor(mimeType: string, pathValue: string): ComposerAttachment['kind'] {
  const normalizedMime = String(mimeType || '').trim().toLowerCase();
  const normalizedPath = String(pathValue || '').trim().toLowerCase();
  if (normalizedMime.startsWith('image/') || /\.(png|jpe?g|gif|webp|heic|heif|avif)$/.test(normalizedPath)) {
    return 'image';
  }
  if (normalizedMime.startsWith('audio/') || /\.(mp3|m4a|wav|flac|aac|ogg)$/.test(normalizedPath)) {
    return 'audio';
  }
  if (
    normalizedMime.startsWith('text/') ||
    normalizedMime.includes('pdf') ||
    /\.(pdf|docx?|xlsx?|pptx?|txt|md|rtf|csv|json|html?)$/.test(normalizedPath)
  ) {
    return 'document';
  }
  return 'other';
}

type AuthMode = 'login' | 'register';
type ActiveSurface = 'chat' | 'settings' | 'apps' | 'tasks' | 'archives';
type ListSurfaceKey = 'apps' | 'skills' | 'tasks' | 'archives';
type SettingsSection = 'account' | 'local' | 'cloud' | 'pairing' | 'privacy' | 'advanced' | 'theme';
type ComposerAttachment = RuntimeArtifact & { sizeBytes: number };

interface SurfaceListState {
  items: ListSurfaceItem[];
  loading: boolean;
  error: string;
}

const initialSurfaceListState = (): Record<ListSurfaceKey, SurfaceListState> => ({
  apps: { items: [], loading: false, error: '' },
  skills: { items: [], loading: false, error: '' },
  tasks: { items: [], loading: false, error: '' },
  archives: { items: [], loading: false, error: '' },
});

export function App() {
  const [snapshot, setSnapshot] = useState<BootstrapSnapshot | null>(null);
  const [systemCapabilities, setSystemCapabilities] = useState<SystemCapabilities | null>(null);
  const [windowState, setWindowState] = useState<WindowState | null>(null);
  const [isRailOpen, setIsRailOpen] = useState(true);
  const [isCompactViewport, setIsCompactViewport] = useState(false);
  const [selectedConversationId, setSelectedConversationId] = useState('');
  const [composer, setComposer] = useState('');
  const [composerAttachments, setComposerAttachments] = useState<ComposerAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [lastError, setLastError] = useState('');
  const [hydrationState, setHydrationState] = useState<HydrationState>(initialHydrationState);
  const [renameDialog, setRenameDialog] = useState<{ conversationId: string; currentTitle: string } | null>(null);
  const [renameInputValue, setRenameInputValue] = useState('');
  const [activeSurface, setActiveSurface] = useState<ActiveSurface>('chat');
  const [pendingUserMessage, setPendingUserMessage] = useState<{ text: string, attachments: ComposerAttachment[] } | null>(null);
  const [surfaceLists, setSurfaceLists] = useState<Record<ListSurfaceKey, SurfaceListState>>(initialSurfaceListState);
  const [authMode, setAuthMode] = useState<AuthMode>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authDisplayName, setAuthDisplayName] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');
  const [isClosing, setIsClosing] = useState(false);
  const [trialWelcomeOpen, setTrialWelcomeOpen] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] = useState<SettingsSection>('local');
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);
  const hydratedRef = useRef(false);
  const hydrationRetryRef = useRef(0);
  const listRequestRef = useRef(0);
  const hydrationTimerRef = useRef<number | null>(null);
  const pairingPollTimerRef = useRef<number | null>(null);
  const pairingPollSessionRef = useRef('');
  const skillsPrefetchUserRef = useRef('');

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
        setSnapshot((current) => {
          if (!current) {
            return current;
          }
          const truth = asRecord(payload);
          const backendPatch: PlainRecord = {};
          for (const key of ['authMe', 'mobileBootstrap', 'health', 'brainProfile', 'runtimeSession', 'controlPlane']) {
            const value = truth[key];
            if (Object.keys(asRecord(value)).length > 0) {
              backendPatch[key] = value;
            }
          }
          let next = current;
          if (Object.keys(backendPatch).length > 0) {
            next = withBackend(next, backendPatch);
          }
          if (Object.keys(asRecord(truth.runtime)).length > 0) {
            next = withRuntime(next, truth.runtime);
          }
          if (Object.keys(asRecord(truth.state)).length > 0) {
            next = {
              ...next,
              state: asRecord(truth.state) as BootstrapSnapshot['state'],
            };
          }
          return next;
        });
      }),
      desktopApi.subscribe('chat-block', (payload) => {
        setSnapshot((current) => (current ? applyBlockStreamPayload(current, payload) : current));
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
    const onKeyDown = (event: KeyboardEvent) => {
      const modifier = event.metaKey || event.ctrlKey;
      if (!modifier && event.key !== 'Escape') {
        return;
      }
      if (modifier && event.key === '/') {
        event.preventDefault();
        setShowShortcutHelp((current) => !current);
        return;
      }
      if (modifier && !event.altKey && !event.shiftKey) {
        const normalizedKey = event.key.toLowerCase();
        if (normalizedKey === 'b') {
          event.preventDefault();
          setIsRailOpen((current) => !current);
          return;
        }
        if (normalizedKey === 'n') {
          event.preventDefault();
          void createConversation();
          return;
        }
        if (normalizedKey === '1') {
          event.preventDefault();
          setActiveSurface('chat');
          return;
        }
        if (normalizedKey === '2') {
          event.preventDefault();
          setActiveSurface('settings');
          return;
        }
        if (normalizedKey === '3') {
          event.preventDefault();
          setActiveSurface('apps');
          return;
        }
        if (normalizedKey === '4') {
          event.preventDefault();
          void openTasksSurface();
          return;
        }
      }
      if (event.key === 'Escape') {
        setShowShortcutHelp(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [createConversation]);

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

  useEffect(() => {
    if (!authReady(snapshot)) {
      return;
    }
    const userId = accountId(snapshot);
    const accessState = chatAccessState(snapshot);
    if (!userId || !accessState.trialActive) {
      return;
    }
    const storageKey = `elyan.trial-welcome:${userId}`;
    if (window.localStorage.getItem(storageKey) === 'shown') {
      return;
    }
    window.localStorage.setItem(storageKey, 'shown');
    setTrialWelcomeOpen(true);
  }, [snapshot]);

  useEffect(() => {
    if (!authReady(snapshot)) {
      return;
    }
    const userId = accountId(snapshot);
    if (!userId || skillsPrefetchUserRef.current === userId) {
      return;
    }
    skillsPrefetchUserRef.current = userId;
    void loadRuntimeList('skills');
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
        setSelectedConversationId(explicitActiveConversationId(bootSnapshot));
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
      const truthRefresh = await desktopApi.request({ capability: 'backend.truth_refresh', payload: {} });
      setSnapshot((current) => {
        if (!current) {
          return current;
        }
        let next = current;
        if (truthRefresh.ok) {
          const truthResult = asRecord(truthRefresh.result);
          if (Object.keys(asRecord(truthResult.runtime)).length > 0) {
            next = withRuntime(next, truthResult.runtime);
          }
          if (Object.keys(asRecord(truthResult.state)).length > 0) {
            next = {
              ...next,
              state: asRecord(truthResult.state) as BootstrapSnapshot['state'],
            };
          }
          const backendPatch: PlainRecord = {};
          for (const key of ['authMe', 'mobileBootstrap', 'health', 'brainProfile', 'runtimeSession', 'controlPlane']) {
            const value = truthResult[key];
            if (Object.keys(asRecord(value)).length > 0) {
              backendPatch[key] = value;
            }
          }
          if (Object.keys(backendPatch).length > 0) {
            next = withBackend(next, backendPatch);
          }
        }
        return next;
      });
      if (truthRefresh.ok && runtimePayloadReady(asRecord(truthRefresh.result).runtime)) {
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
      scheduleHydrationRetry(runtimeResponseErrorCode(truthRefresh) || reason);
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
        setActiveSurface('chat');
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
    const hasAttachments = composerAttachments.length > 0;
    const accessState = chatAccessState(snapshot);
    if ((!text && !hasAttachments) || busy || accessState.locked) {
      return;
    }
    const selectedArtifacts = composerAttachments.map(({ sizeBytes: _sizeBytes, ...artifact }) => artifact);
    
    // Set pending message for optimistic UI update
    setPendingUserMessage({ text, attachments: composerAttachments });
    
    // Clear composer immediately
    setComposer('');
    setComposerAttachments([]);
    
    setBusy(true);
    setLastError('');
    try {
      const response = await desktopApi.request({
        capability: 'conversation.send',
        payload: {
          conversationId: selectedConversationId || explicitActiveConversationId(snapshot),
          text,
          selectedArtifacts,
        },
      });
      if (!response.ok) {
        setLastError(response.error?.message ?? 'Mesaj gönderilemedi.');
        if (['daily_quota_reached', 'weekly_quota_reached', 'upgrade_or_byok_required', 'ai_credit_limit_reached'].includes(String(response.error?.code ?? ''))) {
          await hydrateTruth('manual');
        }
        return;
      }
      const conversationId = activeConversationIdFromResponse(response);
      if (conversationId) {
        setSelectedConversationId(conversationId);
      }
      setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
    } finally {
      setPendingUserMessage(null);
      setBusy(false);
    }
  }

  async function addComposerAttachments(files: File[]) {
    const incoming = files.filter((file): file is File => file instanceof File);
    if (incoming.length === 0) {
      return;
    }
    try {
      const nextAttachments: ComposerAttachment[] = [];
      for (const file of incoming) {
        const fileWithPath = file as File & { path?: string };
        const pathValue = String(fileWithPath.path ?? '').trim();
        const mimeType = String(file.type || '').trim() || 'application/octet-stream';
        const name = String(file.name || '').trim() || 'clipboard';
        if (pathValue) {
          nextAttachments.push({
            id: crypto.randomUUID(),
            name,
            path: pathValue,
            url: fileUrlFromPath(pathValue),
            mimeType,
            kind: attachmentKindFor(mimeType, pathValue),
            sizeBytes: file.size,
          });
          continue;
        }
        const dataUrl = await readFileAsDataUrl(file);
        const dataBase64 = base64FromDataUrl(dataUrl);
        if (!dataBase64) {
          continue;
        }
        const saved = await desktopApi.attachments.saveFromBase64({
          name,
          mimeType,
          dataBase64,
        });
        nextAttachments.push({
          ...saved,
          url: saved.url ?? fileUrlFromPath(saved.path),
          kind: attachmentKindFor(saved.mimeType, saved.path),
        });
      }
      if (nextAttachments.length === 0) {
        setLastError('Panoya eklenmiş dosya alınamadı.');
        return;
      }
      setComposerAttachments((current) => [...current, ...nextAttachments]);
    } catch (error) {
      setLastError(error instanceof Error ? error.message : 'Panoya eklenmiş dosya alınamadı.');
    }
  }

  async function openPermissionSettings(_permissionKey: string, systemPermissionKey: string) {
    setSettingsInitialSection('privacy');
    setActiveSurface('settings');
    if (systemPermissionKey) {
      const opened = await desktopApi.system.openPermissionSettings(systemPermissionKey);
      if (!opened) {
        setLastError('Sistem izinleri açılamadı.');
      }
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
        setSelectedConversationId(id);
      }
    } finally {
      setBusy(false);
    }
  }

  function openRenameDialog(conversationId: string, currentTitle: string) {
    setRenameInputValue(currentTitle.trim());
    setRenameDialog({ conversationId, currentTitle: currentTitle.trim() });
  }

  async function submitRenameDialog() {
    if (!renameDialog) {
      return;
    }
    const { conversationId, currentTitle } = renameDialog;
    const nextTitle = renameInputValue.trim();
    setRenameDialog(null);
    setRenameInputValue('');
    if (!nextTitle || nextTitle === currentTitle) {
      return;
    }
    await renameConversation(conversationId, currentTitle, nextTitle);
  }

  async function renameConversation(conversationId: string, currentTitle: string, nextTitle?: string) {
    if (nextTitle === undefined) {
      openRenameDialog(conversationId, currentTitle);
      return;
    }
    if (!nextTitle || nextTitle === currentTitle.trim()) {
      return;
    }
    const nextItems = conversationStateItems(snapshot).map((item) =>
      item.id === conversationId ? { ...item, title: nextTitle! } : item,
    );
    try {
      const response = await desktopApi.request({
        capability: 'conversation.rename',
        payload: {
          conversationId,
          title: nextTitle,
        },
      });
      if (response.ok) {
        const refreshedSnapshot = await refreshBootstrapSnapshot();
        if (activeSurface === 'archives') {
          await loadRuntimeList('archives', refreshedSnapshot);
        }
        return;
      }
      const persisted = await persistConversationState(nextItems, explicitActiveConversationId(snapshot));
      if (!persisted) {
        setLastError(response.error?.message ?? 'Sohbet adı değiştirilemedi.');
      }
      const refreshedSnapshot = await refreshBootstrapSnapshot();
      if (activeSurface === 'archives') {
        await loadRuntimeList('archives', refreshedSnapshot);
      }
      return;
    } catch {
      const persisted = await persistConversationState(nextItems, explicitActiveConversationId(snapshot));
      if (!persisted) {
        setLastError('Sohbet adı değiştirilemedi.');
      }
      const refreshedSnapshot = await refreshBootstrapSnapshot();
      if (activeSurface === 'archives') {
        await loadRuntimeList('archives', refreshedSnapshot);
      }
    }
  }

  async function archiveConversation(conversationId: string, archived = true) {
    const response = await desktopApi.request({
      capability: 'conversation.archive',
      payload: {
        conversationId,
        archived,
      },
    });
    if (response.ok) {
      setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
      const nextActiveId = activeConversationIdFromResponse(response);
      setSelectedConversationId(archived ? nextActiveId : conversationId);
      if (!archived) {
        setActiveSurface('chat');
      }
      const refreshedSnapshot = await refreshBootstrapSnapshot();
      if (activeSurface === 'archives') {
        await loadRuntimeList('archives', refreshedSnapshot);
      }
      return;
    }
    const currentItems = conversationStateItems(snapshot);
    const nextItems = currentItems.map((item) => (item.id === conversationId ? { ...item, archived } : item));
    const nextActiveId = archived
      ? nextItems.find((item) => item.archived !== true && item.id !== conversationId)?.id ?? ''
      : conversationId;
    const persisted = await persistConversationState(nextItems, (nextActiveId || explicitActiveConversationId(snapshot)) as string);
    if (!persisted) {
      setLastError(response.error?.message ?? 'Sohbet arşivlenemedi.');
      return;
    }
    setSelectedConversationId((nextActiveId || conversationId) as string);
    if (!archived) {
      setActiveSurface('chat');
    }
    const refreshedSnapshot = await refreshBootstrapSnapshot();
    if (activeSurface === 'archives') {
      await loadRuntimeList('archives', refreshedSnapshot);
    }
  }

  async function deleteConversation(conversationId: string) {
    const confirmed = window.confirm('Bu sohbeti silmek istiyor musun?');
    if (!confirmed) {
      return;
    }
    const response = await desktopApi.request({
      capability: 'conversation.delete',
      payload: {
        conversationId,
      },
    });
    if (response.ok) {
      setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
      const nextActiveId = activeConversationIdFromResponse(response);
      setSelectedConversationId(nextActiveId);
      const refreshedSnapshot = await refreshBootstrapSnapshot();
      if (activeSurface === 'archives') {
        await loadRuntimeList('archives', refreshedSnapshot);
      }
      return;
    }
    setLastError(response.error?.message ?? 'Sohbet sunucudan silinemedi.');
  }

  function clearComposer() {
    setComposer('');
    setComposerAttachments([]);
  }

  async function persistConversationState(nextItems: PlainRecord[], nextActiveId: string) {
    const response = await desktopApi.request({
      capability: 'state.update',
      payload: {
        conversation: {
          items: nextItems as any,
          activeId: nextActiveId,
        },
      },
    });
    if (!response.ok) {
      setLastError(response.error?.message ?? 'Sohbet durumu kaydedilemedi.');
      return false;
    }
    await refreshBootstrapSnapshot();
    return true;
  }

  async function confirmPlan(pendingPlanId: string, approved: boolean) {
    setBusy(true);
    try {
      const response = await desktopApi.request({
        capability: 'conversation.confirm_plan',
        payload: {
          conversationId: selectedConversationId || explicitActiveConversationId(snapshot),
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

  async function submitAuth(legalAcceptance?: LegalAcceptance) {
    if (authBusy || !snapshot) {
      return;
    }
    if (
      authMode === 'register' &&
      (legalAcceptance?.termsAccepted !== true || legalAcceptance.privacyAccepted !== true)
    ) {
      setAuthError('Kayıt için kullanım koşulları ve gizlilik kabul edilmeli.');
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
          ...(authMode === 'register' && legalAcceptance
            ? {
                legalAcceptance: {
                  termsAccepted: legalAcceptance.termsAccepted,
                  privacyAccepted: legalAcceptance.privacyAccepted,
                },
              }
            : {}),
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
    setTrialWelcomeOpen(false);
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

  async function openTasksSurface() {
    setActiveSurface('tasks');
    await loadRuntimeList('tasks');
  }

  async function openArchivesSurface() {
    setActiveSurface('archives');
    await loadRuntimeList('archives');
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
    if (activeSurface === 'apps' || activeSurface === 'tasks' || activeSurface === 'archives') {
      await loadRuntimeList(activeSurface);
    }
  }

  async function loadRuntimeList(surface: ListSurfaceKey, baseSnapshot: BootstrapSnapshot | null = snapshot) {
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
          : surface === 'tasks'
            ? 'backend.tasks.list'
          : surface === 'archives'
            ? 'conversation.list_archives'
            : 'skill.list';
      const payload: JsonMap = surface === 'tasks' ? { limit: 30, hydrateDetails: true } : { refresh: false };
      const response = await desktopApi.request({ capability, payload });
      if (!response.ok) {
        if (surface === 'archives' && response.error?.code === 'UNKNOWN_CAPABILITY') {
          setSurfaceLists((current) => ({
            ...current,
            [surface]: {
              items: snapshotArchivedConversations(baseSnapshot).map((conversation) => ({
                id: conversation.id,
                title: conversation.title,
                subtitle: conversation.preview,
                meta: conversation.updatedAt,
                details: conversation.messages.length > 0 ? `${conversation.messages.length} mesaj` : '',
                status: 'arşiv',
                statusTone: 'neutral',
                badges: ['conversation', 'archive'],
              })),
              loading: false,
              error: '',
            },
          }));
          return;
        }
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
      if (baseSnapshot) {
        nextSnapshot = baseSnapshot;
      }
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
    activeSurface === 'apps' || activeSurface === 'tasks' || activeSurface === 'archives' ? surfaceLists[activeSurface] : null;

  async function executeAssignedTasks() {
    setBusy(true);
    setLastError('');
    try {
      const response = await desktopApi.request({
        capability: 'runtime.tasks.execute_assigned',
        payload: { limit: 3 },
      });
      if (!response.ok) {
        setLastError(response.error?.message ?? 'Bekleyen desktop görevleri alınamadı.');
        return;
      }
      setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
      await hydrateTruth('manual');
      if (activeSurface === 'tasks') {
        await loadRuntimeList('tasks');
      }
    } finally {
      setBusy(false);
    }
  }

  async function approveRemoteTask(taskId: string, approved: boolean) {
    if (!taskId) {
      return;
    }
    setBusy(true);
    setLastError('');
    try {
      const response = await desktopApi.request({
        capability: 'backend.tasks.approval',
        payload: { taskId, approved },
      });
      if (!response.ok) {
        setLastError(response.error?.message ?? 'Görev onayı gönderilemedi.');
        return;
      }
      setSnapshot((current) => (current ? applyRuntimeResult(current, response) : current));
      if (approved) {
        await executeAssignedTasks();
      } else {
        await hydrateTruth('manual');
      }
      if (activeSurface === 'tasks') {
        await loadRuntimeList('tasks');
      }
    } finally {
      setBusy(false);
    }
  }

  const userName = accountDisplayName(snapshot);
  const userEmail = accountEmail(snapshot);
  const signedIn = authReady(snapshot);
  const usageSummary = accountUsageSummary(snapshot);
  const accessState = chatAccessState(snapshot);
  const conversationHistory = conversationItems(snapshot);
  const taskShell = deriveDesktopTaskShell(snapshot);
  const trialEndsLabel = accessState.trialEndsAt
    ? new Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long' }).format(new Date(accessState.trialEndsAt))
    : '';

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
            historyItems={conversationHistory}
            selectedConversationId={selectedConversationId}
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
            onOpenTasks={() => {
              void openTasksSurface();
              dismissRailOnCompact();
            }}
            onOpenArchives={() => {
              void openArchivesSurface();
              dismissRailOnCompact();
            }}
            onOpenSettings={() => {
              setSettingsInitialSection('local');
              setActiveSurface('settings');
              dismissRailOnCompact();
            }}
            onSelectConversation={(conversationId) => {
              setSelectedConversationId(conversationId);
              setActiveSurface('chat');
              dismissRailOnCompact();
            }}
            onRenameConversation={(conversationId, currentTitle) => void renameConversation(conversationId, currentTitle)}
            onArchiveConversation={(conversationId) => void archiveConversation(conversationId)}
            onDeleteConversation={(conversationId) => void deleteConversation(conversationId)}
          />
          {activeSurface === 'settings' ? (
          <SettingsSurface
            snapshot={snapshot}
            systemCapabilities={systemCapabilities}
            logoUrl={logoUrl}
            initialSection={settingsInitialSection}
            onBack={() => setActiveSurface('chat')}
            onLogout={logout}
            onRefresh={refreshShell}
            onEnsureRegistered={ensureRegistered}
            onCreatePairingSession={createPairingSession}
          />
          ) : activeSurface === 'apps' || activeSurface === 'tasks' || activeSurface === 'archives' ? (
            <ListSurface
              title={
                activeSurface === 'apps'
                  ? 'Uygulamalar'
                  : activeSurface === 'tasks'
                    ? 'Desktop Görevleri'
                  : 'Arşivlenmiş Sohbetler'
              }
              subtitle={
                activeSurface === 'apps'
                  ? 'Runtime MCP araçları'
                  : activeSurface === 'tasks'
                    ? 'Mobilden backend üzerinden gelen görevler ve onaylar'
                  : 'Arşivlenmiş konuşmalar'
              }
              items={visibleListState?.items ?? []}
              loading={visibleListState?.loading ?? false}
              error={visibleListState?.error ?? ''}
              onRefresh={() => void refreshActiveList()}
              onBack={() => setActiveSurface('chat')}
              onSelectItem={
                activeSurface === 'archives'
          ? (conversationId) => {
                      setSelectedConversationId(conversationId);
                      setActiveSurface('chat');
                    }
                  : undefined
              }
              onSecondaryAction={
                activeSurface === 'tasks'
                  ? (taskId) => void approveRemoteTask(taskId, true)
                  : activeSurface === 'archives'
                    ? (conversationId) => void archiveConversation(conversationId, false)
                    : undefined
              }
              secondaryActionLabel={
                activeSurface === 'tasks'
                  ? 'Onayla'
                  : activeSurface === 'archives'
                    ? 'Arşivden çıkar'
                    : undefined
              }
              onDeleteItem={
                activeSurface === 'archives'
                  ? (conversationId) => void deleteConversation(conversationId)
                  : undefined
              }
              onRenameItem={
                activeSurface === 'archives'
                  ? (conversationId, currentTitle) => void renameConversation(conversationId, currentTitle)
                  : undefined
              }
            />
          ) : (
            <Workspace
              snapshot={snapshot}
              selectedConversationId={selectedConversationId}
              composer={composer}
              composerAttachments={composerAttachments}
              pendingUserMessage={pendingUserMessage}
              taskShell={taskShell}
              skillItems={surfaceLists.skills.items}
              busy={busy}
              lastError={lastError}
              chatLocked={accessState.locked}
              chatLockTitle={accessState.title}
              chatLockDetail={accessState.detail}
              logoUrl={logoUrl}
              userName={userName}
              onComposerChange={setComposer}
              onClearComposer={clearComposer}
              onCreateConversation={() => void createConversation()}
              onPasteFiles={(files) => void addComposerAttachments(files)}
              onRemoveComposerAttachment={(attachmentId) =>
                setComposerAttachments((current) => current.filter((attachment) => attachment.id !== attachmentId))
              }
              onSend={() => void sendComposer()}
              onConfirmPlan={(pendingPlanId, approved) => void confirmPlan(pendingPlanId, approved)}
              onOpenPermissionSettings={(permissionKey, systemPermissionKey) => void openPermissionSettings(permissionKey, systemPermissionKey)}
              onToggleShortcutHelp={() => setShowShortcutHelp((current) => !current)}
              onCreatePairingSession={createPairingSession}
              onOpenTasks={() => void openTasksSurface()}
              onExecuteAssignedTasks={() => void executeAssignedTasks()}
              onApproveTask={(taskId, approved) => void approveRemoteTask(taskId, approved)}
            />
          )}
        </div>
      ) : (
      <AuthSurface
        heroImageUrl={authMascotUrl}
        runtimeReady={snapshot !== null}
        runtimeDegraded={hydrationState.phase === 'degraded'}
        onRetryRuntime={() => void refreshShell()}
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
          onSubmitAuth={(legalAcceptance) => void submitAuth(legalAcceptance)}
        />
      )}
      {signedIn && trialWelcomeOpen ? (
        <div className="trial-welcome-overlay" role="dialog" aria-modal="true" aria-label="Hesap bilgileri">
          <div className="trial-welcome-card">
            <span className="trial-welcome-badge">{usageSummary.planLabel}</span>
            <strong>Hesap planın sunucudan alındı</strong>
            <p>
              {usageSummary.planLabel} planı için {usageSummary.tokenSummaryLabel} ve {usageSummary.billingStatusLabel} durumu yüklendi.
              {trialEndsLabel ? ` Bu plan ${trialEndsLabel} tarihine kadar geçerli.` : ''}
            </p>
            <p>
              Günlük {accessState.dailyRemaining ?? 5} ve haftalık {accessState.weeklyRemaining ?? 25} limitlerin de sunucudan eşitlendi.
            </p>
            <button type="button" onClick={() => setTrialWelcomeOpen(false)}>
              Devam et
            </button>
          </div>
        </div>
      ) : null}
      {showShortcutHelp ? (
        <div className="shortcut-help-overlay" role="dialog" aria-modal="true" aria-label="Kısayollar">
          <div className="shortcut-help-card">
            <div className="shortcut-help-card__header">
              <span className="shortcut-help-card__badge">Kısayollar</span>
              <button type="button" onClick={() => setShowShortcutHelp(false)}>
                Kapat
              </button>
            </div>
              <div className="shortcut-help-list">
              <div>
                <strong>Cmd/Ctrl + /</strong>
                <span>Bu yardım penceresi</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + N</strong>
                <span>Yeni sohbet</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + 1..4</strong>
                <span>Chat, ayarlar, uygulamalar, yetenekler</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + B</strong>
                <span>Sidebar aç / kapat</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + Enter</strong>
                <span>Mesaj gönder</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + O</strong>
                <span>Dosya ekle</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + Shift + I</strong>
                <span>Görsel ekle</span>
              </div>
              <div>
                <strong>Cmd/Ctrl + Backspace</strong>
                <span>Composer temizle</span>
              </div>
              <div>
                <strong>Esc</strong>
                <span>Menüleri kapat</span>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      {renameDialog ? (
        <div
          className="rename-dialog-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Sohbet adını değiştir"
          onClick={() => { setRenameDialog(null); setRenameInputValue(''); }}
        >
          <div className="rename-dialog-card" onClick={(e) => e.stopPropagation()}>
            <p className="rename-dialog-card__title">Sohbet adını değiştir</p>
            <input
              className="rename-dialog-card__input"
              type="text"
              value={renameInputValue}
              autoFocus
              maxLength={200}
              onChange={(e) => setRenameInputValue(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { void submitRenameDialog(); }
                if (e.key === 'Escape') { setRenameDialog(null); setRenameInputValue(''); }
              }}
            />
            <div className="rename-dialog-card__actions">
              <button type="button" onClick={() => { setRenameDialog(null); setRenameInputValue(''); }}>İptal</button>
              <button
                type="button"
                className="rename-dialog-card__confirm"
                disabled={!renameInputValue.trim() || renameInputValue.trim() === renameDialog.currentTitle}
                onClick={() => void submitRenameDialog()}
              >
                Kaydet
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function applyBlockStreamPayload(snapshot: BootstrapSnapshot, payload: unknown): BootstrapSnapshot {
  const event = asRecord(payload) as unknown as ElyanBlockStreamEvent;
  if (!['block_delta', 'block_replace', 'block_status'].includes(String(event.type || ''))) {
    return snapshot;
  }
  const state = asRecord(snapshot.state);
  const conversation = asRecord(state.conversation);
  const items = asArray(conversation.items).map(asRecord);
  let changed = false;
  const nextItems = items.map((item) => {
    const messages = asArray(item.messages).map(asRecord);
    const nextMessages = applyBlockStreamEvent(messages as any, event as ElyanBlockStreamEvent);
    if (nextMessages !== messages) {
      changed = true;
      return { ...item, messages: nextMessages };
    }
    return item;
  });
  if (!changed) {
    return snapshot;
  }
  return {
    ...snapshot,
    state: {
      ...state,
      conversation: {
        ...conversation,
        items: nextItems,
      },
    } as BootstrapSnapshot['state'],
  };
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

function explicitActiveConversationId(snapshot: BootstrapSnapshot | null): string {
  return asString(asRecord(stateRecord(snapshot).conversation).activeId).trim();
}

function conversationItems(snapshot: BootstrapSnapshot | null): ListSurfaceItem[] {
  return snapshotConversations(snapshot).map((conversation) => ({
    id: conversation.id,
    title: conversation.title,
    subtitle: conversation.preview,
    meta: conversation.updatedAt,
  }));
}

function activeConversationIdFromResponse(response: RuntimeResponse): string {
  const result = asRecord(response.result);
  const stateConversation = asRecord(asRecord(result.state).conversation);
  return String(result.conversationId ?? result.activeConversationId ?? stateConversation.activeId ?? '').trim();
}

function conversationStateItems(snapshot: BootstrapSnapshot | null): PlainRecord[] {
  const stateConversation = asRecord(stateRecord(snapshot).conversation);
  return asArray(stateConversation.items).map((item) => asRecord(item));
}
