import type { CapabilityAuditEntry } from './types';

export class CapabilityAuditTrail {
  private entries: CapabilityAuditEntry[] = [];

  record(entry: CapabilityAuditEntry) {
    this.entries.push(entry);
  }

  list(): CapabilityAuditEntry[] {
    return [...this.entries];
  }

  clear() {
    this.entries = [];
  }
}

