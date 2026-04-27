import path from 'node:path';
import { readFile, readdir, stat } from 'node:fs/promises';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { readMcpServerConfigs, buildConfiguredMcpServerCatalog, McpToolRegistry } from '@/core/mcp';
import type { RuntimeSettings } from '@/core/runtime-settings';
import type {
  WorkspaceBriefRecord,
  WorkspaceJobRecord,
  WorkspaceSourceKind,
  WorkspaceSourceRecord,
  WorkspaceStatusSnapshot,
} from './types';

type DiscoveredMcpSurface = {
  servers: Awaited<ReturnType<McpToolRegistry['listServers']>>;
  tools: Awaited<ReturnType<McpToolRegistry['listTools']>>;
  resources: Awaited<ReturnType<McpToolRegistry['listResources']>>;
  prompts: Awaited<ReturnType<McpToolRegistry['listPrompts']>>;
};

type GitHubRepoSnapshot = {
  fullName: string;
  description: string;
  updatedAt?: string;
  openIssuesCount?: number;
  stars?: number;
  defaultBranch?: string;
};

type NoteSnapshot = {
  path: string;
  title: string;
  snippet: string;
  modifiedAt: string;
};

const SOURCE_ORDER: WorkspaceSourceKind[] = ['gmail', 'calendar', 'notion', 'github', 'obsidian', 'mcp'];

function normalizeText(value: string) {
  return value.trim().toLowerCase();
}

function matchesWorkspaceKind(value: string): WorkspaceSourceKind | null {
  const text = normalizeText(value);

  if (/(^|[^a-z])gmail([^a-z]|$)|google mail|inbox/.test(text)) {
    return 'gmail';
  }

  if (/(^|[^a-z])calendar([^a-z]|$)|google calendar|schedule|agenda/.test(text)) {
    return 'calendar';
  }

  if (/(^|[^a-z])notion([^a-z]|$)/.test(text)) {
    return 'notion';
  }

  if (/(^|[^a-z])github([^a-z]|$)|pull request|pull request|repo|repository/.test(text)) {
    return 'github';
  }

  if (/(^|[^a-z])obsidian([^a-z]|$)|vault/.test(text)) {
    return 'obsidian';
  }

  return null;
}

function createSourceRecord(
  kind: WorkspaceSourceKind,
  partial: Partial<WorkspaceSourceRecord> & Pick<WorkspaceSourceRecord, 'title' | 'summary' | 'detail'>
): WorkspaceSourceRecord {
  return {
    kind,
    state: partial.state ?? 'unconfigured',
    origin: partial.origin ?? 'derived',
    title: partial.title,
    summary: partial.summary,
    detail: partial.detail,
    stats: partial.stats,
    lastSyncAt: partial.lastSyncAt,
  };
}

function mergeCounts(records: WorkspaceSourceRecord[]) {
  const totals = {
    configuredSourceCount: 0,
    connectedSourceCount: 0,
    availableSourceCount: 0,
  };

  for (const record of records) {
    if (record.state !== 'unconfigured') {
      totals.configuredSourceCount += 1;
    }

    if (record.state === 'connected' || record.state === 'partial') {
      totals.connectedSourceCount += 1;
    }

    if (record.state === 'available') {
      totals.availableSourceCount += 1;
    }
  }

  return totals;
}

