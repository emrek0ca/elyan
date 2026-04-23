import {
  mergeToolCatalogs,
  normalizeLocalBridgeCatalog,
  normalizeLocalToolCatalog,
  normalizeMcpToolCatalog,
} from '../tools/catalog';
import { normalizeMcpServerManifest } from './config';
import { type McpServerConfig, type McpToolManifest, type ToolManifest } from './types';

function dedupeByKey<T>(items: T[], keySelector: (item: T) => string): T[] {
  const seen = new Set<string>();
  const deduped: T[] = [];

  for (const item of items) {
    const key = keySelector(item);
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(item);
  }

  return deduped;
}

export function buildLocalCapabilityCatalog(
  capabilities: Array<{
    id: string;
    title: string;
    description: string;
    library: string;
    timeoutMs: number;
    enabled: boolean;
  }>
): ToolManifest[] {
  return normalizeLocalToolCatalog(capabilities);
}

export function buildLocalBridgeCatalog(
  tools: Array<{
    id: string;
    title: string;
    description: string;
    library: string;
    timeoutMs: number;
    enabled: boolean;
  }>
): ToolManifest[] {
  return normalizeLocalBridgeCatalog(tools);
}

export function buildConfiguredMcpServerCatalog(configs: McpServerConfig[]) {
  return configs.map((config) => normalizeMcpServerManifest(config));
}

export function buildLiveMcpToolCatalog(tools: McpToolManifest[]): McpToolManifest[] {
  return dedupeByKey(normalizeMcpToolCatalog(tools), (tool) => tool.id);
}

export function buildUnifiedToolCatalog(...catalogs: ToolManifest[][]): ToolManifest[] {
  return mergeToolCatalogs(...catalogs);
}
