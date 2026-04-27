import { randomUUID } from 'crypto';
import type {
  CreateOperatorRunInput,
  OperatorApproval,
  OperatorQualityGate,
  OperatorReasoningProfile,
  OperatorRun,
  OperatorRunMode,
  OperatorRunStep,
  OperatorWorkItem,
} from './run-types';

function nowIso() {
  return new Date().toISOString();
}

function shortId(prefix: string) {
  return `${prefix}_${randomUUID().slice(0, 8)}`;
}

export function resolveOperatorRunMode(text: string, requestedMode: OperatorRunMode): Exclude<OperatorRunMode, 'auto'> {
  if (requestedMode !== 'auto') {
    return requestedMode;
  }

  const normalized = text.toLowerCase();
  if (/\b(repo|code|bug|test|refactor|implement|patch|commit|pr|pull request)\b/.test(normalized)) {
    return 'code';
  }

  if (/\b(research|source|sources|cite|compare|latest|web|perplexity)\b/.test(normalized)) {
    return 'research';
  }

  if (/\b(project|roadmap|plan|cowork|long[- ]running|milestone)\b/.test(normalized)) {
    return 'cowork';
  }

  return 'cowork';
}

function baseSteps(mode: Exclude<OperatorRunMode, 'auto'>): OperatorRunStep[] {
  if (mode === 'research') {
    return [
      {
        id: shortId('step'),
        title: 'Clarify research intent',
        summary: 'Classify the question, required freshness, and evidence threshold.',
        kind: 'intent',
        status: 'pending',
        requiresApproval: false,
      },
      {
        id: shortId('step'),
        title: 'Collect sources',
        summary: 'Use configured live search and browser/crawl capabilities when available.',
        kind: 'research',
        status: 'pending',
        requiresApproval: false,
      },
      {
        id: shortId('step'),
        title: 'Synthesize with citations',
        summary: 'Produce an answer grounded in sources, or report that live evidence is unavailable.',
        kind: 'delivery',
        status: 'pending',
        requiresApproval: false,
      },
    ];
  }

  if (mode === 'code') {
    return [
      {
        id: shortId('step'),
        title: 'Inspect repository',
        summary: 'Read project structure, relevant files, tests, and current git state before edits.',
        kind: 'repo_inspection',
        status: 'pending',
        requiresApproval: false,
      },
      {
        id: shortId('step'),
        title: 'Plan patch',
        summary: 'Create a minimal implementation plan that preserves existing architecture.',
        kind: 'planning',
        status: 'pending',
        requiresApproval: false,
      },
      {
        id: shortId('step'),
        title: 'Execute approved local changes',
        summary: 'Apply file or terminal changes only through local-agent policy and approval gates.',
        kind: 'execution',
        status: 'blocked',
        requiresApproval: true,
        riskLevel: 'write_safe',
      },
      {
        id: shortId('step'),
        title: 'Verify and summarize',
        summary: 'Run focused checks and report changed files, risks, and remaining work.',
        kind: 'verification',
        status: 'pending',
        requiresApproval: false,
      },
    ];
  }

  return [
    {
      id: shortId('step'),
      title: 'Create project plan',
      summary: 'Break the request into planner, researcher, executor, reviewer, verifier, and memory work.',
      kind: 'planning',
      status: 'pending',
      requiresApproval: false,
    },
    {
      id: shortId('step'),
      title: 'Run cowork team',
      summary: 'Coordinate role-based artifacts and keep side effects behind approval boundaries.',
      kind: 'execution',
      status: 'pending',
      requiresApproval: false,
    },
    {
      id: shortId('step'),
      title: 'Verify project outcome',
      summary: 'Check the outcome against the original intent and record next steps.',
      kind: 'verification',
      status: 'pending',
      requiresApproval: false,
    },
    {
      id: shortId('step'),
      title: 'Curate local memory',
      summary: 'Store durable project facts locally without sending private runtime state to hosted services.',
      kind: 'memory',
      status: 'pending',
      requiresApproval: false,
    },
  ];
}

