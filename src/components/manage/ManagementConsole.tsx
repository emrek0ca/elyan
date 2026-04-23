'use client';

import React from 'react';
import { motion } from 'framer-motion';
import type { CapabilityDirectorySnapshot } from '@/core/capabilities';
import type { RuntimeSettings } from '@/core/runtime-settings';

type DashboardStatus = {
  ok: boolean;
  runtime: 'local-first';
  surfaces: {
    local: { key: 'local'; label: string; ready: boolean; summary: string; detail: string };
    shared: { key: 'shared'; label: string; ready: boolean; summary: string; detail: string };
    hosted: { key: 'hosted'; label: string; ready: boolean; summary: string; detail: string };
  };
  readiness: {
    hasLocalModels: boolean;
    searchEnabled: boolean;
    searchAvailable: boolean;
    mcpConfigured: boolean;
    voiceConfigured: boolean;
  };
  models: Array<{ id: string; name: string; provider: string; type: string }>;
  capabilities: CapabilityDirectorySnapshot;
  channels: {
    telegram: { configured: boolean; enabled: boolean; mode: string; webhookPath: string };
    whatsappCloud: { configured: boolean; enabled: boolean; webhookPath: string };
    imessage: { configured: boolean; enabled: boolean; webhookPath: string };
  };
  mcp: {
    configured: boolean;
    servers: RuntimeSettings['mcp']['servers'];
  };
  controlPlane: {
    health?: {
      ok?: boolean;
      storage?: string;
      connection?: {
        storage?: string;
        hostedReady?: boolean;
        callbackUrl?: string;
        apiBaseUrl?: string;
        billingMode?: 'sandbox' | 'production';
      };
    };
  };
  runtimeSettings: RuntimeSettings;
};

type RuntimeConfigPayload = {
  settings?: Record<string, unknown>;
  secrets?: Record<string, string | null>;
};

type ReleasePayload = {
  currentVersion: string;
  currentTagName: string;
  repository: string;
  publishable: boolean;
  updateAvailable: boolean;
  updateStatus: 'current' | 'update_available' | 'unavailable';
  updateMessage: string;
  latest: {
    tagName: string;
    publishedAt: string;
    htmlUrl: string;
    complete: boolean;
  } | null;
  requiredAssets: string[];
};

