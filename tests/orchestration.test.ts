import { describe, expect, it } from 'vitest';
import { buildEvaluationSignalDraft, buildOrchestrationPlan } from '@/core/orchestration';
import type { ExecutionSurfaceSnapshot } from '@/core/orchestration';

function createSurface(overrides: Partial<ExecutionSurfaceSnapshot>): ExecutionSurfaceSnapshot {
  return {
    local: {
      capabilities: [],
      bridgeTools: [],
    },
    mcp: {
      servers: [],
      tools: [],
      resources: [],
      resourceTemplates: [],
      prompts: [],
    },
    ...overrides,
  };
}

describe('Orchestration planning', () => {
  it('treats research queries as deep, cloud-preferred work', () => {
    const plan = buildOrchestrationPlan('What changed in AI search this week?', 'research');

    expect(plan.taskIntent).toBe('research');
    expect(plan.intentConfidence).toBe('high');
    expect(plan.uncertainty).toBe('high');
    expect(plan.reasoningDepth).toBe('deep');
    expect(plan.routingMode).toBe('cloud_preferred');
    expect(plan.skillPolicy.selectedSkillId).toBe('research_companion');
    expect(plan.skillPolicy.resultShape).toBe('report');
    expect(plan.stages).toEqual([
      'intent',
      'routing',
      'retrieval',
      'tooling',
      'synthesis',
      'citation',
      'evaluation',
    ]);
    expect(plan.expandSearchQueries).toBe(true);
    expect(plan.retrieval.rounds).toBe(3);
    expect(plan.retrieval.rerankTopK).toBe(12);
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'web_crawl')?.enabled).toBe(true);
    expect(plan.usageBudget.inference).toBe(4);
  });

  it('biases personal workflow queries toward local-only routing', () => {
    const plan = buildOrchestrationPlan('Work on my files locally', 'speed');

    expect(plan.taskIntent).toBe('personal_workflow');
    expect(plan.routingMode).toBe('local_only');
    expect(plan.surface).toBe('local');
    expect(plan.skillPolicy.selectedSkillId).toBe('workspace_operator');
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'mcp_bridge')?.enabled).toBe(true);
  });

  it('prefers browser read when a URL needs rendered inspection', () => {
    const plan = buildOrchestrationPlan(
      'Read this page and summarize it: https://example.com',
      'speed',
      createSurface({
        local: {
          capabilities: [
            {
              id: 'web_read_dynamic',
              title: 'Web Read Dynamic',
              description: 'Loads a rendered page with Playwright and extracts the visible content.',
              library: 'playwright',
              timeoutMs: 12_500,
              enabled: true,
            },
          ],
          bridgeTools: [],
        },
      })
    );

    expect(plan.executionPolicy.primary.kind).toBe('browser_read');
    expect(plan.executionPolicy.preferredOrder[0]).toBe('browser_read');
    expect(plan.skillPolicy.selectedSkillId).toBe('browser_operator');
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'web_read_dynamic')?.enabled).toBe(true);
  });

  it('prefers crawl when a multi-page site request is detected', () => {
    const plan = buildOrchestrationPlan(
      'Crawl this site and collect all page titles: https://example.com',
      'research',
      createSurface({
        local: {
          capabilities: [
            {
              id: 'web_crawl',
              title: 'Web Crawl',
              description: 'Crawls same-domain pages with Crawlee and extracts readable HTML content.',
              library: 'crawlee',
              timeoutMs: 12_500,
              enabled: true,
            },
          ],
          bridgeTools: [],
        },
      })
    );

    expect(plan.executionPolicy.primary.kind).toBe('crawl');
    expect(plan.executionPolicy.preferredOrder[0]).toBe('crawl');
    expect(plan.skillPolicy.selectedSkillId).toBe('research_companion');
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'web_crawl')?.enabled).toBe(true);
  });

  it('selects MCP prompt or resource objects when live manifests are present', () => {
    const plan = buildOrchestrationPlan(
      'Use the MCP prompt to summarize the connected workspace',
      'speed',
      createSurface({
        mcp: {
          servers: [
            {
              id: 'mock-server',
              transport: 'stdio',
              enabled: true,
              connectTimeoutMs: 1000,
              requestTimeoutMs: 1000,
              shutdownTimeoutMs: 1000,
              disabledToolNames: [],
            },
          ],
          tools: [],
          resources: [
            {
              uri: 'mcp://workspace/state',
              name: 'knowledge-base',
              title: 'Knowledge Base',
              description: 'Connected reference corpus.',
              enabled: true,
              source: {
                kind: 'mcp',
                serverId: 'mock-server',
                transport: 'stdio',
              },
            },
          ],
          resourceTemplates: [],
          prompts: [
            {
              name: 'summary-template',
              title: 'Summary Template',
              description: 'Summarizes the current workspace.',
              arguments: [],
              enabled: true,
              source: {
                kind: 'mcp',
                serverId: 'mock-server',
                transport: 'stdio',
              },
            },
          ],
        },
      })
    );

    expect(plan.executionPolicy.primary.kind).toBe('mcp_prompt');
    expect(plan.executionPolicy.preferredOrder).toContain('mcp_prompt');
    expect(plan.executionPolicy.shouldDiscoverMcp).toBe(false);
    expect(plan.skillPolicy.selectedSkillId).toBe('mcp_connector');
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'mcp_bridge')?.enabled).toBe(true);
  });

  it('skips web retrieval when a deterministic local bridge tool already covers the request', () => {
    const plan = buildOrchestrationPlan(
      'Calculate 1.5 + 2.5 with decimal precision',
      'speed',
      createSurface({
        local: {
          capabilities: [],
          bridgeTools: [
            {
              id: 'math_decimal',
              title: 'Decimal Math',
              description: 'Performs high precision decimal arithmetic.',
              library: 'decimal.js',
              timeoutMs: 250,
              enabled: true,
            },
          ],
        },
      })
    );

    expect(plan.executionPolicy.primary.kind).toBe('local_bridge_tool');
    expect(plan.executionPolicy.primary.id).toBe('math_decimal');
    expect(plan.executionPolicy.shouldRetrieve).toBe(false);
    expect(plan.skillPolicy.selectedSkillId).toBe('deterministic_math');
    expect(plan.retrieval.rounds).toBe(0);
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'tool_bridge')?.enabled).toBe(true);
  });

  it('selects PDF extraction as a local document path without broad retrieval', () => {
    const plan = buildOrchestrationPlan(
      'Extract the PDF document and summarize the file',
      'speed',
      createSurface({
        local: {
          capabilities: [
            {
              id: 'pdf_extract',
              title: 'PDF Extract',
              description: 'Extracts readable text from PDF files.',
              library: 'unpdf',
              timeoutMs: 2_000,
              enabled: true,
            },
          ],
          bridgeTools: [],
        },
      })
    );

    expect(plan.executionPolicy.primary.kind).toBe('local_capability');
    expect(plan.executionPolicy.primary.id).toBe('pdf_extract');
    expect(plan.executionPolicy.shouldRetrieve).toBe(false);
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'pdf_extract')?.enabled).toBe(true);
  });

  it('builds a structured evaluation draft for a retrieved hosted answer', () => {
    const plan = buildOrchestrationPlan('What changed in AI search this week?', 'research', createSurface({}));
    const draft = buildEvaluationSignalDraft({
      requestId: 'req_42',
      mode: 'research',
      plan,
      surface: createSurface({}),
      searchAvailable: true,
      operatorNotes: ['broad retrieval was required'],
      modelProvider: 'openai',
      modelId: 'gpt-4.1',
      text: 'The answer is now more accurate [1] and the citations are cleaner [2].',
      queryLength: 37,
      latencyMs: 1250,
      totalUsage: {
        inputTokens: 128,
        outputTokens: 82,
        totalTokens: 210,
      },
      toolCallCount: 1,
      toolResultCount: 1,
      sourcesCount: 2,
    });

    expect(draft.mode).toBe('research');
    expect(draft.surface).toBe(plan.surface);
    expect(draft.quality).toBe('good');
    expect(draft.promotionCandidate).toBe(true);
    expect(draft.retrieval.citationCount).toBe(2);
    expect(draft.model.modelId).toBe('gpt-4.1');
    expect(draft.notes.join(' ')).toContain('Retrieved sources: 2. Citations: 2.');
  });
});