function parsePositiveInteger(value: string | undefined, fallback: number) {
  const parsed = Number.parseInt(String(value ?? '').trim(), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function computeNextDailyRun(now: Date, hour: number, minute: number) {
  const candidate = new Date(now);
  candidate.setHours(hour, minute, 0, 0);

  if (candidate.getTime() <= now.getTime()) {
    candidate.setDate(candidate.getDate() + 1);
  }

  return candidate.toISOString();
}

function computeNextIntervalRun(now: Date, intervalMinutes: number) {
  const intervalMs = intervalMinutes * 60_000;
  const next = Math.ceil(now.getTime() / intervalMs) * intervalMs;
  return new Date(next).toISOString();
}

async function fetchJsonWithTimeout(url: string, timeoutMs: number, init: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
    });

    if (!response.ok) {
      return null;
    }

    return await response.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

async function readGitHubSnapshot(): Promise<GitHubRepoSnapshot | null> {
  const repo = readRuntimeEnvValue('GITHUB_REPO') || readRuntimeEnvValue('GITHUB_REPOSITORY');
  const token = readRuntimeEnvValue('GITHUB_TOKEN');
  const allowTestFetch = process.env.ELYAN_ALLOW_GITHUB_WORKSPACE_FETCH_IN_TESTS === '1';

  if (!repo || !token || (process.env.NODE_ENV === 'test' && !allowTestFetch)) {
    return null;
  }

  const baseHeaders: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'User-Agent': 'elyan-workspace',
  };

  if (token) {
    baseHeaders.Authorization = `Bearer ${token}`;
  }

  const repoJson = await fetchJsonWithTimeout(`https://api.github.com/repos/${repo}`, 2_500, {
    headers: baseHeaders,
  });

  if (!repoJson) {
    return {
      fullName: repo,
      description: 'GitHub repository configured, but metadata could not be fetched.',
    };
  }

  return {
    fullName: String(repoJson.full_name ?? repo),
    description: String(repoJson.description ?? 'GitHub repository connected.'),
    updatedAt: typeof repoJson.updated_at === 'string' ? repoJson.updated_at : undefined,
    openIssuesCount: typeof repoJson.open_issues_count === 'number' ? repoJson.open_issues_count : undefined,
    stars: typeof repoJson.stargazers_count === 'number' ? repoJson.stargazers_count : undefined,
    defaultBranch: typeof repoJson.default_branch === 'string' ? repoJson.default_branch : undefined,
  };
}

function extractNoteTitle(content: string, fallbackTitle: string) {
  const heading = content.match(/^#\s+(.+)$/m)?.[1]?.trim();
  if (heading) {
    return heading;
  }

  return fallbackTitle;
}

function extractNoteSnippet(content: string) {
  const lines = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith('#'));

  return lines[0]?.slice(0, 180) ?? '';
}

