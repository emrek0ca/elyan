import type {
  CapabilityApprovalLevel,
  CapabilityCategory,
  CapabilityDirectoryEntry,
  CapabilityOperationalProfile,
  CapabilityRiskLevel,
  CapabilitySource,
} from './types';

export type CapabilityProfileGuide = {
  category: CapabilityCategory;
  title: string;
  summary: string;
  when: string;
  why: string;
  libraries: string[];
};

type CapabilityLike = {
  id: string;
  title: string;
  description: string;
};

function inferSource(capabilityId: string): CapabilitySource {
  switch (capabilityId) {
    case 'web_read_dynamic':
    case 'browser_automation':
      return 'browser_surface';
    case 'web_crawl':
    case 'tool_bridge':
      return 'local_bridge_tool';
    case 'mcp_bridge':
      return 'mcp_surface';
    default:
      return 'local_module';
  }
}

const categoryGuide: Record<CapabilityCategory, CapabilityProfileGuide> = {
  documents: {
    category: 'documents',
    title: 'Document suite',
    summary: 'Files, pages, tables, drafting, transforms, and content extraction.',
    when: 'The task starts from PDFs, DOCX files, spreadsheets, archives, markdown, OCR, metadata, or a requested brief/spec.',
    why: 'Keep file and document work deterministic, auditable, and scoped to the smallest transform that solves it.',
    libraries: ['pdfjs-dist', 'pdf-lib', 'docx', 'mammoth', 'exceljs', 'papaparse', 'jszip', 'tesseract.js', 'sharp', 'unified', 'fast-xml-parser'],
  },
  research: {
    category: 'research',
    title: 'Research lane',
    summary: 'Rendered page reads, site traversal, and evidence gathering.',
    when: 'The answer needs live sources, page inspection, or bounded multi-page collection.',
    why: 'Favor sourced retrieval over speculative answers and keep crawl depth narrow.',
    libraries: ['playwright', 'crawlee'],
  },
  comms: {
    category: 'comms',
    title: 'Communication lane',
    summary: 'Inbox triage, message drafting, and calendar-aware workflows.',
    when: 'The task changes how people are contacted or scheduled.',
    why: 'External communication should stay explicit, reversible, and clearly attributed.',
    libraries: [],
  },
  dev: {
    category: 'dev',
    title: 'Engineering lane',
    summary: 'Repo inspection, refactors, diffs, and release support.',
    when: 'The task touches code, builds, issues, or pull requests.',
    why: 'Engineering actions need strong verification and clean rollback boundaries.',
    libraries: [],
  },
  ops: {
    category: 'ops',
    title: 'Operations lane',
    summary: 'Local execution, tool bridges, and MCP surfaces.',
    when: 'The task needs local actions or connected services.',
    why: 'Operational surfaces should stay approval-bound and fully auditable.',
    libraries: ['ai', '@modelcontextprotocol/sdk'],
  },
  desktop: {
    category: 'desktop',
    title: 'Desktop lane',
    summary: 'Screens, UI automation, and evidence capture.',
    when: 'The task must interact with a visible app or system surface.',
    why: 'Desktop work needs screenshot-backed verification and clear approval gating.',
    libraries: ['playwright'],
  },
  memory: {
    category: 'memory',
    title: 'Memory lane',
    summary: 'Local search, summaries, and persistent context.',
    when: 'The task depends on project history, recall, or repeated context reuse.',
    why: 'Memory should stay structured, source-backed, and easy to audit.',
    libraries: ['@orama/orama', 'fuse.js'],
  },
  browser: {
    category: 'browser',
    title: 'Browser lane',
    summary: 'Rendered page reads and bounded browser actions.',
    when: 'The page is dynamic or the rendered DOM matters.',
    why: 'Browser automation should be explicit, narrow, and easy to inspect.',
    libraries: ['playwright'],
  },
  calculation: {
    category: 'calculation',
    title: 'Calculation lane',
    summary: 'Deterministic math, charts, and structured transforms.',
    when: 'The task is numeric, formulaic, or data-shaping.',
    why: 'Prefer deterministic helpers before broad model reasoning.',
    libraries: ['mathjs', 'decimal.js', 'recharts'],
  },
  general: {
    category: 'general',
    title: 'General lane',
    summary: 'Fallback answers when no specialized surface improves the result.',
    when: 'No dedicated capability changes the outcome.',
    why: 'Keep the fallback path clean and avoid unnecessary side effects.',
    libraries: [],
  },
};

const categoryDefaults: Record<
  CapabilityCategory,
  Omit<CapabilityOperationalProfile, 'category' | 'recommendedSkillId' | 'useCases'>
