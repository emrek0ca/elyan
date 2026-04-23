import type { SearchMode } from '@/types/search';
import type {
  CapabilityPolicyEntry,
  EvaluationPolicy,
  IntentConfidence,
  ModelRoutingMode,
  OrchestrationPlan,
  ReasoningDepth,
  TaskIntent,
  UncertaintyLevel,
  UsageBudget,
} from './types';
import type { ExecutionSurfaceSnapshot } from './surface';
import { buildExecutionPolicy } from './execution-policy';

const ORCHESTRATION_STAGES: OrchestrationPlan['stages'] = [
  'intent',
  'routing',
  'retrieval',
  'tooling',
  'synthesis',
  'citation',
  'evaluation',
];

type IntentSignals = {
  comparison: boolean;
  procedural: boolean;
  personalWorkflow: boolean;
  research: boolean;
  documents: boolean;
  urls: boolean;
};

function readIntentSignals(query: string): IntentSignals {
  const normalized = query.toLowerCase();

  return {
    comparison: /(compare|versus|difference|tradeoff|benchmark)/i.test(normalized),
    procedural: /(how to|steps|guide|setup|configure|install|run|fix|read|inspect|summarize|extract)/i.test(
      normalized
    ),
    personalWorkflow: /(my files|local|on my machine|computer|device|workspace|folder|offline|private)/i.test(
      normalized
    ),
    research: /(latest|news|today|current|recent|research|why is|what changed|this week|trend)/i.test(
      normalized
    ),
    documents: /\b(pdf|docx|document|file|csv|spreadsheet)\b/i.test(normalized),
    urls: /https?:\/\//i.test(query),
  };
}

function classifyTaskIntent(query: string): {
  intent: TaskIntent;
  confidence: IntentConfidence;
  signals: IntentSignals;
} {
  const signals = readIntentSignals(query);
  const scores: Record<TaskIntent, number> = {
    direct_answer: 0,
    research: 0,
    comparison: 0,
    procedural: 0,
    personal_workflow: 0,
  };

  if (signals.comparison) {
    scores.comparison += 4;
  }

  if (signals.procedural) {
    scores.procedural += 3;
  }

  if (signals.personalWorkflow) {
    scores.personal_workflow += 5;
  }

  if (signals.research) {
    scores.research += 4;
  }

  if (signals.documents) {
    scores.procedural += 1;
    scores.personal_workflow += 1;
  }

  if (signals.urls) {
    scores.procedural += 1;
  }

  const ranked = (Object.entries(scores) as Array<[TaskIntent, number]>)
    .sort((left, right) => {
      if (right[1] !== left[1]) {
        return right[1] - left[1];
      }

      const priority: TaskIntent[] = [
        'personal_workflow',
        'comparison',
        'research',
        'procedural',
        'direct_answer',
      ];

      return priority.indexOf(left[0]) - priority.indexOf(right[0]);
    });
  const [topIntent, topScore] = ranked[0] ?? ['direct_answer', 0];
  const secondScore = ranked[1]?.[1] ?? 0;
  const confidence: IntentConfidence =
    topScore >= 4 && topScore - secondScore >= 2
      ? 'high'
      : topScore >= 2 || query.trim().length < 48
        ? 'medium'
        : 'low';

  return {
    intent: topScore > 0 ? topIntent : 'direct_answer',
    confidence,
    signals,
  };
}

function resolveReasoningDepth(mode: SearchMode, intent: TaskIntent, query: string): ReasoningDepth {
  if (mode === 'research' || intent === 'comparison' || query.length > 160) {
    return 'deep';
  }

  if (intent === 'procedural' || intent === 'research' || intent === 'personal_workflow') {
    return 'standard';
  }

  return 'shallow';
}

function resolveRoutingMode(intent: TaskIntent, mode: SearchMode): ModelRoutingMode {
  if (intent === 'personal_workflow') {
    return 'local_only';
  }

  if (mode === 'research' || intent === 'research' || intent === 'comparison') {
    return 'cloud_preferred';
  }

  if (intent === 'procedural') {
    return 'balanced';
  }

  return 'local_first';
}

function resolveUncertainty(
  taskIntent: TaskIntent,
  confidence: IntentConfidence,
  reasoningDepth: ReasoningDepth,
  mode: SearchMode
): UncertaintyLevel {
  if (mode === 'research' || taskIntent === 'comparison' || reasoningDepth === 'deep') {
    return 'high';
  }

  if (confidence === 'low' || taskIntent === 'procedural') {
    return 'medium';
  }

  return 'low';
}

