const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

function nowIso() {
  return new Date().toISOString();
}

function shortId(prefix) {
  return `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
}

function resolveOperatorRunMode(text, requestedMode = 'auto') {
  if (requestedMode && requestedMode !== 'auto') {
    return requestedMode;
  }

  const normalized = String(text || '').toLowerCase();
  if (/\b(repo|code|bug|test|refactor|implement|patch|commit|pr|pull request)\b/.test(normalized)) {
    return 'code';
  }
  if (/\b(research|source|sources|cite|compare|latest|web|perplexity)\b/.test(normalized)) {
    return 'research';
  }
  return 'cowork';
}

function createStep(title, summary, kind, options = {}) {
  return {
    id: shortId('step'),
    title,
    summary,
    kind,
    status: options.status || 'pending',
    requiresApproval: Boolean(options.requiresApproval),
    riskLevel: options.riskLevel,
  };
}

function buildSteps(mode) {
  if (mode === 'research') {
    return [
      createStep('Clarify research intent', 'Classify freshness and evidence requirements.', 'intent'),
      createStep('Collect sources', 'Use configured live search and browser/crawl capabilities when available.', 'research'),
      createStep('Synthesize with citations', 'Produce a sourced answer or an honest unavailable state.', 'delivery'),
    ];
  }

  if (mode === 'code') {
    return [
      createStep('Inspect repository', 'Read project structure, relevant files, tests, and current git state.', 'repo_inspection'),
      createStep('Plan patch', 'Create a minimal implementation plan that preserves existing architecture.', 'planning'),
      createStep('Execute approved local changes', 'Apply file or terminal changes only through local-agent policy and approval gates.', 'execution', {
        status: 'blocked',
        requiresApproval: true,
        riskLevel: 'write_safe',
      }),
      createStep('Verify and summarize', 'Run focused checks and report changed files, risks, and remaining work.', 'verification'),
    ];
  }

  return [
    createStep('Create project plan', 'Break the request into role-based cowork tasks.', 'planning'),
    createStep('Run cowork team', 'Coordinate artifacts while keeping side effects behind approval boundaries.', 'execution'),
    createStep('Verify project outcome', 'Check the outcome against the original intent and record next steps.', 'verification'),
    createStep('Curate local memory', 'Store durable project facts locally by default.', 'memory'),
  ];
}

function continuitySummary(mode) {
  if (mode === 'research') {
    return 'Research run is tracking source collection, synthesis, and citation-backed follow-up.';
  }
  if (mode === 'code') {
    return 'Coding run is tracking repository inspection, safe patch planning, approval, and verification.';
  }
  return 'Cowork run is tracking project planning, role-based execution, verification, and memory curation.';
}

function buildNextSteps(mode, steps, createdAt) {
  const selectedSteps = mode === 'code'
    ? steps.filter((step) => ['repo_inspection', 'planning', 'verification'].includes(step.kind))
    : steps.filter((step) => step.kind !== 'memory');

  return selectedSteps.map((step) => ({
    id: shortId('item'),
    title: step.title,
    status: step.status === 'blocked' ? 'blocked' : 'open',
    sourceStepId: step.id,
    createdAt,
  }));
}

function createApproval(runId, step) {
  return {
    id: shortId('approval'),
    runId,
    stepId: step.id,
    status: 'pending',
    title: step.title,
    reason: step.summary,
    riskLevel: step.riskLevel || 'write_safe',
    approvalLevel: 'CONFIRM',
    requestedAt: nowIso(),
  };
}

function buildReasoningProfile(mode, steps, text) {
  const normalized = String(text || '').toLowerCase();
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

function buildQualityGates(mode) {
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
      summary: 'Cowork runs must preserve role outputs as inspectable artifacts.',
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

function buildPlanArtifactNotes(mode) {
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

function buildOperatorRun(input) {
  const createdAt = nowIso();
  const mode = resolveOperatorRunMode(input.text, input.mode);
  const id = `run_${Date.now()}_${crypto.randomUUID().slice(0, 8)}`;
  const steps = buildSteps(mode);
  const approvals = steps.filter((step) => step.requiresApproval).map((step) => createApproval(id, step));
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
    source: input.source || 'cli',
    mode,
    status: approvals.length > 0 ? 'blocked' : 'planned',
    title: input.title || String(input.text).slice(0, 80),
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
        content: [stepsWithApprovals.map((step, index) => `${index + 1}. ${step.title}: ${step.summary}`).join('\n'), '', ...planArtifactNotes].join('\n'),
        createdAt,
        metadata: { mode, planArtifactNotes },
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

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function atomicWriteJson(filePath, value) {
  ensureDir(path.dirname(filePath));
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tempPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  fs.renameSync(tempPath, filePath);
}

function createOperatorRunStore(cwd = process.cwd()) {
  const runsDir = path.resolve(cwd, 'storage', 'operator-runs');

  function runPath(runId) {
    return path.join(runsDir, `${runId}.json`);
  }

  function listRuns() {
    if (!fs.existsSync(runsDir)) {
      return [];
    }

    return fs
      .readdirSync(runsDir)
      .filter((entry) => entry.endsWith('.json'))
      .map((entry) => normalizeRun(JSON.parse(fs.readFileSync(path.join(runsDir, entry), 'utf8'))))
      .sort((left, right) => String(right.createdAt).localeCompare(String(left.createdAt)));
  }

  function getRun(runId) {
    const filePath = runPath(runId);
    if (!fs.existsSync(filePath)) {
      return null;
    }

    return normalizeRun(JSON.parse(fs.readFileSync(filePath, 'utf8')));
  }

  function writeRun(run) {
    atomicWriteJson(runPath(run.id), run);
  }

  function createRun(input) {
    const run = buildOperatorRun(input);
    writeRun(run);
    return run;
  }

  function listApprovals() {
    return listRuns().flatMap((run) => run.approvals || []);
  }

  function resolveApproval(approvalId, status) {
    const run = listRuns().find((candidate) => (candidate.approvals || []).some((approval) => approval.id === approvalId));
    if (!run) {
      return null;
    }

    const resolvedAt = nowIso();
    run.approvals = run.approvals.map((approval) =>
      approval.id === approvalId
        ? {
            ...approval,
            status,
            resolvedAt,
            resolvedBy: 'elyan-cli',
          }
        : approval
    );
    run.steps = run.steps.map((step) =>
      step.approvalId === approvalId
        ? {
            ...step,
            status: status === 'approved' ? 'pending' : 'blocked',
          }
        : step
    );
    run.continuity = run.continuity || {
      summary: 'Operator run continuity was created by an earlier runtime.',
      nextSteps: [],
      openItemCount: 0,
      lastActivityAt: resolvedAt,
    };
    run.continuity.nextSteps = (run.continuity.nextSteps || []).map((item) => {
      const linkedStep = run.steps.find((step) => step.id === item.sourceStepId);
      if (!linkedStep) return item;
      return {
        ...item,
        status: linkedStep.status === 'blocked' ? 'blocked' : item.status === 'done' ? 'done' : 'open',
      };
    });
    run.continuity.openItemCount = run.continuity.nextSteps.filter((item) => item.status !== 'done').length;
    run.continuity.lastActivityAt = resolvedAt;
    run.status = status === 'approved' && !run.approvals.some((approval) => approval.status === 'pending') ? 'planned' : 'blocked';
    run.updatedAt = resolvedAt;
    run.notes = [...(run.notes || []), `Approval ${approvalId} was ${status}.`];
    writeRun(run);
    return run.approvals.find((approval) => approval.id === approvalId);
  }

  return {
    runsDir,
    createRun,
    listRuns,
    getRun,
    listApprovals,
    resolveApproval,
  };
}

function normalizeRun(run) {
  if (!run.continuity) {
    run.continuity = {
      summary: 'Operator run continuity was created by an earlier runtime.',
      nextSteps: [],
      openItemCount: 0,
      lastActivityAt: run.updatedAt || nowIso(),
    };
  }
  if (!run.reasoning) {
    run.reasoning = {
      depth: 'standard',
      maxPasses: 3,
      halting: 'Stop when the run state and next step are clear.',
      stabilityGuard: 'Preserve existing approval and verification boundaries.',
      rationale: 'Operator run reasoning was created by an earlier runtime and normalized for v1.3.',
    };
  }
  if (!run.qualityGates) {
    run.qualityGates = [];
  }

  return run;
}

module.exports = {
  buildOperatorRun,
  createOperatorRunStore,
  resolveOperatorRunMode,
};
