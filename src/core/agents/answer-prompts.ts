import type { SearchMode } from '@/types/search';
import type { OrchestrationPlan } from '@/core/orchestration';

type ModeConfig = {
  systemPrompt: string;
  noSourcesPrompt: string;
};

type AnswerPromptContext = {
  plan?: Pick<OrchestrationPlan, 'taskIntent' | 'routingMode' | 'skillPolicy'>;
  operatorNotes?: string[];
};

const MODE_CONFIG: Record<SearchMode, ModeConfig> = {
  speed: {
    systemPrompt: `You are Elyan, a direct-answer assistant.
Answer the user's question using only the provided sources and runtime context.
Stay concise, readable, and specific.
Use Markdown.
Always cite claims with [1], [2], etc.

SOURCES:
{context}`,
    noSourcesPrompt: `You are Elyan, a direct-answer assistant.
Web retrieval is unavailable for this question.
Answer directly from model knowledge and runtime context, keep the response brief, use Markdown, and do not cite anything.
Mention that sources could not be verified, then continue with the best useful answer.`,
  },
  research: {
    systemPrompt: `You are Elyan, a research assistant.
Write a focused, well-structured answer using only the provided sources and runtime context.
Use short sections when helpful.
Use Markdown.
Always cite claims with [1], [2], etc.

SOURCES:
{context}`,
    noSourcesPrompt: `You are Elyan, a research assistant.
Web retrieval is unavailable for this question.
Give the best direct answer you can from model knowledge and runtime context, keep the response brief, use Markdown, and do not cite anything.
Mention that sources could not be verified, then continue with the best useful answer.`,
  },
};

function buildLaneInstruction(plan?: AnswerPromptContext['plan']) {
  if (!plan) {
    return '';
  }

  const instructions: string[] = [];

  if (plan.skillPolicy.resultShape === 'report') {
    instructions.push('Structure the answer as a concise report with clear sections, a short conclusion, and grounded findings.');
  } else if (plan.skillPolicy.resultShape === 'artifact') {
    instructions.push('Prefer copy-ready artifact output over commentary and keep the formatting clean, stable, and reusable.');
  } else {
    instructions.push('Keep the answer direct, useful, and easy to act on.');
  }

  switch (plan.skillPolicy.selectedSkillId) {
    case 'research_companion':
      instructions.push('Separate evidence from inference, call out disagreements, and avoid unsupported claims.');
      break;
    case 'workspace_operator':
      instructions.push('When the task is code, workspace, or design related, give implementation steps, affected areas, and verification notes.');
      break;
    case 'document_inspector':
      instructions.push('When the task is document or design related, use clean Markdown, preserve hierarchy, and make the result ready to reuse.');
      break;
    case 'design_producer':
      instructions.push('Treat design work as a production artifact: audit existing context first, avoid generic AI patterns, specify layout density, motion, responsive states, and verification checks.');
      break;
    case 'optimization_decision':
      instructions.push('Treat optimization work as a hybrid classical and quantum-inspired decision report, not a real quantum hardware claim.');
      instructions.push('State the modeled problem, solver comparison, feasibility, and selected solution explicitly.');
      instructions.push('Call out the QUBO or Ising framing only when it is actually supported by the run output.');
      break;
    case 'browser_operator':
    case 'mcp_connector':
      instructions.push('Keep actions explicit, bounded, and auditable.');
      break;
    case 'general_answer':
      instructions.push('Use the smallest trustworthy answer path and say explicitly when no specialized lane was needed.');
      break;
    default:
      break;
  }

  if (plan.routingMode === 'local_first') {
    instructions.push('Prefer the smallest local path before broader reasoning.');
  }

  return instructions.length > 0 ? `\n${instructions.map((instruction) => `- ${instruction}`).join('\n')}` : '';
}

function buildTechniqueInstruction(plan?: AnswerPromptContext['plan']) {
  const techniques = plan?.skillPolicy.selectedTechniques?.slice(0, 3) ?? [];

  if (techniques.length === 0) {
    return '';
  }

  return `\n${techniques
    .flatMap((technique) => [
      `- Apply ${technique.title}: ${technique.instruction}`,
      `- Output hint for ${technique.title}: ${technique.outputHint}`,
    ])
    .join('\n')}`;
}

function buildFallbackInstruction(hasSources: boolean, plan?: AnswerPromptContext['plan']) {
  if (!plan || plan.skillPolicy.selectedSkillId !== 'general_answer') {
    return '';
  }

  if (hasSources) {
    return '\n- Use the provided sources without pretending a specialized runtime lane was selected.';
  }

  return '\n- State clearly that no specialized lane or verified sources were available, then answer as directly as possible.';
}

function buildOperatorNotes(operatorNotes?: string[]) {
  const notes = operatorNotes?.map((note) => note.trim()).filter(Boolean) ?? [];

  if (notes.length === 0) {
    return '';
  }

  return `\n\nOPERATOR NOTES:\n${notes.map((note) => `- ${note}`).join('\n')}`;
}

export function resolveAnswerPrompt(mode: SearchMode, context: string, hasSources: boolean, options?: AnswerPromptContext) {
  const config = MODE_CONFIG[mode];
  const laneInstruction = buildLaneInstruction(options?.plan);
  const techniqueInstruction = buildTechniqueInstruction(options?.plan);
  const fallbackInstruction = buildFallbackInstruction(hasSources, options?.plan);
  const operatorNotes = buildOperatorNotes(options?.operatorNotes);
  const basePrompt = hasSources ? config.systemPrompt.replace('{context}', context) : config.noSourcesPrompt;

  return `${basePrompt}${laneInstruction}${techniqueInstruction}${fallbackInstruction}${operatorNotes}`;
}
