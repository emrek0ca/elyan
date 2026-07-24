import type { ErrorObject, ValidateFunction } from 'ajv';
import schema from '../../contracts/assistant-blocks.schema.json';
import standaloneValidate from '../../contracts/assistant-blocks.validator.mjs';

export const ASSISTANT_BLOCK_SCHEMA_DIGEST = 'e4d362d3126336edf367b7df4263ca6ba3d777fea63b55d3ad34ab4a869cfb5b';
export const ASSISTANT_BLOCK_ENVELOPE_VERSION = 'elyan_blocks.v2';

const embeddedDigest = String((schema as Record<string, unknown>)['x-elyan-schema-digest'] || '');
if (embeddedDigest !== ASSISTANT_BLOCK_SCHEMA_DIGEST) throw new Error('elyan_block_schema_digest_mismatch');

const validate = standaloneValidate as ValidateFunction;

export type AssistantBlock = {
  type: string;
  version?: number;
  blockId?: string;
  stableBlockId?: string;
  visibility?: string;
  isRenderable?: boolean;
  data?: Record<string, unknown>;
  [key: string]: unknown;
};

export type BlockValidation = {
  valid: boolean;
  block: AssistantBlock | null;
  errors: ErrorObject[];
};

export function validateAssistantBlock(value: unknown): BlockValidation {
  const valid = validate(value);
  return {
    valid: Boolean(valid),
    block: valid ? value as AssistantBlock : null,
    errors: valid ? [] : [...(validate.errors || [])],
  };
}

export function schemaDigestMatches(metadata: unknown): boolean {
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return true;
  const value = metadata as Record<string, unknown>;
  const digest = String(value.blockSchemaDigest || value.schemaDigest || '').trim();
  return !digest || digest === ASSISTANT_BLOCK_SCHEMA_DIGEST;
}
