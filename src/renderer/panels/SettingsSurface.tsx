import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { ProviderVaultStatus } from '../../shared/desktop-api';
import type { BootstrapSnapshot, JsonMap, SystemCapabilities } from '../../shared/protocol';
import { getDesktopApi } from '../desktop-api';
import {
  accountUsageSummary,
  chatAccessState,
  accountDisplayName,
  accountEmail,
  accountRecord,
  asArray,
  asBoolean,
  asRecord,
  asString,
  backendHealthRecord,
  backendRecord,
  backendResultData,
  controlPlaneRecord,
  runtimeSessionConnectionRecord,
  runtimeSessionDeviceRecord,
  runtimeSessionReadinessRecord,
  runtimeRecord,
  stateRecord,
  subscriptionRecord,
} from '../lib/data';

type SettingsSection = 'account' | 'local' | 'cloud' | 'pairing' | 'privacy' | 'advanced' | 'theme';

interface SettingsSurfaceProps {
  snapshot: BootstrapSnapshot | null;
  systemCapabilities: SystemCapabilities | null;
  logoUrl: string;
  initialSection?: SettingsSection;
  onBack: () => void;
  onLogout: () => void | Promise<void>;
  onRefresh: () => void | Promise<void>;
  onEnsureRegistered: () => void | Promise<void>;
  onCreatePairingSession: () => void | Promise<void>;
}

interface ProviderFormState {
  enabled: boolean;
  baseUrl: string;
  defaultModel: string;
  secret: string;
  binaryPath: string;
  modelPath: string;
  autoStart: boolean;
}

const desktopApi = getDesktopApi();

function iconPath(path: string) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

function formatTimestamp(value: string, fallback = 'Henüz yok') {
  const text = String(value || '').trim();
  if (!text) {
    return fallback;
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat('tr-TR', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(parsed);
}

function IconRefresh() {
  return iconPath('M15.8 4.9v3.6h-3.6l1.2-1.2a4.9 4.9 0 1 0 1.1 5l1.8.6A6.8 6.8 0 1 1 14 5.9l1.8-1Z');
}

function IconBack() {
  return iconPath('M8.4 4.6 3 10l5.4 5.4 1-1L5.7 10h10.8V8.6H5.7l4.7-4.7-1-1Z');
}

function IconAccount() {
  return iconPath('M10 3.5a3 3 0 1 1 0 6 3 3 0 0 1 0-6Zm0 7.8c3.2 0 5.8 1.6 5.8 3.6v1.1H4.2v-1.1c0-2 2.6-3.6 5.8-3.6Z');
}

function IconBrain() {
  return iconPath('M6.2 6.4a2.2 2.2 0 0 1 2.2-2.2c.7 0 1.3.3 1.7.8.4-.5 1-.8 1.7-.8a2.2 2.2 0 0 1 2.2 2.2c0 .5-.2 1-.5 1.4.6.4 1 1.1 1 1.9a2.3 2.3 0 0 1-1 1.9c.3.4.5.9.5 1.4a2.2 2.2 0 0 1-2.2 2.2c-.7 0-1.3-.3-1.7-.8-.4.5-1 .8-1.7.8A2.2 2.2 0 0 1 6.2 13c0-.5.2-1 .5-1.4a2.3 2.3 0 0 1-1-1.9c0-.8.4-1.5 1-1.9-.3-.4-.5-.9-.5-1.4Z');
}

function IconCloud() {
  return iconPath('M6.7 14.7a3 3 0 0 1-.3-6 4.2 4.2 0 0 1 7.9-1.4 2.7 2.7 0 0 1-.1 5.4H6.7Z');
}

function IconPhone() {
  return iconPath('M7 3.2h6a1.8 1.8 0 0 1 1.8 1.8V15a1.8 1.8 0 0 1-1.8 1.8H7A1.8 1.8 0 0 1 5.2 15V5A1.8 1.8 0 0 1 7 3.2Zm3 11.5a.9.9 0 1 0 0 1.8.9.9 0 0 0 0-1.8Zm-3-9.7v8.6h6V5H7Z');
}

function IconPrivacy() {
  return iconPath('M10 3.1 15.4 5v4.1c0 3.4-2 6.2-5.4 7.8-3.4-1.6-5.4-4.4-5.4-7.8V5L10 3.1Zm0 1.5L6 6v3.1c0 2.6 1.4 4.8 4 6.2 2.6-1.4 4-3.6 4-6.2V6l-4-1.4Z');
}

function IconSpark() {
  return iconPath('M9.8 2.8 11 7l4.2 1.2L11 9.4l-1.2 4.2L8.6 9.4 4.4 8.2 8.6 7l1.2-4.2Zm5 9.2.7 2.2 2.2.7-2.2.7-.7 2.2-.7-2.2-2.2-.7 2.2-.7.7-2.2Z');
}

function IconTrash() {
  return iconPath('M6.4 5h7.2l-.4 10H6.8L6.4 5Zm2.1-2h3l.5 1H15v1.4H5V4h3l.5-1Z');
}

function IconCheck() {
  return iconPath('M7.9 13.4 4.8 10.3l1-1 2.1 2.1 5-5 1 1-6 6Z');
}

function IconOpenExternal() {
  return iconPath('M10.7 4h5.3v5.3h-1.4V6.4l-6.1 6.1-1-1 6.1-6.1h-2.9V4ZM5 5h4v1.4H6.4v7.2h7.2V11H15v4H5V5Z');
}

function IconTheme() {
  return iconPath('M10 2c-4.4 0-8 3.6-8 8s3.6 8 8 8c.7 0 1.3-.6 1.3-1.3 0-.3-.1-.6-.3-.9-.2-.2-.3-.5-.3-.9 0-.8.6-1.4 1.4-1.4h1.5c2.4 0 4.4-2 4.4-4.4 0-4-3.6-7.1-8-7.1zm-3.5 8c-.8 0-1.5-.7-1.5-1.5S5.7 7 6.5 7 8 7.7 8 8.5 7.3 10 6.5 10zm2-4c-.8 0-1.5-.7-1.5-1.5S7.7 3 8.5 3 10 3.7 10 4.5 9.3 6 8.5 6zm3 0c-.8 0-1.5-.7-1.5-1.5S10.7 3 11.5 3 13 3.7 13 4.5 12.3 6 11.5 6zm2 4c-.8 0-1.5-.7-1.5-1.5S12.7 7 13.5 7 15 7.7 15 8.5 14.3 10 13.5 10z');
}

function boolLabel(value: boolean | null): string {
  if (value === true) {
    return 'Açık';
  }
  if (value === false) {
    return 'Kapalı';
  }
  return 'Bilinmiyor';
}

function safeStorageGet(key: string, fallback: string): string {
  try {
    if (typeof window === 'undefined') {
      return fallback;
    }
    const storage = window.localStorage;
    if (!storage || typeof storage.getItem !== 'function') {
      return fallback;
    }
    return storage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function safeStorageSet(key: string, value: string): void {
  try {
    if (typeof window === 'undefined') {
      return;
    }
    const storage = window.localStorage;
    if (!storage || typeof storage.setItem !== 'function') {
      return;
    }
    storage.setItem(key, value);
  } catch {
    return;
  }
}

const MANAGED_PERMISSION_KEYS = [
  'allow_browser_control',
  'allow_screen_analysis',
  'allow_computer_control',
  'allow_sensitive_operator_actions',
  'allow_file_indexing',
  'allow_system_inspection',
  'allow_personal_actions',
  'allow_shell',
  'allow_destructive_tools',
] as const;

type ManagedPermissionKey = (typeof MANAGED_PERMISSION_KEYS)[number];

type PermissionDescriptor = {
  key: ManagedPermissionKey;
  title: string;
  hint: string;
  systemPermission?: 'accessibility' | 'screenRecording' | 'inputMonitoring' | 'automation';
};

const PERMISSION_ITEMS: PermissionDescriptor[] = [
  {
    key: 'allow_browser_control',
    title: 'Tarayıcı ve medya kontrolü',
    hint: 'Tarayıcı açma, arama başlatma ve medya oynatma gibi yerel işlemleri çalıştırır.',
    systemPermission: 'accessibility',
  },
  {
    key: 'allow_screen_analysis',
    title: 'Ekran okuma',
    hint: 'Aktif ekranı ve pencere içeriğini yorumlar.',
    systemPermission: 'screenRecording',
  },
  {
    key: 'allow_computer_control',
    title: 'Bilgisayar kontrolü',
    hint: 'Tıklama, yazma, kaydırma ve pencere odaklama gibi operator aksiyonlarını açar.',
    systemPermission: 'accessibility',
  },
  {
    key: 'allow_sensitive_operator_actions',
    title: 'Riskli operator aksiyonları',
    hint: 'Gönderme, silme, ödeme ve dosya yükleme gibi geri alınamaz aksiyonlar için ek katmanı açar.',
    systemPermission: 'automation',
  },
  {
    key: 'allow_file_indexing',
    title: 'Dosya kullanımı',
    hint: 'Kendi dosyalarına erişim izni olmadan işlem yapılmaz.',
  },
  {
    key: 'allow_system_inspection',
    title: 'Sistem görünürlüğü',
    hint: 'Açık uygulamalar ve aktif pencere üzerinde güvenli görünürlük sağlar.',
    systemPermission: 'accessibility',
  },
  {
    key: 'allow_personal_actions',
    title: 'Kişisel eylemler',
    hint: 'Takvim, hatırlatıcı ve mesaj gibi kişisel işlemleri yürütür.',
  },
  {
    key: 'allow_shell',
    title: 'Gelişmiş komutlar',
    hint: 'Terminal komutları gibi güçlü yerel aksiyonları açar.',
  },
  {
    key: 'allow_destructive_tools',
    title: 'Silme ve geri alınamaz işlemler',
    hint: 'Gönderme, silme ve geri alınamaz güçlü işlemleri etkinleştirir.',
  },
];

function permissionStatusLabel(value: boolean): string {
  return value ? 'Açık' : 'Kapalı';
}

function systemPermissionLabel(value: unknown): string {
  const record = asRecord(value);
  const status = asString(record.status).trim().toLowerCase();
  const source = asString(record.source).trim().toLowerCase();
  if (status === 'granted' || status === 'not_required') {
    return 'Hazır';
  }
  if (status === 'required' || status === 'denied') {
    return 'Sistem izni gerekli';
  }
  if (source.includes('unavailable') || source.includes('manual') || source.includes('not_probed')) {
    return 'Manuel kontrol gerekli';
  }
  return 'Bilinmiyor';
}

function localRuntimeErrorMessage(raw: unknown): string {
  const value = asString(raw).trim();
  if (!value) {
    return '';
  }
  if (value === 'model_required') {
    return 'Önce bir model seç.';
  }
  if (value === 'LOCAL_MODEL_NOT_CONFIGURED' || value === 'local_model_not_configured' || value === 'local_model_not_selected') {
    return 'Kurulum tamamlanmadı.';
  }
  if (
    value === 'LOCAL_MODEL_UNREACHABLE' ||
    value === 'provider_unreachable' ||
    value === 'ollama_client_unavailable' ||
    value === 'lmstudio_client_unavailable' ||
    value === 'llamacpp_client_unavailable'
  ) {
    return 'Şu anda ulaşılamıyor.';
  }
  if (value === 'LOCAL_MODEL_TIMEOUT' || value === 'request_timeout') {
    return 'Yanıt vermesi uzun sürüyor.';
  }
  if (value === 'LOCAL_MODEL_BINARY_MISSING' || value === 'ollama_binary_missing') {
    return 'Bilgisayarda bulunamadı.';
  }
  if (value === 'llamacpp_binary_missing' || value === 'llamacpp_model_missing') {
    return 'Kurulum tamamlanmadı.';
  }
  if (value === 'managed_download_only_supported_for_ollama') {
    return 'Bu indirme yolu yalnız Ollama ile çalışır.';
  }
  if (value === 'invalid_response') {
    return 'Anlaşılamayan bir yanıt geldi.';
  }
  return 'İşlem tamamlanamadı.';
}

function providerStatusLabel(item: Record<string, unknown>): string {
  const displayStatus = asString(item.displayStatus);
  if (displayStatus) {
    return displayStatus;
  }
  if (item.secretConfigured === true) {
    return 'Bağlı';
  }
  if (item.configured === true) {
    return 'Hazır';
  }
  return 'Bağlı değil';
}

function providerHint(item: Record<string, unknown>): string {
  const displayHint = asString(item.displayHint);
  if (displayHint) {
    return displayHint;
  }
  if (item.secretConfigured === true) {
    return 'Kullanıma hazır.';
  }
  return 'Bağlantı anahtarı ekleyebilirsin.';
}

function providerCatalogPayload(value: unknown): Record<string, unknown> {
  const direct = asRecord(value);
  const nested = asRecord(direct.result);
  return Object.keys(nested).length > 0 ? nested : direct;
}

function readModelNames(models: unknown): string[] {
  return asArray(models)
    .map((item) => {
      const record = asRecord(item);
      return asString(record.name || record.id).trim();
    })
    .filter(Boolean);
}

async function readFileAsBase64(file: File): Promise<{ mimeType: string; dataBase64: string }> {
  const dataUrl = await readFileAsDataUrl(file);
  const [prefix, data] = dataUrl.split(',', 2);
  const mimeType = (prefix ?? '').match(/data:(.*?);base64/)?.[1] ?? file.type;
  return { mimeType, dataBase64: data ?? '' };
}

async function readFileAsDataUrl(file: File): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error('avatar_read_failed'));
    reader.readAsDataURL(file);
  });
  return dataUrl;
}

