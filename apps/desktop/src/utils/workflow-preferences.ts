import type {
  DocumentOutputMode,
  PresentationOutputMode,
  ProjectTemplate,
  WorkflowAudience,
  WorkflowLanguage,
  WorkflowPreferences,
  WorkflowReviewStrictness,
  WorkflowRoutingProfile,
  WorkflowTaskType,
  WorkflowTone,
  WebsiteStack,
} from "@/types/domain";

export const defaultWorkflowPreferences: WorkflowPreferences = {
  language: "tr",
  audience: "executive",
  tone: "premium",
  websiteStack: "react",
  documentOutput: "docx_pdf",
  presentationOutput: "pptx_pdf",
};

export const defaultProjectTemplates: ProjectTemplate[] = [
  {
    id: "elyan-core",
    name: "Elyan Core",
    description: "Internal planning, architecture, operator documentation.",
    sessionId: "project:elyan-core",
    preferredTaskType: "document",
    routingProfile: "local_first",
    reviewStrictness: "balanced",
    preferences: {
      language: "tr",
      audience: "developer",
      tone: "technical",
      documentOutput: "docx_pdf",
      websiteStack: "react",
    },
  },
  {
    id: "client-delivery",
    name: "Client Delivery",
    description: "Narrative-heavy decks and client-facing polished output.",
    sessionId: "project:client-delivery",
    preferredTaskType: "presentation",
    routingProfile: "quality_first",
    reviewStrictness: "strict",
    preferences: {
      language: "en",
      audience: "client",
      tone: "editorial",
      presentationOutput: "pptx_pdf",
    },
  },
  {
    id: "web-launch",
    name: "Web Launch",
    description: "Website strategy, scaffold, and shipping-oriented product surfaces.",
    sessionId: "project:web-launch",
    preferredTaskType: "website",
    routingProfile: "balanced",
    reviewStrictness: "strict",
    preferences: {
      language: "en",
      audience: "client",
      tone: "premium",
      websiteStack: "react",
    },
  },
];

export const workflowLanguageOptions: Array<{ label: string; value: WorkflowLanguage }> = [
  { label: "TR", value: "tr" },
  { label: "EN", value: "en" },
];

export const workflowAudienceOptions: Array<{ label: string; value: WorkflowAudience }> = [
  { label: "Executive", value: "executive" },
  { label: "Developer", value: "developer" },
  { label: "Client", value: "client" },
];

export const workflowToneOptions: Array<{ label: string; value: WorkflowTone }> = [
  { label: "Premium", value: "premium" },
  { label: "Technical", value: "technical" },
  { label: "Editorial", value: "editorial" },
];

export const websiteStackOptions: Array<{ label: string; value: WebsiteStack }> = [
  { label: "React", value: "react" },
  { label: "Next.js", value: "nextjs" },
  { label: "Vanilla", value: "vanilla" },
];

export const documentOutputOptions: Array<{ label: string; value: DocumentOutputMode }> = [
  { label: "DOCX + PDF", value: "docx_pdf" },
  { label: "PDF", value: "pdf" },
  { label: "DOCX", value: "docx" },
];

export const presentationOutputOptions: Array<{ label: string; value: PresentationOutputMode }> = [
  { label: "PPTX + PDF", value: "pptx_pdf" },
  { label: "PPTX", value: "pptx" },
];

export function preferredFormatsForTask(taskType: WorkflowTaskType, preferences: WorkflowPreferences): string[] {
  if (taskType === "document") {
    if (preferences.documentOutput === "pdf") {
      return ["pdf"];
    }
    if (preferences.documentOutput === "docx") {
      return ["docx"];
    }
    return ["docx", "pdf"];
  }

  if (taskType === "presentation") {
    if (preferences.presentationOutput === "pptx") {
      return ["pptx"];
    }
    return ["pptx", "pdf"];
  }

  return [];
}

export function mergeWorkflowPreferences(
  base: WorkflowPreferences,
  overrides?: Partial<WorkflowPreferences>,
): WorkflowPreferences {
  return {
    ...base,
    ...(overrides || {}),
  };
}

export function resolveProjectTemplate(templates: ProjectTemplate[], activeProjectTemplateId: string): ProjectTemplate {
  return templates.find((item) => item.id === activeProjectTemplateId) || templates[0] || {
    ...defaultProjectTemplates[0],
  };
}

export function inferRoutingProfile(
  taskType: WorkflowTaskType,
  preferences: WorkflowPreferences,
  template: ProjectTemplate,
  autoRouting: boolean,
): WorkflowRoutingProfile {
  if (!autoRouting) {
    return "local_first";
  }
  if (template.routingProfile) {
    return template.routingProfile;
  }
  if (taskType === "website" || preferences.audience === "developer") {
    return "local_first";
  }
  if (taskType === "presentation" || preferences.tone === "editorial" || preferences.audience === "client") {
    return "quality_first";
  }
  return "balanced";
}

export function inferReviewStrictness(
  taskType: WorkflowTaskType,
  preferences: WorkflowPreferences,
  template: ProjectTemplate,
): WorkflowReviewStrictness {
  if (template.reviewStrictness) {
    return template.reviewStrictness;
  }
  if (taskType === "website" || preferences.audience === "client" || preferences.tone === "editorial") {
    return "strict";
  }
  return "balanced";
}

export function projectTemplateSummary(template: ProjectTemplate): string {
  return `${template.name} · ${routingProfileLabel(template.routingProfile)} · ${reviewStrictnessLabel(template.reviewStrictness)}`;
}

export function languageLabel(language: WorkflowLanguage): string {
  return language === "en" ? "English" : "Turkish";
}

export function audienceLabel(audience: WorkflowAudience): string {
  if (audience === "developer") {
    return "Developer";
  }
  if (audience === "client") {
    return "Client";
  }
  return "Executive";
}

export function toneLabel(tone: WorkflowTone): string {
  if (tone === "technical") {
    return "Technical";
  }
  if (tone === "editorial") {
    return "Editorial";
  }
  return "Premium";
}

export function stackLabel(stack: WebsiteStack): string {
  if (stack === "nextjs") {
    return "Next.js";
  }
  if (stack === "vanilla") {
    return "Vanilla";
  }
  return "React";
}

export function outputModeLabel(taskType: WorkflowTaskType, preferences: WorkflowPreferences): string {
  return preferredFormatsForTask(taskType, preferences)
    .map((item) => item.toUpperCase())
    .join(" + ");
}

export function workflowProfileSummary(preferences: WorkflowPreferences): string {
  return [
    languageLabel(preferences.language),
    audienceLabel(preferences.audience),
    toneLabel(preferences.tone),
    stackLabel(preferences.websiteStack),
  ].join(" · ");
}

export function routingProfileLabel(profile: WorkflowRoutingProfile | string): string {
  const normalized = String(profile || "").replace(/_/g, " ").trim().toLowerCase();
  if (normalized === "local first") {
    return "Local first";
  }
  if (normalized === "quality first") {
    return "Quality first";
  }
  return "Balanced";
}

export function reviewStrictnessLabel(strictness: WorkflowReviewStrictness | string): string {
  return String(strictness || "").trim().toLowerCase() === "strict" ? "Strict review" : "Balanced review";
}
