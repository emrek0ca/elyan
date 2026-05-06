import { z } from 'zod';
import type { CapabilityCategory } from './types';

export const capabilityLibraryStatusSchema = z.enum(['active', 'planned']);

export const capabilityLibraryStrategySchema = z.object({
  category: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  libraries: z.array(z.object({
    name: z.string().min(1),
    status: capabilityLibraryStatusSchema,
    purpose: z.string().min(1),
  })).min(1),
  guardrail: z.string().min(1),
});

export type CapabilityLibraryStatus = z.output<typeof capabilityLibraryStatusSchema>;
export type CapabilityLibraryStrategy = z.output<typeof capabilityLibraryStrategySchema> & {
  category: CapabilityCategory | 'code' | 'design' | 'process' | 'validation';
};

const strategies: CapabilityLibraryStrategy[] = [
  {
    category: 'research',
    title: 'Research and source collection',
    summary: 'Use existing crawler, parser, rendered browser, and citation paths before adding custom retrieval code.',
    libraries: [
      { name: 'crawlee', status: 'active', purpose: 'Bounded crawl orchestration for multi-page retrieval.' },
      { name: 'cheerio', status: 'active', purpose: 'Deterministic HTML extraction for static pages.' },
      { name: 'playwright', status: 'active', purpose: 'Rendered page inspection when static extraction is insufficient.' },
    ],
    guardrail: 'Research mode must return sourced output or an honest unavailable state.',
  },
  {
    category: 'code',
    title: 'Repository and patch intelligence',
    summary: 'Prefer mature AST, diff, git, ignore, and glob primitives instead of hand-written repository parsers.',
    libraries: [
      { name: 'ts-morph', status: 'active', purpose: 'TypeScript AST inspection and safe structural edits.' },
      { name: 'diff', status: 'active', purpose: 'Human-readable patch previews and verification summaries.' },
      { name: 'simple-git', status: 'active', purpose: 'Git status, branch, and history access without shell parsing.' },
      { name: 'ignore', status: 'planned', purpose: 'Respect gitignore-style boundaries during file discovery.' },
      { name: 'fast-glob', status: 'active', purpose: 'Fast bounded workspace search across allowed roots.' },
    ],
    guardrail: 'Code capabilities must remain inspect-and-plan-first; mutation stays behind local policy and approval.',
  },
  {
    category: 'process',
    title: 'Controlled process execution',
    summary: 'Wrap process execution in one typed adapter rather than scattering raw shell strings through the runtime.',
    libraries: [
      { name: 'execa', status: 'planned', purpose: 'Structured command execution, cancellation, exit codes, and output capture.' },
    ],
    guardrail: 'Process execution must redact secrets, classify risk, capture exit status, and support cancellation.',
  },
  {
    category: 'documents',
    title: 'Documents and artifact production',
    summary: 'Use existing document libraries for inspectable artifacts rather than recreating file formats.',
    libraries: [
      { name: 'docx', status: 'active', purpose: 'DOCX creation and editing workflows.' },
      { name: 'exceljs', status: 'active', purpose: 'Spreadsheet reading, writing, and report tables.' },
      { name: 'pdf-lib', status: 'active', purpose: 'PDF composition and manipulation.' },
      { name: 'unpdf', status: 'active', purpose: 'PDF text extraction.' },
      { name: 'mammoth', status: 'active', purpose: 'DOCX content extraction.' },
      { name: 'papaparse', status: 'active', purpose: 'CSV parsing and export.' },
      { name: 'yaml', status: 'active', purpose: 'Manifest, frontmatter, and config parsing.' },
    ],
    guardrail: 'Artifact writes must be explicit, auditable, and verified before delivery.',
  },
  {
    category: 'design',
    title: 'Design artifact workflow',
    summary: 'Use current UI and rendering primitives to produce inspectable, parameterized design artifacts.',
    libraries: [
      { name: 'framer-motion', status: 'active', purpose: 'Controlled motion where it improves product UX.' },
      { name: 'lucide-react', status: 'active', purpose: 'Consistent interface icons without hand-drawn SVG drift.' },
      { name: 'playwright', status: 'active', purpose: 'Browser verification for responsive and interactive artifacts.' },
    ],
    guardrail: 'Design generation must start from context/assets and include review, not generic visual output.',
  },
  {
    category: 'memory',
    title: 'Search and memory retrieval',
    summary: 'Keep memory readable and auditable while using proven local search/ranking primitives.',
    libraries: [
      { name: '@orama/orama', status: 'active', purpose: 'Local structured search index.' },
      { name: 'fuse.js', status: 'active', purpose: 'Small fuzzy matching and fallback retrieval.' },
    ],
    guardrail: 'Private local memory must stay local unless the user explicitly chooses to share it.',
  },
  {
    category: 'validation',
    title: 'Contracts and typed boundaries',
    summary: 'Keep every external input, run, approval, skill, and capability shape validated.',
    libraries: [
      { name: 'zod', status: 'active', purpose: 'Runtime schema validation and typed contracts.' },
    ],
    guardrail: 'No MCP tool, skill, or side-effectful action should bypass schema validation.',
  },
];

export function listCapabilityLibraryStrategies() {
  return strategies.map((strategy) => capabilityLibraryStrategySchema.parse(strategy) as CapabilityLibraryStrategy);
}

export function getCapabilityLibraryStrategy(category: CapabilityLibraryStrategy['category']) {
  return listCapabilityLibraryStrategies().find((strategy) => strategy.category === category) ?? null;
}
