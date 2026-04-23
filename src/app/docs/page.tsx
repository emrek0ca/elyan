import Link from 'next/link';
import { docSections } from '@/content/site';

export default function DocsPage() {
  return (
    <div className="site-page">
      <section className="site-hero site-hero--compact">
        <div className="site-kicker">Docs</div>
        <h1 className="site-title">Official Elyan documentation</h1>
        <p className="site-lead">The docs follow the same product truth as the runtime: local-first, narrow hosted state, no fake surfaces.</p>
      </section>

      <section className="site-section">
        <div className="site-grid site-grid--two">
          {docSections.map((section) => (
            <Link key={section.slug} href={`/docs/${section.slug}`} className="site-card site-card--interactive">
              <h2>{section.title}</h2>
              <p>{section.summary}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