function resolveRetrievalPolicy(
  mode: SearchMode,
  taskIntent: TaskIntent,
  reasoningDepth: ReasoningDepth,
  uncertainty: UncertaintyLevel,
  executionPolicy: ReturnType<typeof buildExecutionPolicy>
): OrchestrationPlan['retrieval'] {
  if (!executionPolicy.shouldRetrieve) {
    return {
      rounds: 0,
      maxUrls: 0,
      rerankTopK: 0,
      language: 'tr',
      expandSearchQueries: false,
    };
  }

  const expandSearchQueries = mode === 'research' || taskIntent === 'comparison' || reasoningDepth === 'deep';
  const rounds = mode === 'research' ? 3 : reasoningDepth === 'deep' ? 2 : 1;
  const maxUrls =
    mode === 'research'
      ? 8
      : reasoningDepth === 'deep'
        ? uncertainty === 'high'
          ? 7
          : 6
        : uncertainty === 'medium'
          ? 5
          : 4;
  const rerankTopK = mode === 'research' ? 12 : reasoningDepth === 'deep' ? 10 : 8;

  return {
    rounds,
    maxUrls,
    rerankTopK,
    language: 'tr',
    expandSearchQueries,
  };
}

function resolveCapabilityPolicy(
  taskIntent: TaskIntent,
  mode: SearchMode,
  routingMode: ModelRoutingMode,
  executionPolicy: ReturnType<typeof buildExecutionPolicy>
): CapabilityPolicyEntry[] {
  const shouldEnableTooling =
    taskIntent === 'procedural' ||
    taskIntent === 'personal_workflow' ||
    executionPolicy.preferredOrder.includes('local_bridge_tool');
  const shouldEnableBrowserAutomation =
    (taskIntent === 'personal_workflow' || taskIntent === 'procedural') &&
    executionPolicy.preferredOrder.includes('browser_automation');
  const shouldEnableMcp =
    taskIntent === 'personal_workflow' ||
    executionPolicy.shouldDiscoverMcp ||
    executionPolicy.preferredOrder.some((kind) =>
      ['mcp_tool', 'mcp_prompt', 'mcp_resource', 'mcp_resource_template'].includes(kind)
    );
  const shouldEnableDocx =
    taskIntent === 'procedural' ||
    taskIntent === 'comparison' ||
    executionPolicy.candidates.some((candidate) => candidate.id === 'docx_read');
  const shouldEnablePdf =
    taskIntent === 'procedural' ||
    taskIntent === 'comparison' ||
    executionPolicy.candidates.some((candidate) => candidate.id === 'pdf_extract');
  const shouldEnableCharting =
    taskIntent === 'comparison' || executionPolicy.candidates.some((candidate) => candidate.id === 'chart_generate');
  const shouldEnableRetrievalAssist =
    executionPolicy.shouldRetrieve && (mode === 'research' || taskIntent === 'comparison');
  const shouldEnableWebRead = executionPolicy.preferredOrder.includes('browser_read');
  const shouldEnableCrawler = executionPolicy.preferredOrder.includes('crawl') || shouldEnableRetrievalAssist;
  const shouldEnableLocalBridge = executionPolicy.preferredOrder.includes('local_bridge_tool') || shouldEnableTooling;

  return [
    {
      capabilityId: 'web_crawl',
      family: 'retrieval',
      enabled: shouldEnableCrawler,
      reason: shouldEnableCrawler
        ? 'Research, comparison, and bounded crawl work benefit from broader retrieval.'
        : 'This request already has a narrower execution path than crawl retrieval.',
    },
    {
      capabilityId: 'tool_bridge',
      family: 'tooling',
      enabled: shouldEnableLocalBridge,
      reason: shouldEnableLocalBridge
        ? 'Procedural work and local calculations should use bounded bridge tools before general reasoning.'
        : 'No deterministic local bridge tool is needed for this query.',
    },
    {
      capabilityId: 'mcp_bridge',
      family: 'mcp',
      enabled: shouldEnableMcp,
      reason: shouldEnableMcp
        ? 'Personal workflow and connected-app work may need MCP surface discovery.'
        : 'No MCP surface is required for this query.',
    },
    {
      capabilityId: 'web_read_dynamic',
      family: 'browser',
      enabled: shouldEnableWebRead,
      reason: shouldEnableWebRead
        ? 'Rendered pages should be read with Playwright before broader browser automation.'
        : 'Rendered page reading is unnecessary for this query.',
    },
    {
      capabilityId: 'browser_automation',
      family: 'browser',
      enabled: shouldEnableBrowserAutomation && routingMode !== 'cloud_preferred',
      reason:
        shouldEnableBrowserAutomation && routingMode !== 'cloud_preferred'
          ? 'The request needs controlled browser interaction on the local runtime.'
          : shouldEnableBrowserAutomation
            ? 'Browser automation is withheld because the current routing mode is cloud-preferred.'
            : 'Browser automation is not needed for this query.',
    },
    {
      capabilityId: 'docx_read',
      family: 'documents',
      enabled: shouldEnableDocx,
      reason: shouldEnableDocx
        ? 'DOCX inspection is relevant for the current procedural or comparison request.'
        : 'DOCX inspection is unnecessary for this query.',
    },
    {
      capabilityId: 'pdf_extract',
      family: 'documents',
      enabled: shouldEnablePdf,
      reason: shouldEnablePdf
        ? 'PDF extraction is relevant for the current procedural or comparison request.'
        : 'PDF extraction is unnecessary for this query.',
    },
    {
      capabilityId: 'chart_generate',
      family: 'charts',
      enabled: shouldEnableCharting,
      reason: shouldEnableCharting
        ? 'Comparison and tabular requests can benefit from compact chart summaries.'
        : 'Chart generation is not needed for this query.',
    },
  ];
}

