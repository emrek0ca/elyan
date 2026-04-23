export default function PlatformPage() {
  return (
    <div className="site-page">
      <section className="site-hero site-hero--compact">
        <div className="site-kicker">Platform</div>
        <h1 className="site-title">One operator path. Local-first by default.</h1>
        <p className="site-lead">
          Elyan routes work through one coherent order: local capability, structured MCP context, MCP tools, browser
          automation, bounded crawl, then direct answer when no external action is needed.
        </p>
      </section>

      <section className="site-section">
        <div className="site-grid site-grid--three">
          {[
            ['Local runtime', 'Private context, routing preferences, and direct capabilities stay on the user machine.'],
            ['Optional hosted control plane', 'Accounts, subscriptions, entitlements, credits, and hosted billing stay narrow and explicit.'],
            ['Bounded capability layer', 'MCP, browser, crawl, docs, charts, and structured tools remain optional and explicit.'],
          ].map(([title, body]) => (
            <article key={title} className="site-card">
              <h2>{title}</h2>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