function continuitySummary(mode: Exclude<OperatorRunMode, 'auto'>) {
  if (mode === 'research') {
    return 'Research run is tracking source collection, synthesis, and citation-backed follow-up.';
  }

  if (mode === 'code') {
    return 'Coding run is tracking repository inspection, safe patch planning, approval, and verification.';
  }

  return 'Cowork run is tracking project planning, role-based execution, verification, and memory curation.';
}

function buildNextSteps(mode: Exclude<OperatorRunMode, 'auto'>, steps: OperatorRunStep[], createdAt: string): OperatorWorkItem[] {
  const selectedSteps = mode === 'code'
    ? steps.filter((step) => ['repo_inspection', 'planning', 'verification'].includes(step.kind))
    : steps.filter((step) => step.kind !== 'memory');

  return selectedSteps.map((step) => ({
    id: `item_${randomUUID().slice(0, 8)}`,
    title: step.title,
    status: step.status === 'blocked' ? 'blocked' : 'open',
    sourceStepId: step.id,
    createdAt,
  }));
}

function buildApproval(runId: string, step: OperatorRunStep): OperatorApproval {
  return {
    id: shortId('approval'),
    runId,
    stepId: step.id,
    status: 'pending',
    title: step.title,
    reason: step.summary,
    riskLevel: step.riskLevel ?? 'write_safe',
    approvalLevel: step.riskLevel === 'destructive' || step.riskLevel === 'system_critical' ? 'TWO_FA' : 'CONFIRM',
    requestedAt: nowIso(),
  };
}

function buildReasoningProfile(
  mode: Exclude<OperatorRunMode, 'auto'>,
  steps: OperatorRunStep[],
  text: string
): OperatorReasoningProfile {
  const normalized = text.toLowerCase();
  const hasRiskyStep = steps.some((step) => step.requiresApproval || step.riskLevel);
  const asksForFreshEvidence = /\b(latest|current|recent|today|sources?|cite|research|compare|perplexity)\b/.test(normalized);
  const asksForLongRunningWork = /\b(project|roadmap|milestone|cowork|long[- ]running|memory|follow[- ]?up)\b/.test(normalized);
  const asksForDesignArtifact = /\b(design|prototype|ui|ux|slide|presentation|animation|brand)\b/.test(normalized);

  if (mode === 'code' || hasRiskyStep) {
    return {
      depth: 'deep',
      maxPasses: 5,
      halting: 'Stop after repository inspection, patch planning, approval status, and verification path are explicit.',
      stabilityGuard: 'Keep execution blocked until the requested local side effect passes policy and approval.',
      rationale: 'Code and local mutations need deeper planning because mistakes can alter files, dependencies, git state, or runtime behavior.',
    };
  }

  if (mode === 'research' && asksForFreshEvidence) {
    return {
      depth: 'standard',
      maxPasses: 4,
      halting: 'Stop when source coverage, synthesis, and uncertainty are recorded, or when live evidence is unavailable.',
      stabilityGuard: 'Prefer source-backed retrieval and cite gaps instead of inventing unsupported claims.',
      rationale: 'Research benefits from extra source and synthesis passes, but it should not keep expanding once evidence is sufficient.',
    };
  }

  if (mode === 'cowork' && (asksForLongRunningWork || asksForDesignArtifact)) {
    return {
      depth: 'standard',
      maxPasses: 4,
      halting: 'Stop when the next useful action, owner surface, and verification checkpoint are clear.',
      stabilityGuard: 'Keep private project memory local and separate planning from side-effectful execution.',
      rationale: 'Cowork and design work need iterative planning, but the run should converge on inspectable artifacts and next steps.',
    };
  }

  return {
    depth: 'shallow',
    maxPasses: 2,
    halting: 'Stop once intent, answer path, and next step are clear.',
    stabilityGuard: 'Avoid unnecessary tool use when a direct local answer or short plan is enough.',
    rationale: 'Simple work should stay fast and low-cost instead of using a heavy operator loop.',
  };
}

