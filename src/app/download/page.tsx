import { getLatestElyanReleaseResponse } from '@/core/control-plane';

export const dynamic = 'force-dynamic';

export default async function DownloadPage() {
  const release = await getLatestElyanReleaseResponse().catch(() => null);

  return (
    <div className="site-page">
      <section className="site-hero site-hero--compact">
        <div className="site-kicker">Download</div>
        <h1 className="site-title">Install Elyan the real way</h1>
        <p className="site-lead">
          No desktop wrapper, no fake installer, no hidden infrastructure. Elyan ships as a direct Node.js / Next.js
          local runtime with explicit update paths.
        </p>
      </section>

      <section className="site-section">
        <div className="site-grid site-grid--two">
          <article className="site-card">
            <h2>Source checkout</h2>
            <pre className="site-code">{`cp .env.example .env
npm install
npm run dev`}</pre>
            <p className="panel-copy">Use this when you want the current repository checked out locally and updated by git.</p>
          </article>

          <article className="site-card">
            <h2>Production-like local run</h2>
            <pre className="site-code">{`npm run build
npm run start`}</pre>
            <p className="panel-copy">This is the direct local Node runtime path the product is designed around.</p>
          </article>

          <article className="site-card">
            <h2>Global CLI</h2>
            <pre className="site-code">{`npm install -g .
elyan doctor
elyan status
elyan update`}</pre>
            <p className="panel-copy">CLI commands cover health, status, and the smallest supported update path for the current install.</p>
          </article>

          <article className="site-card">
            <h2>Release stream</h2>
            {release ? (
              <>
                <div className="site-pills">
                  <span>Installed {release.currentTagName}</span>
                  <span>{release.updateStatus.replace('_', ' ')}</span>
                </div>
                <p className="panel-copy">{release.updateMessage}</p>
                <ul className="site-list">
                  <li>Installed version: {release.currentVersion}</li>
                  <li>Latest publishable release: {release.latest?.tagName ?? 'none'}</li>
                  <li>Repository: {release.repository}</li>
                  <li>Publishable: {release.publishable ? 'yes' : 'no'}</li>
                  <li>Required assets: {release.requiredAssets.length}</li>
                </ul>
              </>
            ) : (
              <p className="panel-copy">Release metadata is unavailable right now. Local install commands still work normally.</p>
            )}
          </article>
        </div>
      </section>
    </div>
  );
}
