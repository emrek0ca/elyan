import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod/v4";

import {
  ELYAN_ASSISTANT_BLOCK_ENVELOPE_VERSION,
  elyanAssistantBlockEnvelopeSchemaByType,
  elyanAssistantBlockTypeValues,
  elyanAssistantLegacyTopLevelBlockSchema,
  elyanSourceWidgetBlockTypeValues,
} from "../contracts/assistant-block-schemas.js";

type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "../..");
const outputPath = resolve(
  repositoryRoot,
  "contracts/generated/assistant-blocks.schema.json",
);

function pascalCase(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]!.toUpperCase() + part.slice(1))
    .join("");
}

function sortJson(value: unknown): JsonValue {
  if (value === null || typeof value !== "object") {
    return value as null | boolean | number | string;
  }
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  return Object.keys(value as Record<string, unknown>)
    .sort()
    .reduce<Record<string, JsonValue>>((output, key) => {
      output[key] = sortJson((value as Record<string, unknown>)[key]);
      return output;
    }, {});
}

function schemaWithoutRootMarker(schema: Record<string, unknown>) {
  const { $schema: _schema, ...rest } = schema;
  return rest;
}

const definitions: Record<string, JsonValue> = {};
const definitionByType: Record<string, string> = {};

for (const type of elyanAssistantBlockTypeValues) {
  const definitionName = `${pascalCase(type)}Block`;
  definitionByType[type] = definitionName;
  const generated = schemaWithoutRootMarker(
    z.toJSONSchema(elyanAssistantBlockEnvelopeSchemaByType[type], {
      target: "draft-2020-12",
      reused: "inline",
      cycles: "ref",
    }) as Record<string, unknown>,
  );
  generated.title = definitionName;
  const properties = generated.properties as
    | Record<string, Record<string, unknown>>
    | undefined;
  if (properties?.version) {
    // Zod represents numeric literals as JSON Schema numbers. The protocol
    // version is an integer and Dart should generate `int`, not `double`.
    properties.version.type = "integer";
  }
  if (properties?.data) {
    properties.data.title = `${definitionName}Data`;
  }
  definitions[definitionName] = sortJson(generated);
}

const legacyDefinition = schemaWithoutRootMarker(
  z.toJSONSchema(elyanAssistantLegacyTopLevelBlockSchema, {
    target: "draft-2020-12",
    reused: "inline",
    cycles: "ref",
  }) as Record<string, unknown>,
);
legacyDefinition.title = "LegacyTopLevelBlock";
legacyDefinition.not = {
  anyOf: [
    { required: ["version"] },
    { required: ["blockId"] },
    { required: ["data"] },
  ],
};
definitions.LegacyTopLevelBlock = sortJson(legacyDefinition);

const contractWithoutDigest = sortJson({
  $defs: definitions,
  $id: "https://schemas.elyan.dev/assistant-blocks.schema.json",
  $schema: "https://json-schema.org/draft/2020-12/schema",
  description:
    "Generated from Elyan Zod schemas. Canonical envelopes are additive to legacy elyan_blocks.v2 top-level blocks.",
  oneOf: [
    ...elyanAssistantBlockTypeValues.map((type) => ({
      $ref: `#/$defs/${definitionByType[type]}`,
    })),
    { $ref: "#/$defs/LegacyTopLevelBlock" },
  ],
  title: "ElyanAssistantBlockTransport",
  "x-elyan-canonical-types": [...elyanAssistantBlockTypeValues],
  "x-elyan-definition-by-type": definitionByType,
  "x-elyan-envelope-version": ELYAN_ASSISTANT_BLOCK_ENVELOPE_VERSION,
  "x-elyan-source-widget-types": [...elyanSourceWidgetBlockTypeValues],
});

const digestInput = `${JSON.stringify(contractWithoutDigest, null, 2)}\n`;
const schemaDigest = createHash("sha256").update(digestInput).digest("hex");
const contract = sortJson({
  ...(contractWithoutDigest as Record<string, JsonValue>),
  "x-elyan-schema-digest": schemaDigest,
});

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(contract, null, 2)}\n`, "utf8");
process.stdout.write(`Generated ${outputPath}\nSchema SHA-256: ${schemaDigest}\n`);
