export type McpAuditStatus = 'success' | 'error' | 'disabled' | 'timeout' | 'unavailable' | 'closed';

export type McpAuditEntry = {
  serverId: string;
  toolId?: string;
  toolName?: string;
  status: McpAuditStatus;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  errorMessage?: string;
};

export class McpAuditTrail {
  private entries: McpAuditEntry[] = [];

  record(entry: McpAuditEntry) {
    this.entries.push(entry);
  }

  list(): McpAuditEntry[] {
    return [...this.entries];
  }

  clear() {
    this.entries = [];
  }
}