function avatarFailureMessage(code: unknown): string {
  const value = asString(code).trim().toUpperCase();
  if (value === 'RUNTIME_NOT_READY' || value === 'RUNTIME_UNAVAILABLE' || value === 'PREVIEW_BRIDGE_UNAVAILABLE') {
    return 'Profil fotoğrafı şu anda yüklenemiyor. Birkaç saniye sonra tekrar dene.';
  }
  return 'Profil fotoğrafı güncellenemedi.';
}

async function requestAvatarMutation(
  capability: 'backend.auth_avatar_upload' | 'backend.auth_avatar_delete',
  payload: JsonMap,
) {
  let response = await desktopApi.request({ capability, payload });
  if (!response.ok && (response.error?.code === 'RUNTIME_NOT_READY' || response.error?.code === 'RUNTIME_UNAVAILABLE')) {
    await new Promise((resolve) => window.setTimeout(resolve, 700));
    response = await desktopApi.request({ capability, payload });
  }
  return response;
}

function InlineField({
  label,
  value,
  onChange,
  placeholder = '',
  type = 'text',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: 'text' | 'password';
}) {
  return (
    <label className="settings-inline-field">
      <span>{label}</span>
      <input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function ListSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="settings-list-section">
      <header className="settings-list-section__header">
        <strong>{title}</strong>
      </header>
      <div className="settings-list">{children}</div>
    </section>
  );
}

function ListItem({
  title,
  hint,
  status = '',
  actions,
  children,
}: {
  title: ReactNode;
  hint?: string;
  status?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="settings-list-item">
      <div className="settings-list-item__main">
        <div className="settings-list-item__copy">
          <strong>{title}</strong>
        </div>
        <div className="settings-list-item__side">
          {status ? <i>{status}</i> : null}
          {actions ? <div className="settings-inline-actions">{actions}</div> : null}
        </div>
      </div>
      {children ? <div className="settings-list-item__detail">{children}</div> : null}
    </div>
  );
}

