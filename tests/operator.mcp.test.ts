import { beforeEach, describe, expect, it, vi } from 'vitest';

const mcpMocks = vi.hoisted(() => ({
  invokeTool: vi.fn(),
  readResource: vi.fn(),
  getPrompt: vi.fn(),
  close: vi.fn(),
}));

vi.mock('@/core/mcp', async () => {
  const actual = await vi.importActual<typeof import('@/core/mcp')>('@/core/mcp');
  const MockMcpToolRegistry = vi.fn(function MockMcpToolRegistry() {
    return {
      invokeTool: mcpMocks.invokeTool,
      readResource: mcpMocks.readResource,
      getPrompt: mcpMocks.getPrompt,
      close: mcpMocks.close,
    };
  });

  return {
    ...actual,
    readMcpConfigurationSnapshot: vi.fn(() => ({
      status: 'ready',
      configured: true,
      serverCount: 1,
    })),
    readMcpServerConfigs: vi.fn(() => [
      {
        id: 'mock-server',
        transport: 'stdio',
        command: 'node',
        args: [],
        enabled: true,
        connectTimeoutMs: 1_000,
        requestTimeoutMs: 1_000,
        shutdownTimeoutMs: 1_000,
        disabledToolNames: [],
      },
    ]),
    McpToolRegistry: MockMcpToolRegistry,
  };
});

import { buildOrchestrationPlan, runOperatorPreflight, type ExecutionSurfaceSnapshot } from '@/core/orchestration';

function createMcpSurface(): ExecutionSurfaceSnapshot {
  return {
    local: {
      capabilities: [],
      bridgeTools: [],
    },
    mcp: {
      servers: [
        {
          id: 'mock-server',
          transport: 'stdio',
          enabled: true,
          connectTimeoutMs: 1_000,
          requestTimeoutMs: 1_000,
          shutdownTimeoutMs: 1_000,
          disabledToolNames: [],
          state: 'reachable',
        },
      ],
      tools: [
        {
          id: 'mock-server::echo',
          toolName: 'echo',
          title: 'Echo Tool',
          description: 'Echoes input',
          library: 'mcp',
          timeoutMs: 1_000,
          enabled: true,
          source: {
            kind: 'mcp',
            serverId: 'mock-server',
            transport: 'stdio',
          },
        },
      ],
      resources: [],
      resourceTemplates: [
        {
          uriTemplate: 'elyan://projects/{project}',
          name: 'project-template',
          title: 'Project Template',
          description: 'Loads a project record.',
          enabled: true,
          source: {
            kind: 'mcp',
            serverId: 'mock-server',
            transport: 'stdio',
          },
        },
      ],
      prompts: [],
    },
  };
}

describe('Operator MCP preflight', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mcpMocks.invokeTool.mockResolvedValue({
      structuredContent: {
        echoed: 'approved',
      },
    });
    mcpMocks.readResource.mockResolvedValue({
      contents: [
        {
          uri: 'elyan://projects/alpha',
          text: 'Alpha project record',
        },
      ],
    });
    mcpMocks.getPrompt.mockResolvedValue({
      description: 'Prompt response',
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'text',
              text: 'Roadmap summary prompt',
            },
          ],
        },
      ],
    });
    mcpMocks.close.mockResolvedValue(undefined);
  });

  it('requires confirmation before invoking an MCP tool, then executes it with parsed JSON input', async () => {
    const query = 'Run the MCP tool echo with {"message":"approved"}';
    const surface = createMcpSurface();
    const plan = buildOrchestrationPlan(query, 'speed', surface);

    expect(plan.executionPolicy.primary.kind).toBe('mcp_tool');
    expect(plan.executionPolicy.primary.requiresConfirmation).toBe(true);

    const blockedOutcome = await runOperatorPreflight(query, plan.executionPolicy, surface);
    expect(blockedOutcome.sources).toHaveLength(0);
    expect(blockedOutcome.notes).toContain('MCP tool execution requires explicit confirmation before the tool can run.');
    expect(mcpMocks.invokeTool).not.toHaveBeenCalled();

    const approvedOutcome = await runOperatorPreflight(
      query,
      {
        ...plan.executionPolicy,
        primary: {
          ...plan.executionPolicy.primary,
          requiresConfirmation: false,
        },
      },
      surface
    );

    expect(mcpMocks.invokeTool).toHaveBeenCalledWith('mock-server::echo', {
      message: 'approved',
    });
    expect(approvedOutcome.sources).toHaveLength(1);
    expect(approvedOutcome.sources[0]?.url).toBe('mcp://tool/mock-server::echo');
    expect(approvedOutcome.sources[0]?.content).toContain('approved');
  });

  it('expands MCP resource templates from named query arguments', async () => {
    const query = 'Use the MCP template for project=alpha';
    const surface = createMcpSurface();
    const plan = buildOrchestrationPlan(query, 'speed', surface);
    const outcome = await runOperatorPreflight(query, plan.executionPolicy, surface);

    expect(plan.executionPolicy.primary.kind).toBe('mcp_resource_template');
    expect(mcpMocks.readResource).toHaveBeenCalledWith('elyan://projects/alpha');
    expect(outcome.sources).toHaveLength(1);
    expect(outcome.sources[0]?.url).toBe('mcp://resource-template/elyan://projects/alpha');
    expect(outcome.sources[0]?.content).toContain('Alpha project record');
  });

  it('passes named query arguments to MCP prompts', async () => {
    const query = 'Run the MCP prompt topic=roadmap audience=ops';
    const surface: ExecutionSurfaceSnapshot = {
      ...createMcpSurface(),
      mcp: {
        ...createMcpSurface().mcp,
        tools: [],
        resourceTemplates: [],
        prompts: [
          {
            name: 'roadmap-prompt',
            title: 'Roadmap Prompt',
            description: 'Summarizes the current roadmap for a target audience.',
            arguments: [
              { name: 'topic', required: true },
              { name: 'audience', required: true },
            ],
            enabled: true,
            source: {
              kind: 'mcp',
              serverId: 'mock-server',
              transport: 'stdio',
            },
          },
        ],
      },
    };
    const plan = buildOrchestrationPlan(query, 'speed', surface);
    const outcome = await runOperatorPreflight(query, plan.executionPolicy, surface);

    expect(plan.executionPolicy.primary.kind).toBe('mcp_prompt');
    expect(mcpMocks.getPrompt).toHaveBeenCalledWith('roadmap-prompt', {
      topic: 'roadmap',
      audience: 'ops',
    });
    expect(outcome.sources).toHaveLength(1);
    expect(outcome.sources[0]?.url).toBe('mcp://prompt/roadmap-prompt');
    expect(outcome.sources[0]?.content).toContain('Roadmap summary prompt');
  });
});
