'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { SearchBar } from '@/components/search/SearchBar';
import { SearchMode } from '@/types/search';
import { useRouter } from 'next/navigation';
import { pricingCards, publicFaq } from '@/content/site';

export default function Home() {
  const router = useRouter();

  const handleSearch = (query: string, mode: SearchMode) => {
    const params = new URLSearchParams({ q: query, mode });
    router.push(`/chat/new?${params.toString()}`);
  };

  return (
    <div className="site-page">
      <section className="site-hero">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="site-hero__grid"
        >
          <div className="site-hero__copy">
            <div className="site-kicker">Official Elyan Site</div>
            <h1 className="site-title">Local-first personal operator. Narrow hosted control plane.</h1>
            <p className="site-lead">
              Elyan runs on the user machine first. Private context stays local by default. elyan.dev handles account,
              billing, credits, release metadata, docs, downloads, and hosted access only when you actually need them.
            </p>
            <div className="site-actions">
              <Link href="/download" className="site-cta">
                Install Elyan
              </Link>
              <Link href="/auth" className="site-secondary-cta">
                Register / Login
              </Link>
            </div>
            <div className="site-pills">
              <span>Ollama-first</span>
              <span>Search optional</span>
              <span>MCP optional</span>
              <span>Hosted state stays narrow</span>
            </div>
          </div>

          <div className="site-hero__panel">
            <div className="site-card">
              <h2>Ask Elyan right now</h2>
              <p>Try the local runtime directly. If search is offline, Elyan degrades cleanly instead of failing the product path.</p>
              <div className="site-search">
                <SearchBar onSearch={handleSearch} />
              </div>
            </div>
          </div>
        </motion.div>
      </section>

      <section className="site-section">
        <div className="site-grid site-grid--three">
          <article className="site-card">
            <h2>Local runtime</h2>
            <p>Private context, local files, runtime settings, and capability execution stay local by default.</p>
          </article>
          <article className="site-card">
            <h2>Hosted control plane</h2>
            <p>Accounts, subscriptions, entitlements, credits, billing, notifications, and release status live in the shared control plane.</p>
          </article>
          <article className="site-card">
            <h2>Official docs and panel</h2>
            <p>elyan.dev is the official docs, install, update, account, billing, and hosted panel surface.</p>
          </article>
        </div>
      </section>

      <section className="site-section">
        <div className="site-section__header">
          <div className="site-kicker">Install Path</div>
          <h2>Start locally in minutes</h2>
        </div>
        <div className="site-grid site-grid--three">
          {[
            'cp .env.example .env',
            'npm install',
            'Start Ollama or set one cloud API key',
            'npm run dev',
            'Check /api/healthz',
            'Inspect /api/capabilities',
          ].map((step, index) => (
            <div key={step} className="site-step">
              <span>{index + 1}</span>
              <p>{step}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="site-section">
        <div className="site-section__header">
          <div className="site-kicker">Plans</div>
          <h2>Local entry stays simple</h2>
        </div>
        <div className="site-grid site-grid--pricing">
          {pricingCards.map((plan) => (
            <article key={plan.id} className="site-card">
              <div className="site-price">{plan.price}</div>
              <h3>{plan.title}</h3>
              <p>{plan.summary}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="site-section">
        <div className="site-section__header">
          <div className="site-kicker">FAQ</div>
          <h2>Clear boundaries, no fake platform story</h2>
        </div>
        <div className="site-grid site-grid--two">
          {publicFaq.map((item) => (
            <article key={item.question} className="site-card">
              <h3>{item.question}</h3>
              <p>{item.answer}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