function buildQualityGates(mode: Exclude<OperatorRunMode, 'auto'>): OperatorQualityGate[] {
  if (mode === 'research') {
    return [
      {
        id: shortId('gate'),
        title: 'Source coverage',
        summary: 'Research output must include usable sources or an explicit unavailable-state explanation.',
        status: 'pending',
      },
      {
        id: shortId('gate'),
        title: 'Citation integrity',
        summary: 'Claims that depend on live evidence must be tied to collected sources.',
        status: 'pending',
      },
    ];
  }

  if (mode === 'code') {
    return [
      {
        id: shortId('gate'),
        title: 'Repository inspection',
        summary: 'Code work must inspect relevant files and current repository state before planning edits.',
        status: 'pending',
      },
      {
        id: shortId('gate'),
        title: 'Approval boundary',
        summary: 'File, terminal, dependency, git, and deploy changes must remain blocked until approval.',
        status: 'blocked',
      },
      {
        id: shortId('gate'),
        title: 'Verification path',
        summary: 'The run must record focused checks or explain why verification could not run.',
        status: 'pending',
      },
    ];
  }

  return [
    {
      id: shortId('gate'),
      title: 'Role artifacts',
      summary: 'Cowork runs must preserve planner, executor, reviewer, verifier, and next-step outputs as inspectable artifacts.',
      status: 'pending',
    },
    {
      id: shortId('gate'),
      title: 'Local memory boundary',
      summary: 'Private project memory must stay local unless the user explicitly chooses to share it.',
      status: 'pending',
    },
  ];
}

function buildPlanArtifactNotes(mode: Exclude<OperatorRunMode, 'auto'>) {
  if (mode === 'research') {
    return [
      'Evidence requirement: sources or an honest unavailable-state explanation.',
      'Quality gates: source coverage and citation integrity.',
    ];
  }

  if (mode === 'code') {
    return [
      'Evidence requirement: repository inspection and focused verification checks.',
      'Quality gates: repository inspection, approval boundary, and verification path.',
    ];
  }

  return [
    'Evidence requirement: role artifacts and a local memory boundary.',
    'Quality gates: inspectable cowork artifacts and no hosted memory spill by default.',
  ];
}

export function buildOperatorRun(input: CreateOperatorRunInput): OperatorRun {
  const createdAt = nowIso();
  const mode = resolveOperatorRunMode(input.text, input.mode);
  const id = `run_${Date.now()}_${randomUUID().slice(0, 8)}`;
  const steps = baseSteps(mode);
  const approvals = steps.filter((step) => step.requiresApproval).map((step) => buildApproval(id, step));
  const stepsWithApprovals = steps.map((step) => {
    const approval = approvals.find((candidate) => candidate.stepId === step.id);
    return approval ? { ...step, approvalId: approval.id } : step;
  });
  const nextSteps = buildNextSteps(mode, stepsWithApprovals, createdAt);
  const reasoning = buildReasoningProfile(mode, stepsWithApprovals, input.text);
  const qualityGates = buildQualityGates(mode);
  const planArtifactNotes = buildPlanArtifactNotes(mode);

  return {
    id,
    version: 1,
    source: input.source,
    mode,
    status: approvals.some((approval) => approval.status === 'pending') ? 'blocked' : 'planned',
    title: input.title ?? input.text.slice(0, 80),
    intent: input.text,
    createdAt,
    updatedAt: createdAt,
    steps: stepsWithApprovals,
    approvals,
    artifacts: [
      {
        id: shortId('artifact'),
        runId: id,
        kind: 'plan',
        title: `${mode} run plan`,
        content: [
          stepsWithApprovals.map((step, index) => `${index + 1}. ${step.title}: ${step.summary}`).join('\n'),
          '',
          ...planArtifactNotes,
        ].join('\n'),
        createdAt,
        metadata: {
          mode,
          planArtifactNotes,
        },
      },
    ],
    verification: {
      status: 'not_run',
      summary: 'Verification has not run yet.',
    },
    continuity: {
      summary: continuitySummary(mode),
      nextSteps,
      openItemCount: nextSteps.filter((step) => step.status !== 'done').length,
      lastActivityAt: createdAt,
    },
    reasoning,
    qualityGates,
    notes: [
      'v1.3 operator runs are local-first and side-effect aware.',
      `Adaptive reasoning profile: ${reasoning.depth}, up to ${reasoning.maxPasses} passes.`,
      'Risky actions must pass typed action, policy, approval, audit, and verification.',
    ],
  };
}
