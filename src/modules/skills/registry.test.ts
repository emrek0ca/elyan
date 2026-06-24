import assert from "node:assert/strict";
import test from "node:test";
import { getPublicSkillCatalog, loadSkillRegistry, resetSkillRegistryForTests } from "./registry.js";
import { configureSkillDefinitionSchema, validateSkillDefinition } from "./validator.js";

const minimalDefinitionSchema = {
  type: "object",
  required: [
    "id",
    "version",
    "active",
    "name",
    "purpose",
    "summary",
    "instructions",
    "triggers",
    "inputSchema",
    "outputSchema",
    "allowedTools",
    "modelProfile",
    "maxInputTokens",
    "maxOutputTokens",
    "timeoutMs",
    "cachePolicy",
    "validation",
  ],
};

test("skill registry loads active document skills", async () => {
  resetSkillRegistryForTests();
  const skills = await loadSkillRegistry();
  const activeIds = skills.filter((skill) => skill.active).map((skill) => skill.id);

  assert.ok(activeIds.includes("document_summary"));
  assert.ok(activeIds.includes("document_key_points"));
  assert.ok(activeIds.includes("document_qa"));
  for (const skill of skills.filter((item) => item.active)) {
    assert.equal(typeof skill.displayName, "string");
    assert.equal(skill.displayName.length > 0, true);
    assert.equal(skill.slashCommand.startsWith("/"), true);
    assert.equal(skill.manualSelectable, true);
  }
});

test("public skill catalog exposes only UI-safe skill fields", async () => {
  resetSkillRegistryForTests();
  const catalog = await getPublicSkillCatalog();

  assert.equal(catalog.enabled, true);
  assert.equal(catalog.catalogVersion, "2026-06-skill-catalog-v1");
  assert.equal(catalog.items.some((item) => item.id === "document_summary"), true);
  const serialized = JSON.stringify(catalog);
  assert.doesNotMatch(serialized, /instructions|modelProfile|allowedTools|outputSchema|inputSchema/);
});

test("invalid skill definition is rejected", () => {
  configureSkillDefinitionSchema(minimalDefinitionSchema);

  assert.throws(
    () =>
      validateSkillDefinition({
        id: "broken_skill",
        version: "1.0.0",
      }),
    /invalid_skill_definition/,
  );
});

test("invalid skill display metadata is rejected", () => {
  configureSkillDefinitionSchema({
    type: "object",
    required: ["id", "slashCommand", "manualSelectable"],
    properties: {
      id: { type: "string" },
      slashCommand: { type: "string", pattern: "^/[^\\s]+$" },
      manualSelectable: { type: "boolean" },
    },
  });

  assert.throws(
    () =>
      validateSkillDefinition({
        id: "broken_display",
        slashCommand: "özetle",
        manualSelectable: true,
      }),
    /invalid_skill_definition/,
  );
});