async function collectMarkdownFiles(rootDir: string, maxDepth = 2, maxFiles = 24) {
  const results: Array<{ path: string; modifiedAt: number }> = [];
  const stack: Array<{ dir: string; depth: number }> = [{ dir: rootDir, depth: 0 }];

  while (stack.length > 0 && results.length < maxFiles) {
    const current = stack.pop();
    if (!current) {
      break;
    }

    let entries;
    try {
      entries = await readdir(current.dir, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      const entryPath = path.join(current.dir, entry.name);
      if (entry.isDirectory()) {
        if (current.depth < maxDepth) {
          stack.push({ dir: entryPath, depth: current.depth + 1 });
        }
        continue;
      }

      if (!entry.isFile() || !/\.(md|markdown)$/i.test(entry.name)) {
        continue;
      }

      try {
        const fileStat = await stat(entryPath);
        results.push({
          path: entryPath,
          modifiedAt: fileStat.mtimeMs,
        });
      } catch {
        continue;
      }
    }
  }

  return results.sort((left, right) => right.modifiedAt - left.modifiedAt);
}

async function readRecentObsidianNotes(): Promise<NoteSnapshot[]> {
  const vaultPath = readRuntimeEnvValue('OBSIDIAN_VAULT_PATH')?.trim();
  if (!vaultPath) {
    return [];
  }

  let vaultStat;
  try {
    vaultStat = await stat(vaultPath);
  } catch {
    return [];
  }

  if (!vaultStat.isDirectory()) {
    return [];
  }

  const files = await collectMarkdownFiles(vaultPath);
  const notes: NoteSnapshot[] = [];

  for (const file of files.slice(0, 3)) {
    try {
      const content = await readFile(file.path, 'utf8');
      const relativePath = path.relative(vaultPath, file.path);
      notes.push({
        path: relativePath,
        title: extractNoteTitle(content, path.basename(file.path, path.extname(file.path))),
        snippet: extractNoteSnippet(content),
        modifiedAt: new Date(file.modifiedAt).toISOString(),
      });
    } catch {
      continue;
    }
  }

  return notes;
}

async function discoverMcpSurfaces(runtimeSettings: RuntimeSettings) {
  let serverConfigs = runtimeSettings.mcp.servers;

  if (serverConfigs.length === 0) {
    try {
      serverConfigs = readMcpServerConfigs();
    } catch {
      serverConfigs = [];
    }
  }

  const configuredServers = buildConfiguredMcpServerCatalog(serverConfigs);

  if (serverConfigs.length === 0) {
    return {
      servers: configuredServers,
      tools: [] as DiscoveredMcpSurface['tools'],
      resources: [] as DiscoveredMcpSurface['resources'],
      prompts: [] as DiscoveredMcpSurface['prompts'],
    };
  }

  const registry = new McpToolRegistry(serverConfigs);
  try {
    const [servers, tools, resources, prompts] = await Promise.all([
      registry.listServers(),
      registry.listTools(),
      registry.listResources(),
      registry.listPrompts(),
    ]);

    return {
      servers,
      tools,
      resources,
      prompts,
    };
  } catch {
    return {
      servers: configuredServers,
      tools: [] as DiscoveredMcpSurface['tools'],
      resources: [] as DiscoveredMcpSurface['resources'],
      prompts: [] as DiscoveredMcpSurface['prompts'],
    };
  } finally {
    await registry.close();
  }
}

function buildMcpSourceRecords(discovery: Awaited<ReturnType<typeof discoverMcpSurfaces>>) {
  const sourceMap = new Map<WorkspaceSourceKind, WorkspaceSourceRecord>();

  for (const kind of SOURCE_ORDER) {
    sourceMap.set(
      kind,
      createSourceRecord(kind, {
        title:
          kind === 'mcp'
            ? 'MCP surfaces'
            : kind === 'github'
              ? 'GitHub'
              : kind === 'gmail'
                ? 'Gmail'
                : kind === 'calendar'
                  ? 'Calendar'
                  : kind === 'notion'
                    ? 'Notion'
                    : 'Obsidian',
        summary: 'Not configured yet.',
        detail: 'Connect a source to surface live daily context here.',
        state: 'unconfigured',
        origin: kind === 'obsidian' ? 'local' : 'mcp',
      })
    );
  }

  const genericMcpRecord = sourceMap.get('mcp');
  if (genericMcpRecord) {
    const serverCount = discovery.servers.length;
    const toolCount = discovery.tools.length;
    const resourceCount = discovery.resources.length;
    const promptCount = discovery.prompts.length;

    sourceMap.set(
      'mcp',
      createSourceRecord('mcp', {
        title: 'MCP surfaces',
        state: serverCount > 0 ? 'available' : 'unconfigured',
        origin: 'mcp',
        summary:
          serverCount > 0
            ? `${serverCount} server${serverCount === 1 ? '' : 's'} configured`
            : 'No MCP servers configured.',
        detail:
          serverCount > 0
            ? `${toolCount} tools, ${resourceCount} resources, and ${promptCount} prompts discovered.`
            : 'Add MCP servers only when you actively need them.',
        stats: {
          serverCount,
          toolCount,
          resourceCount,
          promptCount,
        },
      })
    );
  }

  for (const server of discovery.servers) {
    const serverText = `${server.id} ${server.endpoint ?? ''}`.trim();
    const matchingKind = matchesWorkspaceKind(serverText);
    if (!matchingKind) {
      continue;
    }

    const existing = sourceMap.get(matchingKind);
    const state = server.state === 'reachable' ? 'connected' : server.state === 'degraded' ? 'partial' : 'available';
    const detail = server.stateReason ?? server.lastError ?? server.endpoint ?? 'MCP server configured.';
    const summary =
      state === 'connected'
        ? `Connected via ${server.transport}${server.endpoint ? ` · ${server.endpoint}` : ''}`
        : state === 'partial'
          ? `Partially connected via ${server.transport}`
          : `Configured via ${server.transport}`;

    sourceMap.set(
      matchingKind,
      createSourceRecord(matchingKind, {
        title: existing?.title ?? matchingKind,
        state,
        origin: 'mcp',
        summary,
        detail,
        stats: {
          serverCount: (existing?.stats?.serverCount ?? 0) + 1,
          toolCount: existing?.stats?.toolCount,
          resourceCount: existing?.stats?.resourceCount,
          promptCount: existing?.stats?.promptCount,
        },
      })
    );
  }

  for (const tool of discovery.tools) {
    const matchingKind = matchesWorkspaceKind(`${tool.id} ${tool.title} ${tool.description}`);
    if (!matchingKind) {
      continue;
    }

    const existing = sourceMap.get(matchingKind);
    sourceMap.set(
      matchingKind,
      createSourceRecord(matchingKind, {
        title: existing?.title ?? matchingKind,
        state: existing?.state === 'connected' ? 'connected' : 'available',
        origin: 'mcp',
        summary: existing?.summary ?? `Surface detected through ${tool.id}`,
        detail: existing?.detail ?? tool.description,
        stats: {
          serverCount: existing?.stats?.serverCount,
          toolCount: (existing?.stats?.toolCount ?? 0) + 1,
          resourceCount: existing?.stats?.resourceCount,
          promptCount: existing?.stats?.promptCount,
        },
      })
    );
  }

  for (const resource of discovery.resources) {
    const matchingKind = matchesWorkspaceKind(`${resource.uri} ${resource.name} ${resource.title ?? ''} ${resource.description ?? ''}`);
    if (!matchingKind) {
      continue;
    }

    const existing = sourceMap.get(matchingKind);
    sourceMap.set(
      matchingKind,
      createSourceRecord(matchingKind, {
        title: existing?.title ?? matchingKind,
        state: existing?.state === 'connected' ? 'connected' : 'available',
        origin: 'mcp',
        summary: existing?.summary ?? `Resource surface detected through ${resource.uri}`,
        detail: existing?.detail ?? resource.description ?? resource.name,
        stats: {
          serverCount: existing?.stats?.serverCount,
          toolCount: existing?.stats?.toolCount,
          resourceCount: (existing?.stats?.resourceCount ?? 0) + 1,
          promptCount: existing?.stats?.promptCount,
        },
      })
    );
  }

  for (const prompt of discovery.prompts) {
    const matchingKind = matchesWorkspaceKind(`${prompt.name} ${prompt.title ?? ''} ${prompt.description ?? ''}`);
    if (!matchingKind) {
      continue;
    }

    const existing = sourceMap.get(matchingKind);
    sourceMap.set(
      matchingKind,
      createSourceRecord(matchingKind, {
        title: existing?.title ?? matchingKind,
        state: existing?.state === 'connected' ? 'connected' : 'available',
        origin: 'mcp',
        summary: existing?.summary ?? `Prompt surface detected through ${prompt.name}`,
        detail: existing?.detail ?? prompt.description ?? prompt.name,
        stats: {
          serverCount: existing?.stats?.serverCount,
          toolCount: existing?.stats?.toolCount,
          resourceCount: existing?.stats?.resourceCount,
          promptCount: (existing?.stats?.promptCount ?? 0) + 1,
        },
      })
    );
  }

  return Array.from(sourceMap.values());
}

function buildWorkspaceJobs(now: Date, sources: WorkspaceSourceRecord[]): WorkspaceJobRecord[] {
  const hasGmail = sources.some((source) => source.kind === 'gmail' && source.state !== 'unconfigured');
  const hasCalendar = sources.some((source) => source.kind === 'calendar' && source.state !== 'unconfigured');
  const hasGithub = sources.some((source) => source.kind === 'github' && source.state !== 'unconfigured');
  const hasNotes = sources.some((source) => source.kind === 'obsidian' && source.state !== 'unconfigured');
  const hasAnyConnectedSource = sources.some((source) => source.state === 'connected' || source.state === 'partial');
  const briefHour = parsePositiveInteger(readRuntimeEnvValue('ELYAN_WORKSPACE_BRIEF_HOUR'), 8);
  const briefMinute = parsePositiveInteger(readRuntimeEnvValue('ELYAN_WORKSPACE_BRIEF_MINUTE'), 30);

  return [
    {
      id: 'morning_brief',
      title: 'Morning brief',
      cadence: 'Daily',
      enabled: hasAnyConnectedSource,
      summary: 'Collects the current workspace snapshot into a concise day-start brief.',
      nextRunAt: computeNextDailyRun(now, briefHour % 24, briefMinute % 60),
    },
    {
      id: 'gmail_sync',
      title: 'Inbox sync',
      cadence: 'Every 5 min',
      enabled: hasGmail,
      summary: 'Keeps inbox context fresh for triage and follow-ups.',
      nextRunAt: computeNextIntervalRun(now, 5),
    },
    {
      id: 'calendar_sync',
      title: 'Calendar sync',
      cadence: 'Every 5 min',
      enabled: hasCalendar,
      summary: 'Keeps meetings, deadlines, and prep context current.',
      nextRunAt: computeNextIntervalRun(now, 5),
    },
    {
      id: 'github_digest',
      title: 'GitHub digest',
      cadence: 'Every 10 min',
      enabled: hasGithub,
      summary: 'Summarizes issues, pull requests, and repository movement.',
      nextRunAt: computeNextIntervalRun(now, 10),
    },
    {
      id: 'note_sweep',
      title: 'Note sweep',
      cadence: 'On change',
      enabled: hasNotes,
      summary: 'Surfaces recent vault changes and note snippets.',
    },
    {
      id: 'workspace_digest',
      title: 'Workspace digest',
      cadence: 'On demand',
      enabled: hasAnyConnectedSource,
      summary: 'Rolls the connected sources into a single operator-ready snapshot.',
    },
  ];
}

function buildNextSteps(records: WorkspaceSourceRecord[], brief: WorkspaceBriefRecord[]) {
  const connectedKinds = records.filter((record) => record.state === 'connected' || record.state === 'partial').map((record) => record.kind);

  if (connectedKinds.length === 0) {
    return [
      'Connect GitHub, Obsidian, or MCP surfaces for Gmail, Calendar, and Notion to build a daily brief.',
      'Set `GITHUB_REPO` and `GITHUB_TOKEN` if you want repository context from GitHub.',
      'Set `OBSIDIAN_VAULT_PATH` if you want local note snippets in the workspace brief.',
    ];
  }

  return [
    `Connected sources: ${connectedKinds.join(', ')}.`,
    brief.length > 0 ? 'Open the workspace brief to inspect recent signals before starting a task.' : 'Refresh the workspace status to pull the latest brief.',
    'Use the connected surfaces for inbox, calendar, note, and repository context instead of asking the model to infer it.',
  ];
}

export async function buildWorkspaceStatusSnapshot(runtimeSettings: RuntimeSettings): Promise<WorkspaceStatusSnapshot> {
  const [githubSnapshot, noteSnapshots, mcpDiscovery] = await Promise.all([
    readGitHubSnapshot(),
    readRecentObsidianNotes(),
    discoverMcpSurfaces(runtimeSettings),
  ]);

  const baseSources = buildMcpSourceRecords(mcpDiscovery);
  const sourcesByKind = new Map<WorkspaceSourceKind, WorkspaceSourceRecord>(
    baseSources.map((source) => [source.kind, source])
  );

  if (githubSnapshot) {
    const existing = sourcesByKind.get('github');
    sourcesByKind.set(
      'github',
      createSourceRecord('github', {
        title: 'GitHub',
        state: 'connected',
        origin: 'direct',
        summary: githubSnapshot.fullName,
        detail:
          githubSnapshot.description ||
          'GitHub repository metadata is available for workspace briefing.',
        stats: {
          issueCount: githubSnapshot.openIssuesCount,
        },
        lastSyncAt: githubSnapshot.updatedAt,
      })
    );

    if (existing?.state === 'connected' || existing?.state === 'partial') {
      sourcesByKind.set('github', {
        ...existing,
        state: 'connected',
        origin: 'direct',
        summary: githubSnapshot.fullName,
        detail:
          githubSnapshot.description ||
          existing.detail,
        stats: {
          ...existing.stats,
          issueCount: githubSnapshot.openIssuesCount ?? existing.stats?.issueCount,
        },
        lastSyncAt: githubSnapshot.updatedAt ?? existing.lastSyncAt,
      });
    }
  }

  if (noteSnapshots.length > 0) {
    const existing = sourcesByKind.get('obsidian');
    sourcesByKind.set(
      'obsidian',
      createSourceRecord('obsidian', {
        title: 'Obsidian',
        state: 'connected',
        origin: 'local',
        summary: `${noteSnapshots.length} recent note${noteSnapshots.length === 1 ? '' : 's'}`,
        detail: noteSnapshots[0]
          ? `${noteSnapshots[0].title} · ${noteSnapshots[0].snippet || 'No preview available.'}`
          : 'Local vault is available for briefing.',
        stats: {
          noteCount: noteSnapshots.length,
        },
        lastSyncAt: noteSnapshots[0]?.modifiedAt,
      })
    );

    if (existing?.state === 'connected' || existing?.state === 'partial') {
      sourcesByKind.set('obsidian', {
        ...existing,
        state: 'connected',
        origin: 'local',
        summary: `${noteSnapshots.length} recent note${noteSnapshots.length === 1 ? '' : 's'}`,
        detail: noteSnapshots[0]
          ? `${noteSnapshots[0].title} · ${noteSnapshots[0].snippet || 'No preview available.'}`
          : existing.detail,
        stats: {
          ...existing.stats,
          noteCount: noteSnapshots.length,
        },
        lastSyncAt: noteSnapshots[0]?.modifiedAt ?? existing.lastSyncAt,
      });
    }
  }

  const sources = SOURCE_ORDER.map((kind) => sourcesByKind.get(kind)).filter((source): source is WorkspaceSourceRecord => Boolean(source));

  const now = new Date();
  const jobs = buildWorkspaceJobs(now, sources);
  const brief: WorkspaceBriefRecord[] = [];

  if (githubSnapshot) {
    brief.push({
      kind: 'repo',
      title: githubSnapshot.fullName,
      detail:
        githubSnapshot.openIssuesCount !== undefined
          ? `${githubSnapshot.openIssuesCount} open issue${githubSnapshot.openIssuesCount === 1 ? '' : 's'}`
          : githubSnapshot.description,
      source: 'GitHub',
      timestamp: githubSnapshot.updatedAt,
    });
  }

  for (const note of noteSnapshots) {
    brief.push({
      kind: 'note',
      title: note.title,
      detail: note.snippet || 'No preview available.',
      source: `Obsidian · ${note.path}`,
      timestamp: note.modifiedAt,
    });
  }

  for (const source of sources.filter((entry) => entry.kind !== 'mcp' && (entry.state === 'connected' || entry.state === 'partial'))) {
    brief.push({
      kind: 'surface',
      title: source.title,
      detail: source.detail,
      source: source.kind,
      timestamp: source.lastSyncAt,
    });
  }

  const counts = mergeCounts(sources);
  const ready = counts.connectedSourceCount > 0;

  return {
    ready,
    summary: {
      ...counts,
      jobCount: jobs.length,
      activeJobCount: jobs.filter((job) => job.enabled).length,
      briefItemCount: brief.length,
    },
    sources,
    jobs,
    brief: brief.slice(0, 6),
    nextSteps: buildNextSteps(sources, brief),
  };
}
