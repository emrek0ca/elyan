import { notFound } from 'next/navigation';
import { docSections } from '@/content/site';

export default async function DocDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const section = docSections.find((entry) => entry.slug === slug);

  if (!section) {
    notFound();
  }

  return (
    <div className="site-page">
      <section className="site-hero site-hero--compact">
        <div className="site-kicker">Docs</div>
        <h1 className="site-title">{section.title}</h1>
        <p className="site-lead">{section.summary}</p>
      </section>

      <section className="site-section">
        <article className="site-prose">
          {section.body.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </article>
      </section>
    </div>
  );
}
