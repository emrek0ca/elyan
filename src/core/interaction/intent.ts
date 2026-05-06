import type { SearchMode } from '@/types/search';
import type {
  ControlPlaneInteractionIntent,
  ControlPlaneMemoryKind,
} from '@/core/control-plane/types';

export type InteractionClassification = {
  intent: ControlPlaneInteractionIntent;
  resolvedMode: SearchMode;
  confidence: 'low' | 'medium' | 'high';
  notes: string[];
};

function normalizeText(value: string) {
  return value.trim().toLowerCase();
}

function hasAny(query: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(query));
}

export function classifyInteractionIntent(
  query: string,
  modeHint?: SearchMode
): InteractionClassification {
  const normalized = normalizeText(query);
  const notes: string[] = [];
  const researchSignals = hasAny(normalized, [
    /\b(latest|recent|current|today|this week|this month|research|compare|versus|difference|trend|news)\b/i,
    /\b(why did|what changed|what's changed|what is changing|how has)\b/i,
  ]);
  const toolSignals = hasAny(normalized, [
    /\b(file|folder|rename|move|delete|trash|create|update|edit|fix|install|configure|run|launch|open|close)\b/i,
    /\b(click|type|submit|copy|paste|browser|desktop|window|workspace)\b/i,
    /\b(code|repo|repository|branch|commit|diff|patch|refactor|review|debug|test|build|lint|deploy)\b/i,
    /\b(document|docs?|docx|markdown|md|spec|brief|proposal|rfc|prd|readme|outline)\b/i,
    /\b(design|layout|wireframe|mockup|ui|ux|figma|component|typography|spacing|palette|style guide)\b/i,
  ]);
  const followUpSignals =
    query.trim().length < 80 &&
    hasAny(normalized, [/\b(what about|and what|also|how about|more detail|clarify)\b/i]) &&
    /\?$/.test(query.trim());

  if (modeHint === 'research') {
    notes.push('Mode hint favors research.');
  }

  if (researchSignals || modeHint === 'research') {
    return {
      intent: 'research',
      resolvedMode: 'research',
      confidence: researchSignals ? 'high' : 'medium',
      notes,
    };
  }

  if (followUpSignals) {
    return {
      intent: 'follow_up_question',
      resolvedMode: 'speed',
      confidence: 'medium',
      notes: ['Follow-up phrasing detected.'],
    };
  }

  if (toolSignals) {
    return {
      intent: 'tool_action',
      resolvedMode: 'speed',
      confidence: 'high',
      notes: ['Operational or local tool request detected.'],
    };
  }

  return {
    intent: 'direct_answer',
    resolvedMode: 'speed',
    confidence: query.trim().length < 48 ? 'medium' : 'low',
    notes: modeHint ? [`Mode hint: ${modeHint}.`] : [],
  };
}

export function deriveMemoryKind(intent: ControlPlaneInteractionIntent, query: string): ControlPlaneMemoryKind {
  const normalized = normalizeText(query);

  if (intent === 'research') {
    return 'recent';
  }

  if (hasAny(normalized, [/\b(always|prefer|remember|use this|don't use|do not use|my preference)\b/i])) {
    return 'preference';
  }

  if (hasAny(normalized, [/\b(project|roadmap|workspace|repo|client|feature)\b/i])) {
    return 'project';
  }

  if (hasAny(normalized, [/\b(routine|daily|weekly|every time|workflow|checklist)\b/i])) {
    return 'routine';
  }

  return 'recent';
}

export function buildInteractionThreadTitle(query: string) {
  const compact = query.trim().replace(/\s+/g, ' ');
  return compact.length > 72 ? `${compact.slice(0, 69)}...` : compact;
}

export function buildMemorySummary(text: string, limit = 220) {
  const compact = text.trim().replace(/\s+/g, ' ');
  return compact.length > limit ? `${compact.slice(0, limit - 3)}...` : compact;
}