async function fetchStatus(): Promise<DashboardStatus> {
  const response = await fetch('/api/dashboard/status', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load dashboard status (${response.status})`);
  }

  return response.json();
}

async function patchRuntimeConfig(payload: RuntimeConfigPayload) {
  const response = await fetch('/api/runtime/config', {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error || `Failed to save runtime config (${response.status})`);
  }

  return response.json() as Promise<{ ok: boolean }>;
}

async function fetchRelease(): Promise<ReleasePayload> {
  const response = await fetch('/api/releases/latest', { cache: 'no-store' });

  if (!response.ok) {
    throw new Error(`Failed to load release stream (${response.status})`);
  }

  const payload = (await response.json()) as ReleasePayload & { ok?: boolean };
  return payload;
}

export function ManagementConsole() {
  const [status, setStatus] = React.useState<DashboardStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [releaseInfo, setReleaseInfo] = React.useState<ReleasePayload | null>(null);

  const [runtimeForm, setRuntimeForm] = React.useState({
    preferredModelId: '',
    routingMode: 'local_first',
    searchEnabled: true,
  });

  const [channelForm, setChannelForm] = React.useState({
    telegram: {
      enabled: false,
      mode: 'polling',
      webhookPath: '/api/channels/telegram/webhook',
      botUsername: '',
    },
    whatsappCloud: {
      enabled: false,
      webhookPath: '/api/channels/whatsapp/webhook',
    },
    whatsappBaileys: {
      enabled: false,
      sessionPath: 'storage/channels/whatsapp-baileys.json',
    },
      imessage: {
        enabled: false,
        webhookPath: '/api/channels/imessage/bluebubbles/webhook',
      },
    });

  const [mcpJson, setMcpJson] = React.useState('[]');

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        const [next, nextRelease] = await Promise.all([
          fetchStatus(),
          fetchRelease().catch(() => null),
        ]);
        if (cancelled) return;

        setStatus(next);
        setReleaseInfo(nextRelease);
        setRuntimeForm({
          preferredModelId: next.runtimeSettings.routing.preferredModelId ?? '',
          routingMode: next.runtimeSettings.routing.routingMode,
          searchEnabled: next.runtimeSettings.routing.searchEnabled,
        });
        setChannelForm({
          telegram: {
            enabled: next.runtimeSettings.channels.telegram.enabled,
            mode: next.runtimeSettings.channels.telegram.mode,
            webhookPath: next.runtimeSettings.channels.telegram.webhookPath,
            botUsername: next.runtimeSettings.channels.telegram.botUsername ?? '',
          },
          whatsappCloud: {
            enabled: next.runtimeSettings.channels.whatsappCloud.enabled,
            webhookPath: next.runtimeSettings.channels.whatsappCloud.webhookPath,
          },
          whatsappBaileys: {
            enabled: next.runtimeSettings.channels.whatsappBaileys.enabled,
            sessionPath: next.runtimeSettings.channels.whatsappBaileys.sessionPath,
          },
          imessage: {
            enabled: next.runtimeSettings.channels.imessage.enabled,
            webhookPath: next.runtimeSettings.channels.imessage.webhookPath,
          },
        });
        setMcpJson(JSON.stringify(next.runtimeSettings.mcp.servers, null, 2));
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load dashboard');
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = React.useCallback(async () => {
    const [next, nextRelease] = await Promise.all([
      fetchStatus(),
      fetchRelease().catch(() => null),
    ]);
    setStatus(next);
    setReleaseInfo(nextRelease);
    setRuntimeForm({
      preferredModelId: next.runtimeSettings.routing.preferredModelId ?? '',
      routingMode: next.runtimeSettings.routing.routingMode,
      searchEnabled: next.runtimeSettings.routing.searchEnabled,
    });
    setChannelForm({
      telegram: {
        enabled: next.runtimeSettings.channels.telegram.enabled,
        mode: next.runtimeSettings.channels.telegram.mode,
        webhookPath: next.runtimeSettings.channels.telegram.webhookPath,
        botUsername: next.runtimeSettings.channels.telegram.botUsername ?? '',
      },
      whatsappCloud: {
        enabled: next.runtimeSettings.channels.whatsappCloud.enabled,
        webhookPath: next.runtimeSettings.channels.whatsappCloud.webhookPath,
      },
      whatsappBaileys: {
        enabled: next.runtimeSettings.channels.whatsappBaileys.enabled,
        sessionPath: next.runtimeSettings.channels.whatsappBaileys.sessionPath,
      },
      imessage: {
        enabled: next.runtimeSettings.channels.imessage.enabled,
        webhookPath: next.runtimeSettings.channels.imessage.webhookPath,
      },
    });
    setMcpJson(JSON.stringify(next.runtimeSettings.mcp.servers, null, 2));
  }, []);

  const handleRuntimeSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      await patchRuntimeConfig({
        settings: {
          routing: {
            preferredModelId: runtimeForm.preferredModelId.trim() || null,
            routingMode: runtimeForm.routingMode,
            searchEnabled: runtimeForm.searchEnabled,
          },
        },
      });
      setStatus(await fetchStatus());
      setNotice('Runtime settings saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save runtime settings');
    } finally {
      setSaving(false);
    }
  };

  const handleChannelSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const channelSettings = {
        telegram: {
          ...channelForm.telegram,
          botUsername: channelForm.telegram.botUsername.trim() || null,
        },
        whatsappCloud: channelForm.whatsappCloud,
        whatsappBaileys: channelForm.whatsappBaileys,
        imessage: channelForm.imessage,
      };

      await patchRuntimeConfig({
        settings: {
          channels: channelSettings,
        },
      });
      setStatus(await fetchStatus());
      setNotice('Channel settings saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save channel settings');
    } finally {
      setSaving(false);
    }
  };

  const handleMcpSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const servers = JSON.parse(mcpJson);
      if (!Array.isArray(servers)) {
        throw new Error('MCP config must be a JSON array.');
      }

      await patchRuntimeConfig({
        settings: {
          mcp: {
            servers,
          },
        },
      });
      setStatus(await fetchStatus());
      setNotice('MCP servers saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save MCP config');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="manage-page__loading">Loading local runtime status…</div>;
  }

  if (!status) {
    return <div className="manage-page__loading">{error ?? 'Dashboard unavailable.'}</div>;
  }

  return (
    <div className="manage-page">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="manage-page__stack"
      >
        <div className="manage-page__header">
          <div>
            <div className="manage-page__eyebrow">Management</div>
            <h1 className="manage-page__title">Local runtime first. Optional integrations second.</h1>
            <p className="manage-page__lead">
              Inspect startup readiness, capabilities, and only the real settings Elyan uses right now. Hosted state remains optional.
            </p>
          </div>
          <button type="button" className="manage-page__button manage-page__button--ghost" onClick={() => void refresh()}>
            Refresh
          </button>
        </div>

        <section className="manage-page__grid">
          <article className="manage-card">
            <div className="manage-card__title">Local</div>
            <div className="manage-list">
              <ChannelLine label={status.surfaces.local.label} value={status.surfaces.local.ready ? 'Ready' : 'Not ready'} hint={status.surfaces.local.summary} />
              <div className="manage-page__help">{status.surfaces.local.detail}</div>
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title">Shared</div>
            <div className="manage-list">
              <ChannelLine label={status.surfaces.shared.label} value={status.surfaces.shared.ready ? 'Ready' : 'Not ready'} hint={status.surfaces.shared.summary} />
              <div className="manage-page__help">{status.surfaces.shared.detail}</div>
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title">Hosted</div>
            <div className="manage-list">
              <ChannelLine label={status.surfaces.hosted.label} value={status.surfaces.hosted.ready ? 'Ready' : 'Not ready'} hint={status.surfaces.hosted.summary} />
              <div className="manage-page__help">{status.surfaces.hosted.detail}</div>
            </div>
          </article>
        </section>

        <section className="manage-page__grid">
          <article className="manage-card">
            <div className="manage-card__title">Readiness</div>
            <div className="manage-metrics">
              <Metric label="Models" value={status.readiness.hasLocalModels ? 'Ready' : 'Missing'} />
              <Metric
                label="Search"
                value={
                  status.readiness.searchEnabled
                    ? status.readiness.searchAvailable
                      ? 'Reachable'
                      : 'Enabled, offline'
                    : 'Disabled'
                }
              />
              <Metric label="MCP" value={status.readiness.mcpConfigured ? 'Configured' : 'Optional'} />
              <Metric label="Voice" value={status.readiness.voiceConfigured ? 'Configured' : 'Optional'} />
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title">Models</div>
            <div className="manage-list">
              {status.models.length > 0 ? status.models.slice(0, 4).map((model) => (
                <div key={model.id} className="manage-list__row">
                  <div>
                    <div className="manage-list__primary">{model.name}</div>
                    <div className="manage-list__secondary">{model.provider}</div>
                  </div>
                  <div className="manage-list__badge">{model.type}</div>
                </div>
              )) : <div className="manage-page__help">No active model source yet. Start Ollama or set one cloud key.</div>}
            </div>
          </article>
        </section>

        <section className="manage-page__grid">
          <article className="manage-card">
            <div className="manage-card__title">Capabilities</div>
            <div className="manage-metrics">
              <Metric label="Local" value={String(status.capabilities.summary?.localCapabilityCount ?? 0)} />
              <Metric label="Bridge" value={String(status.capabilities.summary?.bridgeToolCount ?? 0)} />
              <Metric label="Skills" value={String(status.capabilities.summary?.skillCount ?? 0)} />
              <Metric label="Installed" value={String(status.capabilities.summary?.installedSkillCount ?? 0)} />
            </div>
            <div className="manage-page__help">
              Browser {status.capabilities.summary?.browserEnabled ? 'available' : 'unavailable'}.
              {' '}Crawl {status.capabilities.summary?.crawlEnabled ? 'available' : 'unavailable'}.
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title">Optional hosted state</div>
            <div className="manage-list">
              <ChannelLine label="Shared control plane" value={status.surfaces.shared.ready ? 'Reachable' : 'Optional'} hint={status.surfaces.shared.detail} />
              <ChannelLine label="Hosted surface" value={status.surfaces.hosted.ready ? 'Configured' : 'Optional'} hint={status.surfaces.hosted.detail} />
              <ChannelLine label="Storage" value={status.controlPlane.health?.storage ?? 'local-only'} hint="Only relevant if you use the shared VPS control plane." />
              <ChannelLine
                label="Billing mode"
                value={status.controlPlane.health?.connection?.billingMode ?? 'unconfigured'}
                hint={status.controlPlane.health?.connection?.apiBaseUrl ?? 'No iyzico endpoint configured.'}
              />
              <ChannelLine
                label="Callback"
                value={status.controlPlane.health?.connection?.hostedReady ? 'Ready' : 'Not ready'}
                hint={status.controlPlane.health?.connection?.callbackUrl ?? 'Hosted callback URL not resolved yet.'}
              />
            </div>
          </article>
        </section>

        <section className="manage-page__grid">
          <article className="manage-card">
            <div className="manage-card__title">Release stream</div>
            <div className="manage-list">
              <ChannelLine
                label="Current"
                value={releaseInfo?.currentTagName ?? 'unknown'}
                hint={releaseInfo ? `${releaseInfo.currentVersion} on ${releaseInfo.repository}` : 'Local runtime release metadata is unavailable.'}
              />
              <ChannelLine
                label="Latest"
                value={releaseInfo?.latest?.tagName ?? 'none'}
                hint={releaseInfo?.latest?.publishedAt ?? releaseInfo?.updateMessage ?? 'No publishable release detected yet.'}
              />
              <ChannelLine
                label="Update status"
                value={releaseInfo?.updateStatus?.replace('_', ' ') ?? 'unavailable'}
                hint={
                  releaseInfo?.updateAvailable
                    ? 'A newer publishable build exists.'
                    : releaseInfo?.publishable
                      ? 'Installed version matches the latest publishable release.'
                      : 'Release checks stay explicit and fail closed.'
                }
              />
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title">Update paths</div>
            <div className="manage-list">
              <ChannelLine label="CLI" value="elyan update" hint="Pull the newest publishable release when running through the installed command." />
              <ChannelLine label="Source checkout" value="git pull --ff-only" hint="Use when you run Elyan directly from the repository." />
              <ChannelLine label="VPS" value="./ops/update.sh" hint="Keep hosted deployments on a reproducible upgrade path." />
            </div>
          </article>
        </section>

        <section className="manage-card">
          <div className="manage-card__title">Runtime routing</div>
          <div className="manage-form">
            <label className="manage-field">
              <span>Preferred model</span>
              <input
                value={runtimeForm.preferredModelId}
                onChange={(event) => setRuntimeForm((current) => ({ ...current, preferredModelId: event.target.value }))}
                placeholder="ollama:llama3.2"
              />
            </label>
            <label className="manage-field">
              <span>Routing mode</span>
              <select
                value={runtimeForm.routingMode}
                onChange={(event) => setRuntimeForm((current) => ({ ...current, routingMode: event.target.value }))}
              >
                <option value="local_only">local_only</option>
                <option value="local_first">local_first</option>
                <option value="balanced">balanced</option>
                <option value="cloud_preferred">cloud_preferred</option>
              </select>
            </label>
            <label className="manage-field manage-field--inline">
              <input
                type="checkbox"
                checked={runtimeForm.searchEnabled}
                onChange={(event) => setRuntimeForm((current) => ({ ...current, searchEnabled: event.target.checked }))}
              />
              <span>Enable web search when SearXNG is available</span>
            </label>
            <div className="manage-form__actions">
              <button type="button" className="manage-page__button" onClick={() => void handleRuntimeSave()} disabled={saving}>
                Save runtime settings
              </button>
            </div>
          </div>
        </section>

        <section className="manage-page__grid">
          <article className="manage-card">
            <div className="manage-card__title">Optional integrations</div>
            <div className="manage-list">
              <ChannelLine label="Telegram" value={status.channels.telegram.enabled ? 'Enabled' : 'Disabled'} hint={status.channels.telegram.webhookPath} />
              <ChannelLine label="WhatsApp Cloud" value={status.channels.whatsappCloud.enabled ? 'Enabled' : 'Disabled'} hint={status.channels.whatsappCloud.webhookPath} />
              <ChannelLine label="iMessage / BlueBubbles" value={status.channels.imessage.enabled ? 'Enabled' : 'Disabled'} hint={status.channels.imessage.webhookPath} />
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title">MCP</div>
            <div className="manage-metrics">
              <Metric label="Configured" value={String(status.capabilities.summary?.mcpConfiguredServerCount ?? 0)} />
              <Metric label="Reachable" value={String(status.capabilities.summary?.mcpReachableServerCount ?? 0)} />
              <Metric label="Blocked" value={String(status.capabilities.summary?.mcpBlockedServerCount ?? 0)} />
              <Metric label="Disabled" value={String(status.capabilities.summary?.mcpDisabledServerCount ?? 0)} />
            </div>
            <div className="manage-list">
              {status.capabilities.mcp.mcpServers.length > 0 ? (
                status.capabilities.mcp.mcpServers.slice(0, 4).map((server) => (
                  <ChannelLine
                    key={server.id}
                    label={server.id}
                    value={(server.state ?? (server.enabled ? 'configured' : 'disabled')).replace('_', ' ')}
                    hint={server.stateReason ?? server.endpoint ?? 'No live state recorded yet.'}
                  />
                ))
              ) : (
                <div className="manage-page__help">
                  {status.mcp.configured
                    ? 'Live MCP surfaces are unavailable right now.'
                    : 'Optional. Add stdio or streamable-http servers.'}
                </div>
              )}
            </div>
          </article>
        </section>

        <section className="manage-card">
          <div className="manage-card__title">Channel connections</div>
          <div className="manage-form">
            <div className="manage-page__help">
              Toggle only the adapters you actually use. Secrets stay in the local env file.
            </div>
            <div className="manage-page__grid">
              <label className="manage-field">
                <span>Telegram enabled</span>
                <input
                  type="checkbox"
                  checked={channelForm.telegram.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      telegram: { ...current.telegram, enabled: event.target.checked },
                    }))
                  }
                />
              </label>
              <label className="manage-field">
                <span>Telegram mode</span>
                <select
                  value={channelForm.telegram.mode}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      telegram: { ...current.telegram, mode: event.target.value },
                    }))
                  }
                >
                  <option value="polling">polling</option>
                  <option value="webhook">webhook</option>
                </select>
              </label>
              <label className="manage-field">
                <span>Telegram webhook path</span>
                <input
                  value={channelForm.telegram.webhookPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      telegram: { ...current.telegram, webhookPath: event.target.value },
                    }))
                  }
                />
              </label>
              <label className="manage-field">
                <span>WhatsApp Cloud enabled</span>
                <input
                  type="checkbox"
                  checked={channelForm.whatsappCloud.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      whatsappCloud: { ...current.whatsappCloud, enabled: event.target.checked },
                    }))
                  }
                />
              </label>
              <label className="manage-field">
                <span>WhatsApp webhook path</span>
                <input
                  value={channelForm.whatsappCloud.webhookPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      whatsappCloud: { ...current.whatsappCloud, webhookPath: event.target.value },
                    }))
                  }
                />
              </label>
              <label className="manage-field">
                <span>iMessage bridge enabled</span>
                <input
                  type="checkbox"
                  checked={channelForm.imessage.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      imessage: { ...current.imessage, enabled: event.target.checked },
                    }))
                  }
                />
              </label>
              <label className="manage-field">
                <span>iMessage webhook path</span>
                <input
                  value={channelForm.imessage.webhookPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      imessage: { ...current.imessage, webhookPath: event.target.value },
                    }))
                  }
                />
              </label>
            </div>
            <label className="manage-field">
              <span>WhatsApp Baileys enabled</span>
              <input
                type="checkbox"
                checked={channelForm.whatsappBaileys.enabled}
                onChange={(event) =>
                  setChannelForm((current) => ({
                    ...current,
                    whatsappBaileys: { ...current.whatsappBaileys, enabled: event.target.checked },
                  }))
                }
              />
            </label>
            <label className="manage-field">
              <span>WhatsApp Baileys session path</span>
              <input
                value={channelForm.whatsappBaileys.sessionPath}
                onChange={(event) =>
                  setChannelForm((current) => ({
                    ...current,
                    whatsappBaileys: { ...current.whatsappBaileys, sessionPath: event.target.value },
                  }))
                }
              />
            </label>
            <div className="manage-form__actions">
              <button type="button" className="manage-page__button" onClick={() => void handleChannelSave()} disabled={saving}>
                Save channels
              </button>
            </div>
          </div>
        </section>

        <section className="manage-card">
          <div className="manage-card__title">MCP servers</div>
          <div className="manage-form">
            <div className="manage-page__help">
              Paste a JSON array of stdio or streamable-http server configs only if you actively use MCP.
            </div>
            <textarea
              className="manage-textarea"
              rows={10}
              value={mcpJson}
              onChange={(event) => setMcpJson(event.target.value)}
            />
            <div className="manage-form__actions">
              <button type="button" className="manage-page__button" onClick={() => void handleMcpSave()} disabled={saving}>
                Save MCP servers
              </button>
            </div>
          </div>
        </section>

        {notice ? <div className="manage-banner manage-banner--success">{notice}</div> : null}
        {error ? <div className="manage-banner manage-banner--error">{error}</div> : null}
      </motion.div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="manage-metric">
      <div className="manage-metric__label">{label}</div>
      <div className="manage-metric__value">{value}</div>
    </div>
  );
}

function ChannelLine({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="manage-list__row">
      <div>
        <div className="manage-list__primary">{label}</div>
        <div className="manage-list__secondary">{hint}</div>
      </div>
      <div className="manage-list__badge">{value}</div>
    </div>
  );
}
