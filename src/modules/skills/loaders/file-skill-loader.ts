import { readdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { configureSkillDefinitionSchema, validateSkillDefinition } from "../validator.js";
import type { SkillDefinition } from "../types.js";

const moduleDir = dirname(fileURLToPath(import.meta.url));

function uniquePaths(paths: string[]): string[] {
  return [...new Set(paths.map((path) => resolve(path)))];
}

function candidateRoots(kind: "definitions" | "schemas"): string[] {
  const projectRoot = process.cwd();
  return uniquePaths([
    join(moduleDir, "..", kind),
    join(projectRoot, "src", "modules", "skills", kind),
    join(projectRoot, "dist", "modules", "skills", kind),
  ]);
}

async function readFirstExistingJson(fileName: string, kind: "definitions" | "schemas") {
  const errors: string[] = [];
  for (const root of candidateRoots(kind)) {
    try {
      return JSON.parse(await readFile(join(root, fileName), "utf8")) as Record<string, unknown>;
    } catch (error) {
      errors.push(`${root}:${error instanceof Error ? error.message : String(error)}`);
    }
  }
  throw new Error(`skill_json_not_found:${fileName}:${errors.join("|")}`);
}

async function listDefinitionFiles(): Promise<string[]> {
  for (const root of candidateRoots("definitions")) {
    try {
      return (await readdir(root))
        .filter((file) => file.endsWith(".skill.json"))
        .sort();
    } catch {
      continue;
    }
  }
  return [];
}

export async function loadSkillDefinitionsFromFiles(): Promise<SkillDefinition[]> {
  const schema = await readFirstExistingJson("skill-definition.schema.json", "schemas");
  configureSkillDefinitionSchema(schema);

  const files = await listDefinitionFiles();
  const definitions: SkillDefinition[] = [];
  for (const file of files) {
    const raw = await readFirstExistingJson(file, "definitions");
    definitions.push(validateSkillDefinition(raw));
  }
  return definitions;
}
