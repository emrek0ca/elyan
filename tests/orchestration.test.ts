import { describe, expect, it } from 'vitest';
import { buildEvaluationSignalDraft, buildOrchestrationPlan } from '@/core/orchestration';
import type { ExecutionSurfaceSnapshot } from '@/core/orchestration';

function createSurface(overrides: Record<string, unknown>): ExecutionSurfaceSnapshot {
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
  } as ExecutionSurfaceSnapshot;
}

describe('Orchestration planning', () => {
  it('treats research queries as deep, cloud-preferred work', () => {
    const plan = buildOrchestrationPlan('What changed in AI search this week?', 'research');

    expect(plan.taskIntent).toBe('research');
    expect(plan.intentConfidence).toBe('high');
    expect(plan.uncertainty).toBe('high');
    expect(plan.reasoningDepth).toBe('deep');
    expect(plan.routingMode).toBe('cloud_preferred');
    expect(plan.executionMode).toBe('team');
    expect(plan.teamPolicy.modelRoutingMode).toBe('local_first');
    expect(plan.teamPolicy.requiredRoles).toContain('researcher');
    expect(plan.teamPolicy.requiredRoles).toContain('verifier');
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
    expect(plan.teamPolicy.modelRoutingMode).toBe('local_only');
  });

  it('keeps narrow direct answers on the single-agent path', () => {
    const plan = buildOrchestrationPlan('What is Elyan?', 'speed');

    expect(plan.taskIntent).toBe('direct_answer');
    expect(plan.executionMode).toBe('single');
    expect(plan.teamPolicy.enabledByDefault).toBe(false);
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

  it('treats document and design authoring as a local-first artifact path', () => {
    const plan = buildOrchestrationPlan(
      'Write a design brief in markdown for the product UI',
      'speed',
      createSurface({
        local: {
          capabilities: [
            {
              id: 'markdown_render',
              title: 'Markdown Render',
              description: 'Renders Markdown to sanitized HTML with unified.',
              library: 'unified',
              timeoutMs: 500,
              enabled: true,
            },
            {
              id: 'docx_write',
              title: 'DOCX Write',
              description: 'Creates simple DOCX documents with docx.',
              library: 'docx',
              timeoutMs: 750,
              enabled: true,
            },
          ],
          bridgeTools: [],
        },
      })
    );

    expect(plan.routingMode).toBe('local_first');
    expect(plan.executionPolicy.primary.id).toBe('markdown_render');
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'markdown_render')?.enabled).toBe(true);
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'docx_write')?.enabled).toBe(true);
  });

  it('routes minimum-cost assignment work to the optimization capability', () => {
    const plan = buildOrchestrationPlan(
      'Solve a minimum cost assignment with QUBO for task allocation',
      'speed',
      createSurface({
        local: {
          capabilities: [],
          bridgeTools: [
            {
              id: 'optimization_solve',
              title: 'Optimization Solve',
              description: 'Models assignment and resource allocation problems with QUBO.',
              library: 'elyan-optimization',
              timeoutMs: 3_000,
              enabled: true,
            },
          ],
        },
      })
    );

    expect(plan.taskIntent).toBe('procedural');
    expect(plan.routingMode).toBe('local_first');
    expect(plan.reasoningDepth).toBe('standard');
    expect(plan.executionPolicy.primary.kind).toBe('local_bridge_tool');
    expect(plan.executionPolicy.primary.id).toBe('optimization_solve');
    expect(plan.executionPolicy.shouldRetrieve).toBe(false);
    expect(plan.skillPolicy.selectedSkillId).toBe('optimization_decision');
    expect(plan.capabilityPolicy.find((entry) => entry.capabilityId === 'optimization_solve')?.enabled).toBe(true);
  });

  it('routes best distribution requests to the optimization capability', () => {
    const plan = buildOrchestrationPlan(
      'Find the best distribution of tasks and resources for this project',
      'speed',
      createSurface({
        local: {
          capabilities: [],
          bridgeTools: [
            {
              id: 'optimization_solve',
              title: 'Optimization Solve',
              description: 'Models assignment and resource allocation problems with QUBO.',
              library: 'elyan-optimization',
              timeoutMs: 3_000,
              enabled: true,
            },
          ],
        },
      })
    );

    expect(plan.taskIntent).toBe('procedural');
    expect(plan.executionPolicy.primary.id).toBe('optimization_solve');
    expect(plan.skillPolicy.selectedSkillId).toBe('optimization_decision');
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
        inputTokenDetails: {
          noCacheTokens: undefined,
          cacheReadTokens: undefined,
          cacheWriteTokens: undefined,
        },
        outputTokens: 82,
        outputTokenDetails: {
          textTokens: undefined,
          reasoningTokens: undefined,
        },
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
