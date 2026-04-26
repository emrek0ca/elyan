export type WorkspaceSourceKind = 'gmail' | 'calendar' | 'notion' | 'github' | 'obsidian' | 'mcp';

export type WorkspaceSourceState = 'connected' | 'available' | 'partial' | 'unconfigured' | 'offline';

export type WorkspaceSourceRecord = {
  kind: WorkspaceSourceKind;
  title: string;
  state: WorkspaceSourceState;
  origin: 'direct' | 'mcp' | 'local' | 'derived';
  summary: string;
  detail: string;
  stats?: {
    serverCount?: number;
    toolCount?: number;
    resourceCount?: number;
    promptCount?: number;
    noteCount?: number;
    issueCount?: number;
    pullRequestCount?: number;
  };
  lastSyncAt?: string;
};

export type WorkspaceJobRecord = {
  id: string;
  title: string;
  cadence: string;
  enabled: boolean;
  summary: string;
  nextRunAt?: string;
};

export type WorkspaceBriefRecord = {
  kind: 'note' | 'repo' | 'surface';
  title: string;
  detail: string;
  source: string;
  timestamp?: string;
};

export type WorkspaceStatusSnapshot = {
  ready: boolean;
  summary: {
    configuredSourceCount: number;
    connectedSourceCount: number;
    availableSourceCount: number;
    jobCount: number;
    activeJobCount: number;
    briefItemCount: number;
  };
  sources: WorkspaceSourceRecord[];
  jobs: WorkspaceJobRecord[];
  brief: WorkspaceBriefRecord[];
  nextSteps: string[];
};
