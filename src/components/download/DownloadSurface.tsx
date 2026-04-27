'use client';

import React from 'react';
import Link from 'next/link';
import {
  downloadPlatformCards,
  formatReleaseVersion,
  getMissingReleaseAssets,
  isReleaseMatrixComplete,
  resolvePlatformAssets,
  type DownloadPlatform,
} from '@/core/control-plane/downloads';

type DownloadTarget = {
  platform: DownloadPlatform;
  label: string;
  browserDownloadUrl: string;
  name: string;
};

type DownloadSurfaceProps = {
  release: {
    currentTagName?: string;
    updateStatus?: string;
    updateMessage?: string;
    repository?: string;
    publishable?: boolean;
    requiredAssets: string[];
    latest?: {
      tagName?: string;
      htmlUrl?: string;
      complete?: boolean;
      targets?: DownloadTarget[];
    } | null;
    targets?: DownloadTarget[];
  } | null;
};

function detectPlatform(userAgent: string): DownloadPlatform | null {
  const normalized = userAgent.toLowerCase();
  if (normalized.includes('mac os') || normalized.includes('macintosh')) return 'macos';
  if (normalized.includes('windows')) return 'windows';
  if (normalized.includes('linux') || normalized.includes('x11')) return 'linux';
  return null;
}

export function DownloadSurface({ release }: DownloadSurfaceProps) {
  const [detectedPlatform, setDetectedPlatform] = React.useState<DownloadPlatform | null>(null);
  const latest = release?.latest;
  const targets = latest?.targets ?? release?.targets ?? [];
  const requiredAssets = release?.requiredAssets ?? [];
  const complete = latest?.complete ?? isReleaseMatrixComplete(requiredAssets, targets);
  const missingAssets = getMissingReleaseAssets(requiredAssets, targets);

  React.useEffect(() => {
    setDetectedPlatform(detectPlatform(window.navigator.userAgent));
  }, []);

  return (
    <main className="panel-page">
      <section className="panel-page__hero">
        <div>
          <div className="site-kicker">Downloads</div>
          <h1 className="site-title">Install Elyan locally</h1>
          <p className="site-lead">
            Choose the archive for this machine, run the guided setup, then link the CLI to your hosted account only
            when you need shared billing, sync, or device state.
          </p>
        </div>

        <div className="panel-page__meta">
          <div className="site-card">
            <span className="panel-stat__label">Current version</span>
            <strong className="panel-stat__value">{release?.currentTagName ?? 'unknown'}</strong>
          </div>
          <div className="site-card">
            <span className="panel-stat__label">Latest release</span>
            <strong className="panel-stat__value">{latest?.tagName ?? 'none'}</strong>
          </div>
          <div className="site-card">
            <span className="panel-stat__label">Matrix</span>
            <strong className="panel-stat__value">{complete ? 'complete' : 'incomplete'}</strong>
          </div>
        </div>
      </section>

      <section className="download-band">
        <div>
          <h2>First run</h2>
          <p className="panel-copy">
            v1.3 keeps local execution first. The hosted control plane is used for account, plan, billing, release,
            and device-link state; private runtime work stays on the local machine.
          </p>
        </div>
        <div className="download-command">
          <span>Guided setup</span>
          <code>elyan setup --zero-cost</code>
        </div>
      </section>

      <div className="site-grid site-grid--two">
        <article className="site-card">
          <h2>Release state</h2>
          <p className="panel-copy">{release?.updateMessage ?? 'No publishable release is currently available.'}</p>
          <div className="panel-list">
            <PanelRow label="Repository" value={release?.repository ?? 'unknown'} />
            <PanelRow label="Publishable" value={release?.publishable ? 'yes' : 'no'} />
            <PanelRow label="Complete" value={complete ? 'yes' : 'no'} />
            <PanelRow label="Required assets" value={String(requiredAssets.length)} />
            {!complete ? <PanelRow label="Missing" value={missingAssets.join(', ') || 'unknown'} /> : null}
          </div>
          <div className="panel-actions">
            <Link href="/docs/install" className="site-secondary-cta">
              Install docs
            </Link>
            {latest?.htmlUrl ? (
              <Link href={latest.htmlUrl} className="site-cta" target="_blank" rel="noreferrer">
                View release
              </Link>
            ) : null}
          </div>
        </article>

        <article className="site-card">
          <h2>After install</h2>
          <div className="panel-list">
            <PanelRow label="Prepare local runtime" value={<code>elyan setup --zero-cost</code>} />
            <PanelRow label="Start app" value={<code>npm run dev</code>} />
            <PanelRow label="Check health" value={<code>elyan status</code>} />
            <PanelRow label="Link account" value={<code>elyan login --base-url https://api.elyan.dev</code>} />
          </div>
          <p className="panel-copy">Account linking is optional for local use and required only for hosted plan state.</p>
        </article>
      </div>

      <section className="site-card">
        <h2>Downloads</h2>
        <div className="site-grid site-grid--three">
          {downloadPlatformCards.map((card) => {
            const assets = resolvePlatformAssets(targets, card.key);
            const recommended = detectedPlatform === card.key;

            return (
              <article
                key={card.key}
                className={recommended ? 'site-card site-card--interactive download-card download-card--recommended' : 'site-card site-card--interactive download-card'}
              >
                <div className="download-card__heading">
                  <h3>{card.title}</h3>
                  {recommended ? <span>Detected</span> : null}
                </div>
                <p className="panel-copy">{card.detail}</p>
                <div className="download-command">
                  <span>Install</span>
                  <code>{card.installCommand}</code>
                </div>
                <div className="download-command">
                  <span>Setup</span>
                  <code>{card.setupCommand}</code>
                </div>
                <div className="panel-list">
                  {assets.map((asset) => (
                    <PanelRow key={asset.name} label={asset.label} value={<DownloadLink href={asset.browserDownloadUrl} />} />
                  ))}
                  {assets.length === 0 ? <PanelRow label="Availability" value="Not published yet" /> : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="site-card">
        <h2>Release API</h2>
        <p className="panel-copy">
          The download page, CLI status, and release checks use the same release resolver. Scripts should verify the
          tag and required asset matrix before replacing a local runtime.
        </p>
        <div className="panel-list">
          <PanelRow label="API" value={<code>/api/releases/latest</code>} />
          <PanelRow label="Tag" value={formatReleaseVersion(latest?.tagName ?? release?.currentTagName)} />
          <PanelRow label="Targets" value={String(targets.length)} />
        </div>
      </section>
    </main>
  );
}

function PanelRow({ label, value }: { label: string; value: React.ReactNode }) {
  const isBadge = React.isValidElement(value);

  return (
    <div className="panel-row">
      <span>{label}</span>
      {isBadge ? value : <strong>{value}</strong>}
    </div>
  );
}

function DownloadLink({ href }: { href: string }) {
  return (
    <a href={href} className="site-secondary-cta" target="_blank" rel="noreferrer">
      Download
    </a>
  );
}