> = {
  documents: {
    riskLevel: 'medium',
    approvalLevel: 'CONFIRM',
    verificationMode: 'schema',
    rollbackMode: 'restore',
    safeByDefault: true,
  },
  research: {
    riskLevel: 'medium',
    approvalLevel: 'CONFIRM',
    verificationMode: 'snapshot',
    rollbackMode: 'manual',
    safeByDefault: true,
  },
  comms: {
    riskLevel: 'high',
    approvalLevel: 'SCREEN',
    verificationMode: 'audit',
    rollbackMode: 'manual',
    safeByDefault: false,
  },
  dev: {
    riskLevel: 'high',
    approvalLevel: 'CONFIRM',
    verificationMode: 'roundtrip',
    rollbackMode: 'reversible',
    safeByDefault: false,
  },
  ops: {
    riskLevel: 'high',
    approvalLevel: 'CONFIRM',
    verificationMode: 'audit',
    rollbackMode: 'manual',
    safeByDefault: false,
  },
  desktop: {
    riskLevel: 'high',
    approvalLevel: 'SCREEN',
    verificationMode: 'snapshot',
    rollbackMode: 'manual',
    safeByDefault: false,
  },
  memory: {
    riskLevel: 'medium',
    approvalLevel: 'CONFIRM',
    verificationMode: 'audit',
    rollbackMode: 'rebuild',
    safeByDefault: true,
  },
  browser: {
    riskLevel: 'high',
    approvalLevel: 'SCREEN',
    verificationMode: 'snapshot',
    rollbackMode: 'manual',
    safeByDefault: false,
  },
  calculation: {
    riskLevel: 'low',
    approvalLevel: 'AUTO',
    verificationMode: 'schema',
    rollbackMode: 'none',
    safeByDefault: true,
  },
  general: {
    riskLevel: 'low',
    approvalLevel: 'AUTO',
    verificationMode: 'schema',
    rollbackMode: 'none',
    safeByDefault: true,
  },
};

function inferCategory(capability: CapabilityLike): CapabilityCategory {
  switch (capability.id) {
    case 'math_exact':
    case 'math_decimal':
    case 'chart_generate':
      return 'calculation';
    case 'csv_parse':
    case 'csv_export':
    case 'docx_read':
    case 'docx_write':
    case 'pdf_extract':
    case 'pdf_workflow':
    case 'image_process':
    case 'spreadsheet_read':
    case 'spreadsheet_write':
    case 'archive_zip':
    case 'ocr_image':
    case 'metadata_parse':
    case 'markdown_render':
      return 'documents';
    case 'web_read_dynamic':
    case 'web_crawl':
      return 'research';
    case 'browser_automation':
      return 'browser';
    case 'local_search_index':
    case 'fuzzy_find':
      return 'memory';
    case 'tool_bridge':
    case 'mcp_bridge':
      return 'ops';
    default:
      return 'general';
  }
}

function buildUseCases(capabilityId: string, category: CapabilityCategory, description: string) {
  const fallback = description.replace(/\.$/, '');

  switch (capabilityId) {
    case 'fuzzy_find':
      return ['Find approximate matches in local text', 'Keep local lookup deterministic'];
    case 'math_exact':
      return ['Evaluate exact expressions', 'Keep numeric work deterministic'];
    case 'math_decimal':
      return ['Perform precise decimal arithmetic', 'Avoid floating-point drift'];
    case 'csv_parse':
      return ['Parse CSV into rows', 'Normalize tabular text'];
    case 'csv_export':
      return ['Export structured rows to CSV', 'Produce machine-readable tables'];
    case 'docx_read':
      return ['Extract document structure from DOCX', 'Summarize office files'];
    case 'docx_write':
      return ['Generate DOCX artifacts', 'Produce shareable office documents'];
    case 'pdf_extract':
      return ['Extract text from PDFs', 'Preserve source ordering'];
    case 'pdf_workflow':
      return ['Merge or split PDF artifacts', 'Apply safe PDF transforms'];
    case 'image_process':
      return ['Resize or normalize images', 'Prepare visual inputs for downstream work'];
    case 'spreadsheet_read':
      return ['Read workbook tabs', 'Inspect structured sheets'];
    case 'spreadsheet_write':
      return ['Write workbook data', 'Emit edited spreadsheets'];
    case 'archive_zip':
      return ['Pack or unpack archives', 'Inspect compressed file surfaces'];
    case 'ocr_image':
      return ['Read text from images', 'Recover scan content'];
    case 'metadata_parse':
      return ['Parse YAML, XML, and frontmatter', 'Extract structured metadata'];
    case 'markdown_render':
      return ['Render markdown safely', 'Normalize rich text to HTML'];
    case 'local_search_index':
      return ['Index local knowledge', 'Run deterministic local search'];
    case 'web_read_dynamic':
      return ['Read rendered pages', 'Capture dynamic page content'];
    case 'web_crawl':
      return ['Traverse bounded site sections', 'Gather page-level evidence'];
    case 'browser_automation':
      return ['Perform bounded browser actions', 'Interact with rendered UI'];
    case 'tool_bridge':
      return ['Call deterministic local tools', 'Bridge schema-bound execution'];
    case 'mcp_bridge':
      return ['Inspect configured MCP surfaces', 'Discover external tool manifests'];
    case 'chart_generate':
      return ['Summarize series data', 'Render compact chart markup'];
    default:
      return [fallback, `Operate within the ${category} lane`];
  }
}

