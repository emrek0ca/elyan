import { z } from 'zod';
import {
  mcpToolSourceSchema,
  mcpToolManifestSchema,
  toolManifestSchema,
  type McpToolManifest,
  type ToolManifest,
} from '../mcp/types';

type LocalToolLike = {
  id: string;
  title: string;
  description: string;
  library: string;
  timeoutMs: number;
  enabled: boolean;
};

type LocalCapabilityToolManifest = Omit<ToolManifest, 'source'> & {
  source: {
    kind: 'local';
    scope: 'capability';
  };
};

type LocalBridgeToolManifest = Omit<ToolManifest, 'source'> & {
  source: {
    kind: 'local';
    scope: 'bridge';
  };
};

export function normalizeLocalToolCatalog(capabilities: LocalToolLike[]): LocalCapabilityToolManifest[] {
  return capabilities.map((capability) => {
    return toolManifestSchema.parse({
      id: capability.id,
      title: capability.title,
      description: capability.description,
      library: capability.library,
      timeoutMs: capability.timeoutMs,
      enabled: capability.enabled,
      source: {
        kind: 'local',
        scope: 'capability',
      } as const,
    }) as LocalCapabilityToolManifest;
  });
}

export function normalizeLocalBridgeCatalog(tools: LocalToolLike[]): LocalBridgeToolManifest[] {
  return tools.map((tool) => {
    return toolManifestSchema.parse({
      id: tool.id,
      title: tool.title,
      description: tool.description,
      library: tool.library,
      timeoutMs: tool.timeoutMs,
      enabled: tool.enabled,
      source: {
        kind: 'local',
        scope: 'bridge',
      } as const,
    }) as LocalBridgeToolManifest;
  });
}

export function normalizeMcpToolCatalog(tools: McpToolManifest[]): McpToolManifest[] {
  return tools.map((tool) =>
    mcpToolManifestSchema.parse({
      ...tool,
      source: mcpToolSourceSchema.parse(tool.source),
    })
  );
}

export function mergeToolCatalogs(...catalogs: ToolManifest[][]): ToolManifest[] {
  const seen = new Set<string>();
  const merged: ToolManifest[] = [];

  for (const catalog of catalogs) {
    for (const entry of catalog) {
      if (seen.has(entry.id)) {
        continue;
      }

      seen.add(entry.id);
      merged.push(entry);
    }
  }

  return merged;
}

export const toolCatalogSchema = z.array(toolManifestSchema);
