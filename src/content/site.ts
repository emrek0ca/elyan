export const docSections = [
  {
    slug: 'getting-started',
    title: 'Getting Started',
    summary: 'The calm first-run path for local Elyan.',
    body: [
      'Copy `.env.example` to `.env`.',
      'Run `npm install`.',
      'Start Ollama locally or set one cloud key.',
      'Run `npm run dev`.',
      'Check `/api/healthz` and `/api/capabilities`.',
      'Open Elyan and ask a real question.',
    ],
  },
  {
    slug: 'install',
    title: 'Install',
    summary: 'Real install paths only.',
    body: [
      'Local source checkout: `cp .env.example .env && npm install && npm run dev`.',
      'Production-like local run: `npm run build && npm run start`.',
      'Global CLI path is supported when installed from npm or a local package.',
      'No desktop wrapper is required for v1.',
    ],
  },
  {
    slug: 'local-runtime',
    title: 'Local Runtime',
    summary: 'The primary product surface.',
    body: [
      'Private context, local files, runtime settings, and direct capability execution stay local by default.',
      'Ollama is the preferred default model host.',
      'If search is unavailable, Elyan degrades into local-only answers instead of failing the product path.',
    ],
  },
  {
    slug: 'hosted-account',
    title: 'Hosted Account',
    summary: 'What the shared control plane actually stores.',
    body: [
      'Accounts, plans, subscriptions, entitlements, credits, hosted usage accounting, and notifications live in the shared control plane.',
      'Hosted state is business state, not your local private runtime memory.',
      'Register and log in on elyan.dev only when you need hosted billing, credits, or panel access.',
    ],
  },
  {
    slug: 'search-and-mcp',
    title: 'Search And MCP',
    summary: 'Optional integrations, not product blockers.',
    body: [
      'SearXNG is optional. Elyan still works without it.',
      'MCP is optional. Add only real servers you actively use.',
      'Browser and crawl capabilities exist for bounded external work, not as default overhead on every request.',
    ],
  },
];

export const publicFaq = [
  {
    question: 'What is Elyan today?',
    answer:
      'Elyan is a local-first personal agent runtime with a narrow hosted control plane for accounts, plans, credits, billing, and hosted access.',
  },
  {
    question: 'Does Elyan require search to work?',
    answer:
      'No. Search improves live retrieval and citations when SearXNG is available, but Elyan remains usable in local-only mode without it.',
  },
  {
    question: 'Where does private context live?',
    answer:
      'Private local runtime context stays on the user machine by default. The hosted control plane stores only shared product and business state.',
  },
  {
    question: 'What does the hosted panel show?',
    answer:
      'Account profile, plan, subscription state, entitlements, hosted credits, ledger entries, usage summaries, notifications, and install guidance.',
  },
];

export const pricingCards = [
  {
    id: 'local_byok',
    title: 'Local / BYOK',
    price: '0 TRY',
    summary: 'Run Elyan locally with your own model keys or Ollama. No hosted billing, no hosted debit.',
    highlights: ['Local runtime', 'No hosted credits', 'Private-first'],
  },
  {
    id: 'cloud_assisted',
    title: 'Cloud-Assisted',
    price: '399 TRY',
    summary: 'Hosted credits, shared-account access, and a narrow billing bridge for users who want elyan.dev.',
    highlights: ['Hosted credits', 'Hosted account', 'Managed routing'],
  },
  {
    id: 'pro_builder',
    title: 'Pro / Builder',
    price: '999 TRY',
    summary: 'Higher hosted credit pool for heavier usage, more routing headroom, and more parallel model work.',
    highlights: ['Higher limits', 'More credits', 'Advanced hosted usage'],
  },
  {
    id: 'team_business',
    title: 'Team / Business',
    price: '2499 TRY',
    summary: 'Shared billing, governance, and per-seat hosted operation for teams.',
    highlights: ['Team billing', 'Higher throughput', 'Governance entitlements'],
  },
];