function buildSkillLink(capabilityId: string): string | undefined {
  switch (capabilityId) {
    case 'web_read_dynamic':
    case 'web_crawl':
      return 'research_companion';
    case 'browser_automation':
      return 'browser_operator';
    case 'tool_bridge':
    case 'mcp_bridge':
      return 'workspace_operator';
    case 'pdf_extract':
    case 'pdf_workflow':
    case 'docx_read':
    case 'docx_write':
    case 'csv_parse':
    case 'csv_export':
    case 'spreadsheet_read':
    case 'spreadsheet_write':
    case 'archive_zip':
    case 'ocr_image':
    case 'metadata_parse':
    case 'markdown_render':
    case 'local_search_index':
      return 'document_inspector';
    default:
      return undefined;
  }
}

function buildProfileForCapability(capability: CapabilityLike): CapabilityOperationalProfile {
  const category = inferCategory(capability);
  const defaults = categoryDefaults[category];
  const recommendedSkillId = buildSkillLink(capability.id);

  return {
    category,
    recommendedSkillId,
    useCases: buildUseCases(capability.id, category, capability.description),
    ...defaults,
  };
}

export function buildCapabilityOperationalProfile(capability: CapabilityLike): CapabilityOperationalProfile {
  if (capability.id === 'web_crawl') {
    return {
      category: 'research',
      riskLevel: 'high',
      approvalLevel: 'SCREEN',
      verificationMode: 'snapshot',
      rollbackMode: 'manual',
      safeByDefault: false,
      recommendedSkillId: 'research_companion',
      useCases: ['Traverse bounded site sections', 'Gather page-level evidence'],
    };
  }

  if (capability.id === 'browser_automation') {
    return {
      category: 'browser',
      riskLevel: 'high',
      approvalLevel: 'SCREEN',
      verificationMode: 'snapshot',
      rollbackMode: 'manual',
      safeByDefault: false,
      recommendedSkillId: 'browser_operator',
      useCases: ['Perform bounded browser actions', 'Interact with rendered UI'],
    };
  }

  if (capability.id === 'tool_bridge') {
    return {
      category: 'ops',
      riskLevel: 'medium',
      approvalLevel: 'CONFIRM',
      verificationMode: 'audit',
      rollbackMode: 'manual',
      safeByDefault: false,
      recommendedSkillId: 'workspace_operator',
      useCases: ['Call deterministic local tools', 'Bridge schema-bound execution'],
    };
  }

  if (capability.id === 'mcp_bridge') {
    return {
      category: 'ops',
      riskLevel: 'high',
      approvalLevel: 'SCREEN',
      verificationMode: 'audit',
      rollbackMode: 'manual',
      safeByDefault: false,
      recommendedSkillId: 'workspace_operator',
      useCases: ['Inspect configured MCP surfaces', 'Discover external tool manifests'],
    };
  }

  if (capability.id === 'local_search_index') {
    return {
      category: 'memory',
      riskLevel: 'medium',
      approvalLevel: 'CONFIRM',
      verificationMode: 'audit',
      rollbackMode: 'rebuild',
      safeByDefault: true,
      recommendedSkillId: 'document_inspector',
      useCases: ['Index local knowledge', 'Run deterministic local search'],
    };
  }

  return buildProfileForCapability(capability);
}

export function buildCapabilityProfileGuide(category: CapabilityCategory) {
  return categoryGuide[category];
}

export function listCapabilityProfileGuides() {
  return Object.values(categoryGuide);
}

export function formatCapabilityApproval(level: CapabilityApprovalLevel) {
  switch (level) {
    case 'AUTO':
      return 'Auto';
    case 'CONFIRM':
      return 'Confirm';
    case 'SCREEN':
      return 'Screen';
    case 'TWO_FA':
      return '2FA';
  }
}

export function formatCapabilityRisk(level: CapabilityRiskLevel) {
  switch (level) {
    case 'low':
      return 'Low';
    case 'medium':
      return 'Medium';
    case 'high':
      return 'High';
    case 'critical':
      return 'Critical';
  }
}

export function buildCapabilityDirectoryEntry(
  capability: CapabilityLike & { library: string; timeoutMs: number; enabled: boolean }
): CapabilityDirectoryEntry {
  return {
    id: capability.id,
    title: capability.title,
    description: capability.description,
    library: capability.library,
    timeoutMs: capability.timeoutMs,
    enabled: capability.enabled,
    source: inferSource(capability.id),
    profile: buildCapabilityOperationalProfile(capability),
  };
}
