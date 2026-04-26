import { buildBuiltinSkillCatalog } from './catalog';
import { readMcpConfigurationSnapshot } from '@/core/mcp';
import type { SkillManifest, SkillSelectionInput } from './types';
import type {
  SkillExecutionCandidate,
  SkillExecutionDecision,
  SkillExecutionStage,
} from '@/core/orchestration/types';

function normalizeText(value: string) {
  return value.toLowerCase();
}

function extractSignals(query: string) {
  const normalized = normalizeText(query);

  return {
    hasUrl: /https?:\/\//i.test(query),
    hasDocumentToken: /\b(pdf|docx|document|file|csv|spreadsheet|table)\b/i.test(normalized),
    hasMcpToken: /\b(mcp|integration|prompt|resource|template|tool|connect|workspace|app)\b/i.test(normalized),
    hasActionToken: /\b(click|fill|submit|open|navigate|send|create|update|delete|write|save|install|configure|run)\b/i.test(
      normalized
    ),
    hasMathToken: /\b(calculate|math|sum|subtract|multiply|divide|percentage|ratio|decimal|precision)\b/i.test(
      normalized
    ),
  };
}

function countKeywordHits(query: string, keywords: string[]) {
  const normalized = normalizeText(query);
  let score = 0;

  for (const keyword of keywords) {
    if (normalized.includes(normalizeText(keyword))) {
      score += 1;
    }
  }

  return score;
}

function determineBoundary(skill: SkillManifest): SkillExecutionDecision['policyBoundary'] {
  return skill.policyBoundary;
}

function materializeStages(skill: SkillManifest, requiresConfirmation: boolean): SkillExecutionStage[] {
  return skill.stageTemplates.map((stage) => ({
    id: stage.id,
    title: stage.title,
    summary: stage.summary,
    kind: stage.kind,
    capabilityId: stage.capabilityId,
    requiresConfirmation: requiresConfirmation && stage.requiresConfirmation,
  }));
}

function buildCandidateReason(
  skill: SkillManifest,
  query: string,
  signals: ReturnType<typeof extractSignals>,
  mcpConfiguration = readMcpConfigurationSnapshot()
) {
  const hits = skill.triggers.keywords.filter((keyword) => normalizeText(query).includes(normalizeText(keyword))).slice(0, 3);
  const reasons: string[] = [];

  if (skill.triggers.intents.length > 0) {
    reasons.push(`intent match: ${skill.triggers.intents.join(', ')}`);
  }

  if (hits.length > 0) {
    reasons.push(`keyword match: ${hits.join(', ')}`);
  }

  if (signals.hasUrl && skill.triggers.urlSensitive) {
    reasons.push('url-sensitive path');
  }

  if (signals.hasDocumentToken && skill.triggers.documentSensitive) {
    reasons.push('document-sensitive path');
  }

  if (signals.hasMcpToken && skill.triggers.mcpSensitive) {
    reasons.push('mcp-sensitive path');
  }

  if (skill.domain === 'mcp') {
    if (signals.hasMcpToken && mcpConfiguration.configured) {
      reasons.push(`live MCP surface available: ${mcpConfiguration.serverCount} configured`);
    }
    if (mcpConfiguration.configured) {
      reasons.push(`configured MCP servers: ${mcpConfiguration.serverCount}`);
    } else if (mcpConfiguration.status === 'unavailable') {
      reasons.push('MCP config unavailable');
    } else {
      reasons.push('no MCP servers configured');
    }
  }

  if (signals.hasActionToken && skill.triggers.actionSensitive) {
    reasons.push('action-sensitive path');
  }

  if (reasons.length === 0) {
    return 'fallback skill';
  }

  return reasons.join('; ');
}

function scoreSkill(
  skill: SkillManifest,
  input: SkillSelectionInput,
  signals: ReturnType<typeof extractSignals>,
  mcpConfiguration = readMcpConfigurationSnapshot()
) {
  let score = skill.selectionWeight;
  const mcpSurface = input.surface?.mcp;

  score += countKeywordHits(input.query, skill.triggers.keywords) * 8;

  if (skill.triggers.intents.includes(input.taskIntent)) {
    score += 16;
  }

  if (input.mode === 'research' && skill.domain === 'research') {
    score += 12;
  }

  if (signals.hasUrl && skill.triggers.urlSensitive) {
    score += 8;
  }

  if (signals.hasDocumentToken && skill.triggers.documentSensitive) {
    score += 8;
  }

  if (signals.hasMcpToken && skill.triggers.mcpSensitive) {
    score += 8;
  }

  if (signals.hasActionToken && skill.triggers.actionSensitive) {
    score += 8;
  }

  if (signals.hasMathToken && skill.domain === 'calculation') {
    score += 18;
  }

  if (input.taskIntent === 'personal_workflow' && skill.domain === 'operator') {
    score += 10;
  }

  if (input.taskIntent === 'comparison' && skill.domain === 'research') {
    score += 8;
  }

  if (input.mode === 'research' && skill.domain === 'research' && /\b(crawl|site|page|pages)\b/i.test(input.query)) {
    score += 24;
  }

  if (input.taskIntent === 'direct_answer' && skill.domain === 'general') {
    score += 10;
  }

  if (skill.domain === 'mcp') {
    const hasLiveMcpSurface =
      mcpSurface &&
      (mcpSurface.servers > 0 ||
        mcpSurface.tools > 0 ||
        mcpSurface.resources > 0 ||
        mcpSurface.resourceTemplates > 0 ||
        mcpSurface.prompts > 0);

    if (hasLiveMcpSurface && mcpSurface.discovery?.status === 'degraded') {
      score += 10;
    } else if (hasLiveMcpSurface) {
      score += 18;
    }

    if (mcpConfiguration.configured) {
      score += 12;
    } else if (mcpConfiguration.status === 'unavailable') {
      score -= 10;
    } else {
      score -= 14;
    }
  }

  return score;
}

