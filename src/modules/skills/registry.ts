import type { PublicSkillCatalog, SkillDefinition, SkillSummary } from "./types.js";
import { loadSkillDefinitionsFromFiles } from "./loaders/file-skill-loader.js";

let cachedDefinitions: Promise<SkillDefinition[]> | null = null;

export async function loadSkillRegistry(): Promise<SkillDefinition[]> {
  cachedDefinitions ??= loadSkillDefinitionsFromFiles();
  return cachedDefinitions;
}

export function resetSkillRegistryForTests() {
  cachedDefinitions = null;
}

export async function listActiveSkillSummaries(): Promise<SkillSummary[]> {
  const definitions = await loadSkillRegistry();
  return definitions
    .filter((skill) => skill.active)
    .map((skill) => ({
        id: skill.id,
        version: skill.version,
        active: skill.active,
        name: skill.name,
        displayName: skill.displayName,
        displayDescription: skill.displayDescription,
        slashCommand: skill.slashCommand,
        uiCategory: skill.uiCategory,
        requiresAttachment: skill.requiresAttachment,
        supportedMimeTypes: skill.supportedMimeTypes,
        manualSelectable: skill.manualSelectable,
        purpose: skill.purpose,
        summary: skill.summary,
        triggers: skill.triggers,
        modelProfile: skill.modelProfile,
    }));
}

export async function getPublicSkillCatalog(): Promise<PublicSkillCatalog> {
  const definitions = await loadSkillRegistry();
  const items = definitions
    .filter((skill) => skill.active)
    .map((skill) => ({
      id: skill.id,
      version: skill.version,
      skillHint: skill.id,
      displayName: skill.displayName,
      displayDescription: skill.displayDescription,
      slashCommand: skill.slashCommand,
      uiCategory: skill.uiCategory,
      requiresAttachment: skill.requiresAttachment,
      supportedMimeTypes: skill.supportedMimeTypes,
      manualSelectable: skill.manualSelectable,
    }));

  return {
    enabled: items.length > 0,
    catalogVersion: "2026-06-skill-catalog-v1",
    items,
  };
}

export async function getActiveSkillById(skillId: string): Promise<SkillDefinition | null> {
  const definitions = await loadSkillRegistry();
  return definitions.find((skill) => skill.active && skill.id === skillId) ?? null;
}
