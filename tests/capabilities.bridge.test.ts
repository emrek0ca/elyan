import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry, buildCapabilityDirectorySnapshot } from '@/core/capabilities';

describe('Bridge capabilities', () => {
  it('executes bridge tools with the same typed helpers', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const math = await registry.execute('tool_bridge', {
      toolId: 'math_exact',
      input: {
        expression: '2 + 2 * 3',
      },
    });

    const manifest = await registry.execute('mcp_bridge', {
      includeManifest: true,
    });

    expect(math.result.value).toBe('8');
    expect(manifest.tools.some((tool) => tool.id === 'chart_generate')).toBe(true);
    expect(manifest.tools.every((tool) => tool.source.kind === 'local')).toBe(true);
    expect(manifest.mcpServers).toEqual([]);
    expect(manifest.mcpTools).toEqual([]);
    expect(manifest.mcpResources).toEqual([]);
    expect(manifest.mcpResourceTemplates).toEqual([]);
    expect(manifest.mcpPrompts).toEqual([]);
    expect(manifest.aiSdkToolNames).toEqual(
      expect.arrayContaining(['math_exact', 'math_decimal', 'csv_parse', 'csv_export', 'chart_generate'])
    );
  });

  it('keeps the local directory readable when MCP config is invalid', async () => {
    const previous = process.env.ELYAN_MCP_SERVERS;
    process.env.ELYAN_MCP_SERVERS = '{invalid-json';

    try {
      const snapshot = await buildCapabilityDirectorySnapshot(true);

      expect(snapshot.mcpStatus).toBe('unavailable');
      expect(snapshot.discovery.mcp.status).toBe('unavailable');
      expect(snapshot.discovery.mcp.error).toMatch(/Invalid ELYAN_MCP_SERVERS/i);
      expect(snapshot.local.bridgeTools.some((tool) => tool.id === 'math_exact')).toBe(true);
      expect(snapshot.skills.summary.builtInSkillCount).toBeGreaterThan(0);
      expect(snapshot.skills.summary.installedSkillCount).toBeGreaterThan(0);
    } finally {
      process.env.ELYAN_MCP_SERVERS = previous;
    }
  });
});