export function SettingsSurface({
  snapshot,
  systemCapabilities,
  logoUrl,
  initialSection = 'local',
  onBack,
  onLogout,
  onRefresh,
  onEnsureRegistered,
  onCreatePairingSession,
}: SettingsSurfaceProps) {
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialSection);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busyKey, setBusyKey] = useState('');
  const [avatarPreview, setAvatarPreview] = useState('');
  const [displayNameInput, setDisplayNameInput] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [nextPassword, setNextPassword] = useState('');
  const [providerCatalog, setProviderCatalog] = useState<Record<string, unknown> | null>(null);
  const [vaultStatus, setVaultStatus] = useState<ProviderVaultStatus | null>(null);
  const [providerForms, setProviderForms] = useState<Record<string, ProviderFormState>>({});
  const [localModelDraft, setLocalModelDraft] = useState('');
  const [expandedCloudProvider, setExpandedCloudProvider] = useState<string | null>(null);
  const [expandedAdvancedProvider, setExpandedAdvancedProvider] = useState<string | null>(null);
  const [expandedPermissionsDrawer, setExpandedPermissionsDrawer] = useState(false);
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [showProfileForm, setShowProfileForm] = useState(false);
  const [showModelComposer, setShowModelComposer] = useState(false);
  const [persistedAvatarPreview, setPersistedAvatarPreview] = useState('');

  const [activeTheme, setActiveTheme] = useState(() => safeStorageGet('elyan-theme', 'elyan'));
  const [uiScale, setUiScale] = useState(() => safeStorageGet('elyan-ui-scale', '1'));
  const [ambientOpacity, setAmbientOpacity] = useState(() => safeStorageGet('elyan-ambient-opacity', '1'));
  const [baseRadius, setBaseRadius] = useState(() => safeStorageGet('elyan-base-radius', '16px'));

  const account = accountRecord(snapshot);
  const displayName = accountDisplayName(snapshot);
  const email = accountEmail(snapshot);
  const runtime = runtimeRecord(snapshot);
  const pairing = asRecord(stateRecord(snapshot).pairing);
  const controlPlane = controlPlaneRecord(snapshot);
  const authMe = asRecord(controlPlane.authMe);
  const runtimeReadiness = runtimeSessionReadinessRecord(snapshot);
  const runtimeConnection = runtimeSessionConnectionRecord(snapshot);
  const runtimeDevice = runtimeSessionDeviceRecord(snapshot);

  const subscription = subscriptionRecord(snapshot);
  const rawPlanCode = asString(subscription.planCode).trim().toLowerCase();
  const planCode = rawPlanCode === 'team' ? 'pro' : rawPlanCode;

  const targetStatus = asString(runtime.targetStatus);
  const targetErrorCode = asString(runtime.targetErrorCode);
  const isPlanRestricted = targetStatus === 'plan_restricted' || targetErrorCode === 'desktop_plan_required' || targetErrorCode === 'desktop_limit_reached';

  const providerItems = useMemo(() => asArray(providerCatalog?.providers), [providerCatalog]);
  const cloudProviderItems = useMemo(() => asArray(providerCatalog?.cloudProviders), [providerCatalog]);
  const advancedProviderItems = useMemo(() => asArray(providerCatalog?.advancedProviders), [providerCatalog]);
  const localModels = asRecord(providerCatalog?.localModels);
  const localSummary = asRecord(localModels.summary);
  const localModelStatus = asRecord(localModels.status);
  const localModelPayload = asRecord(localModels.models);
  const localModelEntries = useMemo(() => asArray(localModelPayload.models), [localModelPayload.models]);
  const localModelJobs = useMemo(() => asArray(localModels.jobs), [localModels.jobs]);
  const selectedRuntime = asString(providerCatalog?.defaultLocalRuntime || localModels.selectedRuntime, 'ollama');
  const recommendedLocalModels = useMemo(
    () => {
      const models = asArray(localModels.recommendedModels).map((item) => asString(item).trim()).filter(Boolean);
      return models.length > 0 ? models : ['llama3.1:8b', 'qwen2.5:7b', 'deepseek-r1:8b', 'mistral:7b'];
    },
    [localModels.recommendedModels],
  );
  const localProviders = useMemo(
    () => providerItems.filter((item) => ['ollama', 'lmstudio', 'llamacpp'].includes(asString(asRecord(item).id))),
    [providerItems],
  );
  const health = backendHealthRecord(snapshot);
  const networkInfo = asRecord(health.network);
  const externalReachability = networkInfo.externalClientsCanReachAdvertisedBaseUrl;
  const isNetworkReady = externalReachability === true;
  const runtimeReady = runtimeReadiness.canReceiveTasks === true && isNetworkReady;
  const qrDataUrl = asString(pairing.qrDataUrl);
  const manualEntryCode = asString(pairing.manualEntryCode || pairing.qrText);
  const accessState = chatAccessState(snapshot);
  const usageSummary = accountUsageSummary(snapshot);
  const permissionsState = asRecord(stateRecord(snapshot).permissions);
  const nativePermissions = systemCapabilities?.nativeDesktop.permissions ?? null;

  useEffect(() => {
    setActiveSection(initialSection);
  }, [initialSection]);

  useEffect(() => {
    setDisplayNameInput(displayName);
  }, [displayName]);

  useEffect(() => {
    void refreshCatalog();
    void loadVaultStatus();
  }, []);

  useEffect(() => {
    const hasAvatar = Boolean(account.hasAvatar);
    if (!hasAvatar) {
      setAvatarPreview('');
      setPersistedAvatarPreview('');
      return;
    }
    void loadAvatar();
  }, [account.hasAvatar, account.avatarVersion]);

  async function withBusy<T>(key: string, fn: () => Promise<T>): Promise<T | undefined> {
    setBusyKey(key);
    setNotice('');
    setError('');
    try {
      return await fn();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'İşlem tamamlanamadı.');
      return undefined;
    } finally {
      setBusyKey('');
    }
  }

  const clearHistory = async () => {
    await withBusy('clear-history', async () => {
      const response = await desktopApi.request({
        capability: 'conversation.clear_history',
        payload: {},
      });
      if (!response.ok) {
        setError(response.error?.message ?? 'Geçmiş sunucudan temizlenemedi.');
        return;
      }
      await onRefresh();
      setNotice('Geçmiş temizlendi.');
      setError('');
    });
  };

  async function refreshCatalog() {
    const response = await desktopApi.request({ capability: 'providers.catalog', payload: {} });
    if (!response.ok) {
      setError(response.error?.message ?? 'Ayarlar alınamadı.');
      return;
    }
    const result = providerCatalogPayload(response.result);
    setProviderCatalog(result);
    const nextForms: Record<string, ProviderFormState> = {};
    for (const item of asArray(result.providers)) {
      const record = asRecord(item);
      const providerId = asString(record.id);
      nextForms[providerId] = {
        enabled: record.enabled === true,
        baseUrl: '',
        defaultModel: asString(record.defaultModel),
        secret: '',
        binaryPath: asString(record.binaryPath),
        modelPath: asString(record.modelPath),
        autoStart: record.autoStart === true,
      };
    }
    setProviderForms((current) => {
      const merged = { ...nextForms };
      for (const [key, value] of Object.entries(current)) {
        merged[key] = {
          ...(nextForms[key] ?? {
            enabled: false,
            baseUrl: '',
            defaultModel: '',
            secret: '',
            binaryPath: '',
            modelPath: '',
            autoStart: false,
          }),
          secret: value.secret || '',
        };
      }
      return merged;
    });
  }

  async function loadVaultStatus() {
    setVaultStatus(await desktopApi.providers.getVaultStatus());
  }

  async function loadAvatar() {
    const response = await desktopApi.request({ capability: 'backend.auth_avatar_get', payload: {} });
    if (!response.ok) {
      return;
    }
    const result = asRecord(response.result);
    const payload = asRecord(result.result);
    const data = asRecord(payload.data);
    const mimeType = asString(data.mimeType, 'image/png');
    const dataBase64 = asString(data.dataBase64);
    if (dataBase64) {
      const nextPreview = `data:${mimeType};base64,${dataBase64}`;
      setPersistedAvatarPreview(nextPreview);
      setAvatarPreview(nextPreview);
    }
  }

  function formStateFor(providerId: string): ProviderFormState {
    return (
      providerForms[providerId] ?? {
        enabled: false,
        baseUrl: '',
        defaultModel: '',
        secret: '',
        binaryPath: '',
        modelPath: '',
        autoStart: false,
      }
    );
  }

  function updateProviderForm(providerId: string, patch: Partial<ProviderFormState>) {
    setProviderForms((current) => ({
      ...current,
      [providerId]: {
        ...formStateFor(providerId),
        ...current[providerId],
        ...patch,
      },
    }));
  }

  async function saveProfile() {
    await withBusy('profile', async () => {
      const response = await desktopApi.request({
        capability: 'backend.auth_update_profile',
        payload: { displayName: displayNameInput.trim() },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Ad güncellenemedi.');
      }
      setNotice('Hesap adı güncellendi.');
      setShowProfileForm(false);
      await Promise.resolve(onRefresh());
    });
  }

  async function changePassword() {
    await withBusy('password', async () => {
      const response = await desktopApi.request({
        capability: 'backend.auth_change_password',
        payload: { currentPassword, nextPassword },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Şifre değiştirilemedi.');
      }
      setCurrentPassword('');
      setNextPassword('');
      setShowPasswordForm(false);
      setNotice('Şifre güncellendi.');
    });
  }

  async function uploadAvatar(file: File | null) {
    if (!file) {
      return;
    }
    await withBusy('avatar-upload', async () => {
      const dataUrl = await readFileAsDataUrl(file);
      setAvatarPreview(dataUrl);
      const payload = await readFileAsBase64(file);
      const response = await requestAvatarMutation('backend.auth_avatar_upload', payload);
      if (!response.ok) {
        setAvatarPreview(persistedAvatarPreview);
        throw new Error(avatarFailureMessage(response.error?.code));
      }
      await Promise.resolve(onRefresh());
      await loadAvatar();
      setNotice('Profil fotoğrafı güncellendi.');
    });
  }

  async function removeAvatar() {
    await withBusy('avatar-delete', async () => {
      const response = await requestAvatarMutation('backend.auth_avatar_delete', {});
      if (!response.ok) {
        throw new Error(avatarFailureMessage(response.error?.code));
      }
      setPersistedAvatarPreview('');
      setAvatarPreview('');
      await Promise.resolve(onRefresh());
      setNotice('Profil fotoğrafı kaldırıldı.');
    });
  }

  async function saveProvider(providerId: string) {
    const form = formStateFor(providerId);
    await withBusy(`provider-save-${providerId}`, async () => {
      if (form.secret.trim()) {
        await desktopApi.providers.saveSecret({ providerId, secret: form.secret.trim() });
        updateProviderForm(providerId, { secret: '' });
      }
      const response = await desktopApi.request({
        capability: 'providers.update_config',
        payload: {
          providerId,
          enabled: form.enabled,
          defaultModel: form.defaultModel,
          binaryPath: form.binaryPath,
          modelPath: form.modelPath,
          autoStart: form.autoStart,
          ...(form.baseUrl.trim() ? { baseUrl: form.baseUrl.trim() } : {}),
        },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Kaydedilemedi.');
      }
      await loadVaultStatus();
      await refreshCatalog();
      setNotice('Ayar kaydedildi.');
    });
  }

  async function validateProvider(providerId: string) {
    await withBusy(`provider-validate-${providerId}`, async () => {
      const response = await desktopApi.request({
        capability: 'providers.validate',
        payload: { providerId },
      });
      await refreshCatalog();
      if (!response.ok) {
        const result = asRecord(response.result);
        throw new Error(localRuntimeErrorMessage(response.error?.code ?? result.error ?? response.error?.message));
      }
      const result = asRecord(response.result);
      const modelNames = readModelNames(result.models);
      setNotice(modelNames.length > 0 ? `${providerId} hazır. ${modelNames[0]} bulundu.` : `${providerId} hazır.`);
    });
  }

  async function removeProviderSecret(providerId: string) {
    await withBusy(`provider-secret-${providerId}`, async () => {
      await desktopApi.providers.removeSecret(providerId);
      await loadVaultStatus();
      await refreshCatalog();
      setNotice('Bağlantı anahtarı kaldırıldı.');
    });
  }

  async function switchLocalRuntime(runtimeId: string) {
    await withBusy(`runtime-${runtimeId}`, async () => {
      const response = await desktopApi.request({
        capability: 'providers.update_config',
        payload: {
          defaultLocalRuntime: runtimeId,
          providerId: 'local',
          runtimeFamily: runtimeId,
        },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Bu seçenek kullanılamadı.');
      }
      await refreshCatalog();
      setNotice('Yerel model seçimi güncellendi.');
    });
  }

  async function setLocalDefaultModel(model: string) {
    await withBusy('local-default-model', async () => {
      const response = await desktopApi.request({
        capability: 'local_models.set_default',
        payload: { model },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Model seçilemedi.');
      }
      await refreshCatalog();
      setNotice('Ana model seçildi.');
    });
  }

  async function pullLocalModel(modelName?: string) {
    const model = (modelName ?? localModelDraft).trim();
    if (!model) {
      setError('Model adı gerekli.');
      return;
    }
    await withBusy(`local-model-download-${model}`, async () => {
      const response = await desktopApi.request({
        capability: 'local_models.download',
        payload: { model },
      });
      if (!response.ok) {
        throw new Error(localRuntimeErrorMessage(response.error?.code ?? response.error?.message));
      }
      setLocalModelDraft('');
      setShowModelComposer(false);
      await refreshCatalog();
      setNotice('Model indirme işi başlatıldı.');
    });
  }

  async function removeLocalModel(model: string) {
    await withBusy(`local-model-remove-${model}`, async () => {
      const response = await desktopApi.request({
        capability: 'local_models.remove',
        payload: { model },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Model kaldırılamadı.');
      }
      await refreshCatalog();
      setNotice('Model kaldırma işi başlatıldı.');
    });
  }

  async function cancelLocalJob(jobId: string) {
    await withBusy(`local-job-cancel-${jobId}`, async () => {
      const response = await desktopApi.request({
        capability: 'local_models.cancel',
        payload: { jobId },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'İş iptal edilemedi.');
      }
      await refreshCatalog();
      setNotice('İndirme işi durduruldu.');
    });
  }

  async function startLocalRuntime(providerId: string) {
    await withBusy(`local-runtime-start-${providerId}`, async () => {
      const response = await desktopApi.request({
        capability: 'local_models.start',
        payload: { providerId },
      });
      if (!response.ok) {
        throw new Error(localRuntimeErrorMessage(response.error?.code ?? response.error?.message));
      }
      await refreshCatalog();
      setNotice('Yerel model açılıyor.');
    });
  }

  async function createPairing() {
    await withBusy('pairing', async () => {
      await Promise.resolve(onCreatePairingSession());
      await Promise.resolve(onRefresh());
    });
  }

  async function copyPairingValue(value: string, noticeText: string) {
    const text = value.trim();
    if (!text) {
      setError('Kopyalanacak eşleştirme verisi hazır değil.');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setError('');
      setNotice(noticeText);
    } catch {
      setError('Eşleştirme kodu kopyalanamadı.');
    }
  }

  async function saveFallbackToCloud(nextValue: boolean) {
    await withBusy('fallback-to-cloud', async () => {
      const response = await desktopApi.request({
        capability: 'providers.update_config',
        payload: { fallbackToCloud: nextValue },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Ayar güncellenemedi.');
      }
      await refreshCatalog();
      setNotice('Bulut kullanım ayarı güncellendi.');
    });
  }

  async function savePrivacySettings(
    key: 'localDataStaysLocal' | 'analytics' | 'redactCrashReports' | 'permissionHistory',
    value: boolean,
  ) {
    await withBusy(`privacy-${key}`, async () => {
      const response = await desktopApi.request({
        capability: 'state.update',
        payload: {
          privacy: {
            [key]: value,
          },
        },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Gizlilik ayarı güncellenemedi.');
      }
      setNotice('Gizlilik ayarı güncellendi.');
      await Promise.resolve(onRefresh());
    });
  }

  async function savePermissionState(nextPermissions: Partial<Record<ManagedPermissionKey, boolean>>) {
    const current = Object.fromEntries(
      MANAGED_PERMISSION_KEYS.map((key) => [key, asBoolean(permissionsState[key])]),
    ) as Record<ManagedPermissionKey, boolean>;
    const merged = {
      ...current,
      ...nextPermissions,
    };
    const dangerousAreaEnabled = MANAGED_PERMISSION_KEYS.some((key) => merged[key] === true);
    await withBusy('privacy-permissions', async () => {
      const response = await desktopApi.request({
        capability: 'state.update',
        payload: {
          account: {
            dangerousAreaEnabled,
          },
          permissions: merged,
        },
      });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'İzin ayarı güncellenemedi.');
      }
      setNotice('İzin ayarı güncellendi.');
      await Promise.resolve(onRefresh());
    });
  }

  async function saveMasterPermissions(nextValue: boolean) {
    const nextPermissions = Object.fromEntries(
      MANAGED_PERMISSION_KEYS.map((key) => [key, nextValue]),
    ) as Record<ManagedPermissionKey, boolean>;
    await savePermissionState(nextPermissions);
  }

  async function openSystemPermissionSettings(permission: NonNullable<PermissionDescriptor['systemPermission']>) {
    await withBusy(`open-system-permission-${permission}`, async () => {
      const opened = await desktopApi.system.openPermissionSettings(permission);
      if (!opened) {
        throw new Error('Sistem izinleri açılamadı.');
      }
      setNotice('Sistem izinleri ekranı açıldı.');
    });
  }

  async function deleteAccount() {
    if (!window.confirm('Hesap kalıcı olarak silinecek. Devam edilsin mi?')) {
      return;
    }
    await withBusy('delete-account', async () => {
      const response = await desktopApi.request({ capability: 'backend.auth_delete_account', payload: {} });
      if (!response.ok) {
        throw new Error(response.error?.message ?? 'Hesap silinemedi.');
      }
      setNotice('Hesap silindi.');
      await Promise.resolve(onRefresh());
      onLogout();
    });
  }

  const sections: Array<{ id: SettingsSection; label: string; icon: ReactNode }> = [
    { id: 'local', label: 'Yerel Modeller', icon: <IconBrain /> },
    { id: 'cloud', label: 'Bulut Modeller', icon: <IconCloud /> },
    { id: 'account', label: 'Hesap', icon: <IconAccount /> },
    { id: 'pairing' as const, label: 'Telefon Bağlantısı', icon: <IconPhone /> },
    { id: 'privacy', label: 'Gizlilik', icon: <IconPrivacy /> },
    { id: 'theme', label: 'Tema', icon: <IconTheme /> },
    { id: 'advanced', label: 'Gelişmiş', icon: <IconSpark /> },
  ];

  return (
    <main className="settings-workspace" aria-label="Elyan ayarlar">
      <header className="settings-header">
        <div className="settings-header__title">
          <img src={logoUrl} alt="" aria-hidden="true" />
          <div>
            <strong>Ayarlar</strong>
            <span>{displayName}</span>
          </div>
        </div>
        <div className="settings-header__actions">
          <button type="button" className="button-secondary" onClick={() => void onRefresh()}>
            <IconRefresh />
            Yenile
          </button>
          <button type="button" className="button-secondary" onClick={onBack}>
            <IconBack />
            Sohbete dön
          </button>
        </div>
      </header>

      <div className="settings-frame">
        <nav className="settings-nav" aria-label="Ayar bölümleri">
          {sections.map((section) => (
            <button
              key={section.id}
              type="button"
              className={`settings-nav__item ${activeSection === section.id ? 'settings-nav__item--active' : ''}`}
              onClick={() => setActiveSection(section.id)}
            >
              {section.icon}
              <span>{section.label}</span>
            </button>
          ))}
        </nav>

        <section className="settings-panel">
          {notice ? <div className="settings-banner settings-banner--success">{notice}</div> : null}
          {error ? <div className="settings-banner settings-banner--danger">{error}</div> : null}

          {activeSection === 'local' ? (
            <div className="settings-section">
              <ListSection title="Yerel modeller">
                <ListItem
                  title="Şu an kullanılan yol"
                  hint={asString(localSummary.hint) || 'Yerel model seçimini buradan değiştirebilirsin.'}
                  status={asString(localSummary.status) || providerStatusLabel(asRecord(localProviders[0]))}
                />
                {localProviders.map((item) => {
                  const record = asRecord(item);
                  const providerId = asString(record.id);
                  const form = formStateFor(providerId);
                  const runtimeStatus = asRecord(record.runtimeStatus);
                  const canStart =
                    providerId === 'ollama'
                      ? asString(runtimeStatus.binary) !== '' && runtimeStatus.reachable !== true
                      : providerId === 'llamacpp' &&
                        runtimeStatus.reachable !== true &&
                        Boolean(form.binaryPath.trim()) &&
                        Boolean(form.modelPath.trim());
                  return (
                    <ListItem
                      key={providerId}
                      title={asString(record.label)}
                      hint={providerHint(record)}
                      status={providerId === selectedRuntime ? 'Kullanılıyor' : providerStatusLabel(record)}
                      actions={
                        <>
                          {providerId !== selectedRuntime ? (
                            <button type="button" className="button-secondary" onClick={() => void switchLocalRuntime(providerId)}>
                              Kullan
                            </button>
                          ) : null}
                          <button type="button" className="button-secondary" onClick={() => void validateProvider(providerId)} disabled={busyKey === `provider-validate-${providerId}`}>
                            Kontrol et
                          </button>
                          {canStart ? (
                            <button type="button" className="button-secondary" onClick={() => void startLocalRuntime(providerId)} disabled={busyKey === `local-runtime-start-${providerId}`}>
                              Aç
                            </button>
                          ) : null}
                        </>
                      }
                    />
                  );
                })}
                {selectedRuntime === 'ollama' ? (
                  <>
                    <ListItem
                      title="Önerilen modeller"
                      hint="Tek tuşla indirip deneyebilirsin."
                      status={showModelComposer ? 'Açık' : ''}
                      actions={
                        <button type="button" className="button-secondary" onClick={() => setShowModelComposer((current) => !current)}>
                          Model indir
                        </button>
                      }
                    >
                      {showModelComposer ? (
                        <div className="settings-inline-stack">
                          <div className="settings-chip-list">
                            {recommendedLocalModels.map((modelName) => (
                              <button
                                key={modelName}
                                type="button"
                                className="settings-chip-button"
                                onClick={() => void pullLocalModel(modelName)}
                                disabled={busyKey === `local-model-download-${modelName}`}
                              >
                                {modelName}
                              </button>
                            ))}
                          </div>
                          <div className="settings-inline-editor">
                            <InlineField
                              label="Başka model adı"
                              value={localModelDraft}
                              placeholder="örnek: llama3.1:8b"
                              onChange={setLocalModelDraft}
                            />
                            <div className="settings-inline-actions">
                              <button type="button" onClick={() => void pullLocalModel()} disabled={busyKey === 'local-model-download'}>
                                İndir
                              </button>
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </ListItem>
                    {localModelEntries.map((model) => {
                      const record = asRecord(model);
                      const modelName = asString(record.name || record.id);
                      if (!modelName) {
                        return null;
                      }
                      const isDefault = modelName === asString(localModels.defaultLocalModel || formStateFor(selectedRuntime).defaultModel);
                      return (
                        <ListItem
                          key={modelName}
                          title={modelName}
                          hint={isDefault ? 'Bu model hazır.' : 'İstersen ana model yapabilirsin.'}
                          status={isDefault ? 'Seçili' : 'Hazır'}
                          actions={
                            <>
                              {!isDefault ? (
                                <button type="button" className="button-secondary" onClick={() => void setLocalDefaultModel(modelName)}>
                                  Kullan
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={() => void removeLocalModel(modelName)}
                                disabled={busyKey === `local-model-remove-${modelName}`}
                              >
                                Kaldır
                              </button>
                            </>
                          }
                        />
                      );
                    })}
                    {localModelEntries.length === 0 ? (
                      <ListItem title="Henüz model yok" hint="Bir model indirince burada görünecek." />
                    ) : null}
                    {localModelJobs.map((job) => {
                      const record = asRecord(job);
                      const jobId = asString(record.id);
                      const jobStatus = asString(record.status, 'bekliyor');
                      return (
                        <ListItem
                          key={jobId || jobStatus}
                          title={asString(record.kind, 'İş')}
                          hint={jobStatus === 'running' ? 'İşlem sürüyor.' : 'İşlem kuyruğa alındı.'}
                          status={jobStatus === 'running' ? 'İndiriliyor' : 'Bekliyor'}
                          actions={
                            ['queued', 'running'].includes(jobStatus) && jobId ? (
                              <button type="button" className="button-secondary" onClick={() => void cancelLocalJob(jobId)}>
                                İptal et
                              </button>
                            ) : null
                          }
                        />
                      );
                    })}
                  </>
                ) : (
                  <ListItem title="Model indirme" hint="Uygulama içinden model indirme şu an Ollama ile çalışır." status="Ollama ile" />
                )}
              </ListSection>
            </div>
          ) : null}

          {activeSection === 'cloud' ? (
            <div className="settings-section">
              <ListSection title="Bulut modeller">
                {cloudProviderItems.map((item) => {
                  const record = asRecord(item);
                  const providerId = asString(record.id);
                  const form = formStateFor(providerId);
                  const isExpanded = expandedCloudProvider === providerId;
                  return (
                    <ListItem
                      key={providerId}
                      title={asString(record.label)}
                      hint={providerHint(record)}
                      status={providerStatusLabel(record)}
                      actions={
                        <>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={() => setExpandedCloudProvider((current) => (current === providerId ? null : providerId))}
                          >
                            {isExpanded ? 'Kapat' : record.secretConfigured === true ? 'Düzenle' : 'Bağla'}
                          </button>
                          <button type="button" className="button-secondary" onClick={() => void validateProvider(providerId)} disabled={busyKey === `provider-validate-${providerId}`}>
                            Kontrol et
                          </button>
                        </>
                      }
                    >
                      {isExpanded ? (
                        <div className="settings-inline-editor">
                          <InlineField label="Bağlantı anahtarı" type="password" value={form.secret} onChange={(value) => updateProviderForm(providerId, { secret: value, enabled: true })} />
                          <InlineField label="Model" value={form.defaultModel} placeholder="İsteğe bağlı" onChange={(value) => updateProviderForm(providerId, { defaultModel: value, enabled: true })} />
                          <InlineField label="Uç nokta" value={form.baseUrl} placeholder="İsteğe bağlı" onChange={(value) => updateProviderForm(providerId, { baseUrl: value, enabled: true })} />
                          <div className="settings-inline-actions">
                            <button type="button" onClick={() => void saveProvider(providerId)} disabled={busyKey === `provider-save-${providerId}`}>
                              Kaydet
                            </button>
                            <button type="button" className="button-secondary" onClick={() => void removeProviderSecret(providerId)}>
                              <IconTrash />
                              Kaldır
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </ListItem>
                  );
                })}
              </ListSection>
            </div>
          ) : null}

          {activeSection === 'account' ? (
            <div className="settings-section">
              <ListSection title="Hesap">
                <ListItem
                  title={
                    <div className="settings-profile-summary">
                      <img src={avatarPreview || logoUrl} alt="" className="settings-profile-summary-avatar" />
                      <div className="settings-profile-summary-info">
                        <span className="settings-profile-summary-name">{displayName}</span>
                        <span className="settings-profile-summary-email">{email || 'E-posta eklenmemiş.'}</span>
                      </div>
                    </div>
                  }
                  status=""
                  actions={
                    <button type="button" className="button-secondary" onClick={() => setShowProfileForm((current) => !current)}>
                      {showProfileForm ? 'Kapat' : 'Düzenle'}
                    </button>
                  }
                >
                  {showProfileForm ? (
                    <div className="settings-inline-editor">
                      <div className="settings-avatar-row">
                        <img src={avatarPreview || logoUrl} alt="" aria-hidden="true" />
                        <div className="settings-inline-actions">
                          <label className="button-secondary settings-upload-button">
                            Fotoğraf seç
                            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => void uploadAvatar(event.currentTarget.files?.[0] ?? null)} />
                          </label>
                          <button type="button" className="button-secondary" onClick={() => void removeAvatar()} disabled={!account.hasAvatar || busyKey === 'avatar-delete'}>
                            Fotoğrafı kaldır
                          </button>
                        </div>
                      </div>
                      <InlineField label="Hesap adı" value={displayNameInput} onChange={setDisplayNameInput} />
                      <div className="settings-inline-actions">
                        <button type="button" onClick={() => void saveProfile()} disabled={busyKey === 'profile'}>
                          Kaydet
                        </button>
                      </div>
                    </div>
                  ) : null}
                </ListItem>
                <ListItem
                  title={usageSummary.planLabel}
                  hint=""
                  status={accessState.locked ? 'Kullanıma kapalı' : usageSummary.billingStatusLabel}
                >
                  <div className="settings-usage-list">
                    <div className="settings-usage-row">
                      <span>Token durumu</span>
                      <strong>{usageSummary.tokenSummaryLabel}</strong>
                    </div>
                    <div className="settings-usage-row">
                      <span>Plan dönemi</span>
                      <strong>{usageSummary.endsAtLabel}</strong>
                    </div>
                    {usageSummary.quotaWindows.map((window) => (
                      <div className="settings-usage-row" key={`${window.title}-${window.resetAt}`}>
                        <span>{window.title}</span>
                        <strong>{window.remainingLabel}</strong>
                      </div>
                    ))}
                    {usageSummary.quotaWindows.map((window) => (
                      <div className="settings-usage-row" key={`${window.title}-${window.resetAt}-reset`}>
                        <span>{window.title} yenilenme</span>
                        <strong>{window.resetAtLabel}</strong>
                      </div>
                    ))}
                  </div>
                </ListItem>
                <ListItem
                  title="Şifre"
                  hint="İstersen giriş şifreni yenileyebilirsin."
                  actions={
                    <button type="button" className="button-secondary" onClick={() => setShowPasswordForm((current) => !current)}>
                      {showPasswordForm ? 'Kapat' : 'Şifreyi değiştir'}
                    </button>
                  }
                >
                  {showPasswordForm ? (
                    <div className="settings-inline-editor">
                      <InlineField label="Mevcut şifre" type="password" value={currentPassword} onChange={setCurrentPassword} />
                      <InlineField label="Yeni şifre" type="password" value={nextPassword} onChange={setNextPassword} />
                      <div className="settings-inline-actions">
                        <button type="button" onClick={() => void changePassword()} disabled={busyKey === 'password'}>
                          Güncelle
                        </button>
                      </div>
                    </div>
                  ) : null}
                </ListItem>
                <ListItem
                  title="Oturum"
                  hint="Hesabından güvenli şekilde çıkabilirsin."
                  actions={
                    <button type="button" className="button-secondary" onClick={onLogout}>
                      Çıkış yap
                    </button>
                  }
                />
              </ListSection>
            </div>
          ) : null}

          {activeSection === 'pairing' ? (
            <div className="settings-section">
              {isPlanRestricted ? (
                <ListSection title="Telefon bağlantısı">
                  <ListItem
                    title="Plan yetersiz"
                    hint="Bu özellik Pro plana özeldir. Hesabını Elyan.com üzerinden yükselt."
                    status="Kilitli"
                  />
                </ListSection>
              ) : (
                <>
                  <ListSection title="Bağlı cihazlar">
                    {(() => {
                      const mobileBootstrapData = backendResultData(backendRecord(snapshot).mobileBootstrap);
                      const allDevices = asArray(mobileBootstrapData.devices);
                      const activeDevices = allDevices.map(asRecord).filter((d) => d.isActive !== false);
                      const mobileDevices = activeDevices.filter((d) => asString(d.type) === 'mobile');
                      const desktopLabel = asString(runtimeDevice.label) || 'Bu bilgisayar';
                      const wsConnected = asBoolean(runtimeRecord(snapshot).runtimeWebsocketConnected);
                      const desktopConnected = runtimeReadiness.canReceiveTasks === true && isNetworkReady;
                      const desktopHint = wsConnected
                        ? 'Desktop — WebSocket bağlı'
                        : desktopConnected
                          ? 'Desktop — HTTP modunda'
                          : 'Desktop — Bağlantı bekleniyor';

                      const removeDevice = async (deviceId: string) => {
                        if (!window.confirm('Bu cihazı kaldırmak istediğine emin misin?')) return;
                        setBusyKey(`remove-${deviceId}`);
                        try {
                          await desktopApi.request({
                            capability: 'backend.device_deactivate',
                            payload: { deviceId },
                          });
                          await onRefresh();
                        } catch {
                          setError('Cihaz kaldırılamadı.');
                        } finally {
                          setBusyKey('');
                        }
                      };

                      return (
                        <>
                          <ListItem
                            title={desktopLabel}
                            hint={desktopHint}
                            status={desktopConnected ? (wsConnected ? 'Hazır (WS)' : 'Hazır') : 'Bekliyor'}
                          />
                          {mobileDevices.length === 0 ? (
                            <ListItem
                              title="Telefon bağlı değil"
                              hint="Elyan mobil uygulamasından giriş yaparak bu bilgisayara bağlan."
                              status="Bağlı değil"
                            />
                          ) : (
                            mobileDevices.map((d, i) => {
                              const deviceId = asString(d.id);
                              const label = asString(d.label || d.id) || `Telefon ${i + 1}`;
                              const runtime = asRecord(d.runtime);
                              const isConnected = runtime.isConnected === true;
                              const platform = asString(d.platform);
                              const lastSeenAt = asString(d.lastSeenAt);
                              const lastSeenLabel = lastSeenAt
                                ? `Son görülme: ${new Date(lastSeenAt).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`
                                : '';
                              const hint = [platform, lastSeenLabel].filter(Boolean).join(' · ');
                              const isBusy = busyKey === `remove-${deviceId}`;
                              return (
                                <ListItem
                                  key={deviceId || String(i)}
                                  title={label}
                                  hint={hint || 'Mobil'}
                                  status={isConnected ? 'Aktif' : 'Çevrimdışı'}
                                  actions={
                                    <button
                                      type="button"
                                      className="button-secondary button-danger"
                                      disabled={isBusy}
                                      onClick={() => void removeDevice(deviceId)}
                                    >
                                      {isBusy ? '…' : 'Kaldır'}
                                    </button>
                                  }
                                />
                              );
                            })
                          )}
                        </>
                      );
                    })()}
                  </ListSection>
                  <ListSection title="Yeni cihaz ekle">
                    <ListItem
                      title="QR kod ile eşleştir"
                      hint="Telefondaki Elyan uygulamasından QR kodunu tarat."
                      actions={
                        <>
                          <button type="button" onClick={() => void createPairing()} disabled={busyKey === 'pairing'}>
                            Yeni kod oluştur
                          </button>
                          <button type="button" className="button-secondary" onClick={onEnsureRegistered}>
                            Yenile
                          </button>
                        </>
                      }
                    >
                      <div className="settings-pairing-detail">
                        {qrDataUrl ? (
                          <img src={qrDataUrl} alt="Telefon eşleştirme QR" />
                        ) : (
                          <div className="settings-pairing-empty">Kod hazır olduğunda burada görünecek.</div>
                        )}
                        {(asString(pairing.pairingCode) || manualEntryCode) ? (
                          <div className="settings-pairing-rows">
                            {asString(pairing.pairingCode) ? (
                              <div>
                                <strong>Kod</strong>
                                <span>{asString(pairing.pairingCode)}</span>
                              </div>
                            ) : null}
                            {manualEntryCode ? (
                              <div>
                                <strong>Manuel kod</strong>
                                <span>{manualEntryCode}</span>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        <div className="settings-pairing-actions">
                          {asString(pairing.pairingCode) ? (
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => void copyPairingValue(asString(pairing.pairingCode), 'Bağlantı kodu kopyalandı.')}
                            >
                              Kodu kopyala
                            </button>
                          ) : null}
                          {manualEntryCode ? (
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => void copyPairingValue(manualEntryCode, 'Manuel veriyi kopyala.')}
                            >
                              Manuel veriyi kopyala
                            </button>
                          ) : null}
                        </div>
                      </div>
                    </ListItem>
                  </ListSection>
                </>
              )}
            </div>
          ) : null}

          {activeSection === 'privacy' ? (
            <div className="settings-section">
              <ListSection title="Gizlilik">
                <ListItem
                  title="Yerel çalışma"
                  hint="Özel işler burada kalır."
                  status={asBoolean(asRecord(stateRecord(snapshot).privacy).localDataStaysLocal) ? 'Açık' : 'Kapalı'}
                  actions={
                    <label className="settings-inline-toggle">
                      <input
                        type="checkbox"
                        checked={asBoolean(asRecord(stateRecord(snapshot).privacy).localDataStaysLocal)}
                        onChange={(event) => void savePrivacySettings('localDataStaysLocal', event.currentTarget.checked)}
                      />
                      <span>Kullan</span>
                    </label>
                  }
                />
                <ListItem
                  title="Kullanım ölçümü"
                  hint="Anonim kalite sinyali."
                  status={boolLabel(asBoolean(asRecord(stateRecord(snapshot).privacy).analytics))}
                  actions={
                    <label className="settings-inline-toggle">
                      <input
                        type="checkbox"
                        checked={asBoolean(asRecord(stateRecord(snapshot).privacy).analytics)}
                        onChange={(event) => void savePrivacySettings('analytics', event.currentTarget.checked)}
                      />
                      <span>Kullan</span>
                    </label>
                  }
                />
                <ListItem
                  title="Güvenli hata gizleme"
                  hint="Hata kayıtları maskelenir."
                  status={boolLabel(asBoolean(asRecord(stateRecord(snapshot).privacy).redactCrashReports))}
                  actions={
                    <label className="settings-inline-toggle">
                      <input
                        type="checkbox"
                        checked={asBoolean(asRecord(stateRecord(snapshot).privacy).redactCrashReports)}
                        onChange={(event) => void savePrivacySettings('redactCrashReports', event.currentTarget.checked)}
                      />
                      <span>Kullan</span>
                    </label>
                  }
                />
                <ListItem
                  title="İzin geçmişi"
                  hint="İzin kullanımı tutulur."
                  status={boolLabel(asBoolean(asRecord(stateRecord(snapshot).privacy).permissionHistory))}
                  actions={
                    <label className="settings-inline-toggle">
                      <input
                        type="checkbox"
                        checked={asBoolean(asRecord(stateRecord(snapshot).privacy).permissionHistory)}
                        onChange={(event) => void savePrivacySettings('permissionHistory', event.currentTarget.checked)}
                      />
                      <span>Kullan</span>
                    </label>
                  }
                />
                <ListItem
                  title="Tüm araçlar"
                  hint="Yerel araçları topluca aç."
                  status={boolLabel(asBoolean(account.dangerousAreaEnabled))}
                  actions={
                    <label className="settings-inline-toggle">
                      <input
                        type="checkbox"
                        checked={asBoolean(account.dangerousAreaEnabled)}
                        onChange={(event) => void saveMasterPermissions(event.currentTarget.checked)}
                      />
                      <span>Kullan</span>
                    </label>
                  }
                />
                
                <ListItem
                  title="Gelişmiş İzinler"
                  hint="Cihaz bazlı sistem ve araç erişim izinlerini yönet."
                  actions={
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={() => setExpandedPermissionsDrawer(!expandedPermissionsDrawer)}
                    >
                      {expandedPermissionsDrawer ? 'Gizle' : 'Yönet'}
                    </button>
                  }
                >
                  {expandedPermissionsDrawer ? (
                    <div className="settings-list" style={{ marginTop: '0.5rem', padding: '0.5rem', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
                      {PERMISSION_ITEMS.map((item) => {
                        const enabled = asBoolean(permissionsState[item.key]);
                        const osStatus = item.systemPermission ? systemPermissionLabel(asRecord(nativePermissions)[item.systemPermission]) : '';
                        return (
                          <ListItem
                            key={item.key}
                            title={item.title}
                            hint={item.hint}
                            status={osStatus ? `${permissionStatusLabel(enabled)} · ${osStatus}` : permissionStatusLabel(enabled)}
                            actions={
                              <>
                                {item.systemPermission ? (
                                  <button
                                    type="button"
                                    className="button-secondary"
                                    onClick={() => void openSystemPermissionSettings(item.systemPermission!)}
                                    disabled={busyKey === `open-system-permission-${item.systemPermission}`}
                                  >
                                    Sistem ayarı
                                  </button>
                                ) : null}
                                <label className="settings-inline-toggle">
                                  <input
                                    type="checkbox"
                                    checked={enabled}
                                    onChange={(event) => void savePermissionState({ [item.key]: event.currentTarget.checked })}
                                  />
                                  <span>Kullan</span>
                                </label>
                              </>
                            }
                          />
                        );
                      })}
                    </div>
                  ) : null}
                </ListItem>
                
                <ListItem
                  title="Geçmişi temizle"
                  hint="Tüm yerel sohbet geçmişini ve verileri siler."
                  actions={
                    <button type="button" className="button-secondary" onClick={() => void clearHistory()} disabled={busyKey === 'clear-history'}>
                      Geçmişi temizle
                    </button>
                  }
                />
                
                <ListItem
                  title="Hesabı sil"
                  hint="Gerekirse hesabını kalıcı olarak kapatabilirsin."
                  actions={
                    <button type="button" className="button-danger" onClick={() => void deleteAccount()} disabled={busyKey === 'delete-account'}>
                      <IconTrash />
                      Hesabı sil
                    </button>
                  }
                />
              </ListSection>
            </div>
          ) : null}

          {activeSection === 'advanced' ? (
            <div className="settings-section">
              <ListSection title="Gelişmiş">
                <ListItem
                  title="Bulut yedeği"
                  hint="Yerel model yetmezse internet üzerinden devam edebilsin."
                  status={providerCatalog?.fallbackToCloud === false ? 'Kapalı' : 'Açık'}
                  actions={
                    <label className="settings-inline-toggle">
                      <input
                        type="checkbox"
                        checked={providerCatalog?.fallbackToCloud !== false}
                        onChange={(event) => void saveFallbackToCloud(event.currentTarget.checked)}
                      />
                      <span>Kullan</span>
                    </label>
                  }
                />
                <ListItem
                  title="Anahtar saklama"
                  hint={vaultStatus?.persistent ? 'Bağlantı anahtarları bu bilgisayarda saklanır.' : 'Anahtarlar yalnız bu oturum boyunca tutulur.'}
                  status={vaultStatus?.persistent ? 'Kalıcı' : 'Oturumluk'}
                />
                {advancedProviderItems.map((item) => {
                  const record = asRecord(item);
                  const providerId = asString(record.id);
                  const form = formStateFor(providerId);
                  const isExpanded = expandedAdvancedProvider === providerId;
                  const canStartLlamaCpp =
                    providerId === 'llamacpp' &&
                    Boolean(form.binaryPath.trim()) &&
                    Boolean(form.modelPath.trim()) &&
                    asRecord(record.runtimeStatus).reachable !== true;
                  return (
                    <ListItem
                      key={providerId}
                      title={asString(record.label)}
                      hint={providerHint(record)}
                      status={providerStatusLabel(record)}
                      actions={
                        <>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={() => setExpandedAdvancedProvider((current) => (current === providerId ? null : providerId))}
                          >
                            {isExpanded ? 'Kapat' : 'Düzenle'}
                          </button>
                          <button type="button" className="button-secondary" onClick={() => void validateProvider(providerId)} disabled={busyKey === `provider-validate-${providerId}`}>
                            Kontrol et
                          </button>
                          {canStartLlamaCpp ? (
                            <button type="button" className="button-secondary" onClick={() => void startLocalRuntime(providerId)}>
                              Aç
                            </button>
                          ) : null}
                        </>
                      }
                    >
                      {isExpanded ? (
                        <div className="settings-inline-editor">
                          <InlineField label="Uç nokta" value={form.baseUrl} onChange={(value) => updateProviderForm(providerId, { baseUrl: value, enabled: true })} />
                          <InlineField label="Model" value={form.defaultModel} onChange={(value) => updateProviderForm(providerId, { defaultModel: value, enabled: true })} />
                          {providerId === 'groq' || providerId === 'custom' ? (
                            <InlineField label="Bağlantı anahtarı" type="password" value={form.secret} onChange={(value) => updateProviderForm(providerId, { secret: value, enabled: true })} />
                          ) : null}
                          {providerId === 'llamacpp' ? (
                            <>
                              <InlineField label="Başlatma uygulaması" value={form.binaryPath} onChange={(value) => updateProviderForm(providerId, { binaryPath: value, enabled: true })} />
                              <InlineField label="Model dosyası" value={form.modelPath} onChange={(value) => updateProviderForm(providerId, { modelPath: value, enabled: true })} />
                            </>
                          ) : null}
                          <div className="settings-inline-actions">
                            <button type="button" onClick={() => void saveProvider(providerId)} disabled={busyKey === `provider-save-${providerId}`}>
                              Kaydet
                            </button>
                            {(providerId === 'groq' || providerId === 'custom') && record.secretConfigured === true ? (
                              <button type="button" className="button-secondary" onClick={() => void removeProviderSecret(providerId)}>
                                Anahtarı kaldır
                              </button>
                            ) : null}
                          </div>
                        </div>
                      ) : null}
                    </ListItem>
                  );
                })}
                {authMe.ok === true ? (
                  <ListItem
                    title="Web hesabı"
                    hint="Hesabını tarayıcıda açabilirsin."
                    actions={
                      <a className="button-secondary button-link" href="https://elyan.ai" target="_blank" rel="noreferrer">
                        <IconOpenExternal />
                        Aç
                      </a>
                    }
                  />
                ) : null}
              </ListSection>
            </div>
          ) : null}

          {activeSection === 'theme' ? (
            <div className="settings-section">
              <ListSection title="Görünüm ve Özelleştirme">
                <ListItem
                  title="Vurgu Rengi"
                  actions={
                    <div className="theme-color-picker">
                      {[
                        { id: 'elyan', color: '#5c7c5c', title: 'Orman' },
                        { id: 'mor', color: '#7a5882', title: 'Kadife' },
                        { id: 'okyanus', color: '#4a7888', title: 'Deniz' },
                        { id: 'kehribar', color: '#a87830', title: 'Kehribar' },
                        { id: 'gul_kurusu', color: '#a06868', title: 'Gül' },
                        { id: 'arduvaz', color: '#4e5f80', title: 'Arduvaz' },
                        { id: 'ahsap', color: '#dfd8cf', title: 'Ahşap' },
                      ].map(t => (
                        <button
                          key={t.id}
                          type="button"
                          title={t.title}
                          className={`theme-color-swatch ${activeTheme === t.id ? 'theme-color-swatch--active' : ''}`}
                          style={{ background: t.color }}
                          onClick={() => {
                            setActiveTheme(t.id);
                            safeStorageSet('elyan-theme', t.id);
                            if (t.id === 'elyan') {
                              document.documentElement.removeAttribute('data-theme');
                            } else {
                              document.documentElement.setAttribute('data-theme', t.id);
                            }
                          }}
                        />
                      ))}
                    </div>
                  }
                />
                <ListItem
                  title="Yazı Boyutu"
                  actions={
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button type="button" className="button-secondary" style={{ opacity: uiScale === '0.9' ? 1 : 0.5 }} onClick={() => {
                        setUiScale('0.9');
                        safeStorageSet('elyan-ui-scale', '0.9');
                        document.documentElement.style.zoom = '0.9';
                      }}>Küçük</button>
                      <button type="button" className="button-secondary" style={{ opacity: uiScale === '1' ? 1 : 0.5 }} onClick={() => {
                        setUiScale('1');
                        safeStorageSet('elyan-ui-scale', '1');
                        document.documentElement.style.zoom = '1';
                      }}>Varsayılan</button>
                      <button type="button" className="button-secondary" style={{ opacity: uiScale === '1.1' ? 1 : 0.5 }} onClick={() => {
                        setUiScale('1.1');
                        safeStorageSet('elyan-ui-scale', '1.1');
                        document.documentElement.style.zoom = '1.1';
                      }}>Büyük</button>
                    </div>
                  }
                />
                <ListItem
                  title="Ambiyans Aydınlatması"
                  actions={
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button type="button" className="button-secondary" style={{ opacity: ambientOpacity === '0' ? 1 : 0.5 }} onClick={() => {
                        setAmbientOpacity('0');
                        safeStorageSet('elyan-ambient-opacity', '0');
                        document.documentElement.style.setProperty('--ambient-opacity', '0');
                      }}>Kapalı</button>
                      <button type="button" className="button-secondary" style={{ opacity: ambientOpacity === '0.5' ? 1 : 0.5 }} onClick={() => {
                        setAmbientOpacity('0.5');
                        safeStorageSet('elyan-ambient-opacity', '0.5');
                        document.documentElement.style.setProperty('--ambient-opacity', '0.5');
                      }}>Hafif</button>
                      <button type="button" className="button-secondary" style={{ opacity: ambientOpacity === '1' ? 1 : 0.5 }} onClick={() => {
                        setAmbientOpacity('1');
                        safeStorageSet('elyan-ambient-opacity', '1');
                        document.documentElement.style.setProperty('--ambient-opacity', '1');
                      }}>Yoğun</button>
                    </div>
                  }
                />
                <ListItem
                  title="Arayüz Yumuşaklığı"
                  actions={
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button type="button" className="button-secondary" style={{ opacity: baseRadius === '8px' ? 1 : 0.5 }} onClick={() => {
                        setBaseRadius('8px');
                        safeStorageSet('elyan-base-radius', '8px');
                        document.documentElement.style.setProperty('--base-radius', '8px');
                      }}>Köşeli</button>
                      <button type="button" className="button-secondary" style={{ opacity: baseRadius === '16px' ? 1 : 0.5 }} onClick={() => {
                        setBaseRadius('16px');
                        safeStorageSet('elyan-base-radius', '16px');
                        document.documentElement.style.setProperty('--base-radius', '16px');
                      }}>Varsayılan</button>
                      <button type="button" className="button-secondary" style={{ opacity: baseRadius === '24px' ? 1 : 0.5 }} onClick={() => {
                        setBaseRadius('24px');
                        safeStorageSet('elyan-base-radius', '24px');
                        document.documentElement.style.setProperty('--base-radius', '24px');
                      }}>Yuvarlak</button>
                    </div>
                  }
                />
              </ListSection>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