export class SkillRegistry {
  private readonly definitions = new Map<string, SkillManifest>();

  constructor(definitions = buildBuiltinSkillCatalog()) {
    for (const definition of definitions) {
      this.register(definition);
    }
  }

  register(definition: SkillManifest) {
    if (this.definitions.has(definition.id)) {
      throw new Error(`Skill already registered: ${definition.id}`);
    }

    this.definitions.set(definition.id, definition);
  }

  get(skillId: string) {
    const definition = this.definitions.get(skillId);
    if (!definition) {
      throw new Error(`Skill not found: ${skillId}`);
    }

    return definition;
  }

  list(options?: { includeDisabled?: boolean }) {
    const manifests = [...this.definitions.values()].sort(
      (left, right) => right.selectionWeight - left.selectionWeight || left.title.localeCompare(right.title)
    );

    if (options?.includeDisabled) {
      return manifests;
    }

    return manifests.filter((skill) => skill.enabled);
  }

  select(input: SkillSelectionInput): SkillExecutionDecision {
    const signals = extractSignals(input.query);
    const mcpConfiguration = readMcpConfigurationSnapshot();
    const candidates = this.list({ includeDisabled: true })
      .map((skill) => ({
        skill,
        score: scoreSkill(skill, input, signals, mcpConfiguration),
        reason: buildCandidateReason(skill, input.query, signals, mcpConfiguration),
      }))
      .filter(({ skill }) => skill.enabled)
      .sort((left, right) => right.score - left.score || right.skill.selectionWeight - left.skill.selectionWeight);

    const selected = candidates[0]?.skill ?? this.get('general_answer');
    const requiresConfirmation =
      selected.externalActionsAllowed && signals.hasActionToken;
    const fallbackReason =
      selected.id === 'general_answer'
        ? 'No specialized skill scored above the fallback path.'
        : undefined;

    const decisionSummary =
      selected.id === 'general_answer'
        ? 'General answer path selected.'
        : `${selected.title} selected for ${selected.policyBoundary} execution.`;

    const mcpNotes =
      selected.id === 'mcp_connector' && !mcpConfiguration.configured && !(input.surface?.mcp?.servers ?? 0)
        ? [
            mcpConfiguration.status === 'unavailable'
              ? 'MCP connector selected, but MCP configuration could not be loaded.'
              : 'MCP connector selected, but no MCP servers are configured yet.',
          ]
        : [];

    const candidatePayload: SkillExecutionCandidate[] = candidates.map(({ skill, score, reason }) => ({
      skillId: skill.id,
      title: skill.title,
      version: skill.version,
      domain: skill.domain,
      policyBoundary: skill.policyBoundary,
      outputShape: skill.outputShape,
      preferredCapabilityIds: [...skill.preferredCapabilityIds],
      score,
      reason,
      enabled: skill.enabled,
      localOnly: skill.localOnly,
      sharedAllowed: skill.sharedAllowed,
    }));

    return {
      selectedSkillId: selected.id,
      selectedSkillTitle: selected.title,
      selectedSkillVersion: selected.version,
      resultShape: selected.outputShape,
      policyBoundary: determineBoundary(selected),
      preferredCapabilityIds: [...selected.preferredCapabilityIds],
      requiresConfirmation,
      decisionSummary,
      fallbackReason,
      notes: [
        `Selected skill: ${selected.title}.`,
        selected.externalActionsAllowed
          ? 'External actions stay explicit and bounded.'
          : 'The selected skill stays local and deterministic.',
        ...mcpNotes,
        selected.preferredCapabilityIds.length > 0
          ? `Preferred capabilities: ${selected.preferredCapabilityIds.join(', ')}.`
          : 'No downstream capability preference was needed.',
      ],
      candidates: candidatePayload,
      stages: materializeStages(selected, requiresConfirmation),
    };
  }
}

export const skillRegistry = new SkillRegistry();

export function buildSkillExecutionDecision(input: SkillSelectionInput): SkillExecutionDecision {
  return skillRegistry.select(input);
}