function resolveUsageBudget(
  reasoningDepth: ReasoningDepth,
  retrieval: OrchestrationPlan['retrieval'],
  capabilityPolicy: CapabilityPolicyEntry[],
  evaluation: EvaluationPolicy
): UsageBudget {
  const inference = reasoningDepth === 'deep' ? 4 : reasoningDepth === 'standard' ? 2 : 1;
  const retrievalUnits =
    retrieval.rounds === 0 && retrieval.maxUrls === 0
      ? 0
      : retrieval.rounds + Math.max(1, Math.ceil(retrieval.maxUrls / 4));
  const integrations = capabilityPolicy.filter((entry) => entry.enabled && entry.family !== 'retrieval').length;
  const evaluationUnits =
    (evaluation.collectRetrievalSignals ? 0.5 : 0) +
    (evaluation.collectToolSignals ? 0.5 : 0) +
    (evaluation.captureUsageSignals ? 0.5 : 0);

  return {
    inference,
    retrieval: retrievalUnits,
    integrations,
    evaluation: evaluationUnits,
  };
}

export function buildOrchestrationPlan(
  query: string,
  mode: SearchMode,
  surface?: ExecutionSurfaceSnapshot
): OrchestrationPlan {
  const { intent: taskIntent, confidence: intentConfidence } = classifyTaskIntent(query);
  const reasoningDepth = resolveReasoningDepth(mode, taskIntent, query);
  const routingMode = resolveRoutingMode(taskIntent, mode);
  const uncertainty = resolveUncertainty(taskIntent, intentConfidence, reasoningDepth, mode);
  const executionSurface: ExecutionSurfaceSnapshot =
    surface ?? {
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
    };
  const evaluation: EvaluationPolicy = {
    collectRetrievalSignals: true,
    collectToolSignals: true,
    captureUsageSignals: uncertainty !== 'low',
    promoteLearnings: mode === 'research' || taskIntent === 'comparison',
  };
  const executionPolicy = buildExecutionPolicy(query, mode, executionSurface, {
    taskIntent,
    routingMode,
    uncertainty,
    intentConfidence,
  });
  const retrieval = resolveRetrievalPolicy(mode, taskIntent, reasoningDepth, uncertainty, executionPolicy);
  const capabilityPolicy = resolveCapabilityPolicy(taskIntent, mode, routingMode, executionPolicy);
  const usageBudget = resolveUsageBudget(reasoningDepth, retrieval, capabilityPolicy, evaluation);
  const temperature = uncertainty === 'high' ? 0.15 : reasoningDepth === 'deep' ? 0.25 : 0.2;

  return {
    stages: ORCHESTRATION_STAGES,
    searchRounds: retrieval.rounds,
    maxUrls: retrieval.maxUrls,
    temperature,
    reasoningDepth,
    taskIntent,
    intentConfidence,
    uncertainty,
    routingMode,
    expandSearchQueries: retrieval.expandSearchQueries,
    retrieval,
    capabilityPolicy,
    evaluation,
    usageBudget,
    surface: taskIntent === 'personal_workflow' ? 'local' : 'hosted',
    mode,
    executionPolicy,
  };
}
