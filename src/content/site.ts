export const docSections = [
  {
    slug: 'getting-started',
    title: 'Getting Started',
    summary: 'The calm first-run path for local Elyan and the separate hosted surface.',
    body: [
      'Copy `.env.example` to `.env`.',
      'Run `npm install`.',
      'Run `elyan setup --zero-cost` for local storage, runtime settings, and model readiness checks.',
      'Start Ollama locally or set one cloud key.',
      'Run `npm run dev`.',
      'Check `/api/healthz` and `/api/capabilities`.',
      'Open Elyan locally first; use elyan.dev only when you need hosted account features.',
    ],
  },
  {
    slug: 'install',
    title: 'Install',
    summary: 'Real install paths for the local runtime.',
    body: [
      'Local source checkout: `cp .env.example .env && npm install && elyan setup --zero-cost && npm run dev`.',
      'Production-like local run: `npm run build && npm run start`.',
      'Global CLI path is supported when installed from npm or a local package.',
      'Hosted account linking is optional: use `elyan login --base-url https://api.elyan.dev` only when you want account, billing, sync, or device state.',
      'No desktop wrapper is required for v1.',
    ],
  },
  {
    slug: 'local-runtime',
    title: 'Local Runtime',
    summary: 'The primary operator surface.',
    body: [
      'Private context, local files, runtime settings, and direct capability execution stay local by default.',
      'Ollama is the preferred default model host.',
      'If search is unavailable, Elyan degrades into local-only answers instead of failing the product path.',
      'The manage view is a command center for the local runtime, not a hosted account dashboard.',
    ],
  },
  {
    slug: 'hosted-account',
    title: 'Hosted Account',
    summary: 'What the shared control plane actually stores.',
    body: [
      'Accounts, sessions, plans, subscriptions, entitlements, credits, hosted usage accounting, device links, and release metadata live in the shared control plane.',
      'Hosted state is business state and device state, not your local private runtime memory.',
      'The hosted surface should never model private tool traces, local files, or local orchestration internals.',
      'Register and log in on elyan.dev only when you need hosted billing, credits, sync, or panel access.',
    ],
  },
  {
    slug: 'search-and-mcp',
    title: 'Search And MCP',
    summary: 'Optional integrations, not product blockers.',
    body: [
      'SearXNG is optional. Elyan still works without it.',
      'MCP is optional. Add only real servers you actively use.',
      'Workspace surfaces can pull in GitHub, Obsidian, and MCP-discovered Gmail, Calendar, and Notion context when configured.',
      'Voice input stays local-first and only appears when the browser or runtime path supports it.',
      'Browser and crawl capabilities exist for bounded external work, not as default overhead on every request.',
      'Document, OCR, spreadsheet, archive, chart, and search capabilities are built on ready libraries, not scratch parsers.',
      'Capability discovery, approval posture, and auditability stay visible before a tool is used.',
    ],
  },
];

export const publicFaq = [
  {
    question: 'What is Elyan today?',
    answer:
      'Elyan is a local-first operator runtime with a separate hosted control plane for accounts, plans, credits, billing, sync, and hosted access.',
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
      'Account profile, plan, subscription state, credits, usage summaries, and linked device state. It does not expose private local runtime context.',
  },
];

export const pricingCards = [
  {
    id: 'local_byok',
    title: 'Local / BYOK',
    price: '0 TRY',
    summary: 'Run the local Elyan runtime with your own model keys or Ollama. No hosted billing or managed credits.',
    highlights: ['Local runtime', 'No hosted credits', 'Private-first'],
  },
  {
    id: 'cloud_assisted',
    title: 'Cloud-Assisted',
    price: '399 TRY',
    summary: 'Hosted account access on elyan.dev for billing, credits, sync, and device management.',
    highlights: ['Hosted credits', 'Hosted account', 'Managed routing'],
  },
  {
    id: 'pro_builder',
    title: 'Pro / Builder',
    price: '999 TRY',
    summary: 'Higher hosted credit pool for heavier usage, more routing headroom, and more parallel model work on elyan.dev.',
    highlights: ['Higher limits', 'More credits', 'Advanced hosted usage'],
  },
  {
    id: 'team_business',
    title: 'Team / Business',
    price: '2499 TRY',
    summary: 'Shared billing, governance, and per-seat hosted access for teams.',
    highlights: ['Team billing', 'Higher throughput', 'Governance entitlements'],
  },
];
