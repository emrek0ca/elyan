import type { z, ZodTypeAny } from 'zod';

export type CapabilityStatus = 'success' | 'error' | 'disabled' | 'timeout';

export type CapabilityAuditEntry = {
  capabilityId: string;
  title: string;
  status: CapabilityStatus;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  errorMessage?: string;
};

export type CapabilityExecutionContext = {
  signal: AbortSignal;
};

export type CapabilityDefinition<
  InputSchema extends ZodTypeAny = ZodTypeAny,
  OutputSchema extends ZodTypeAny = ZodTypeAny,
> = {
  id: string;
  title: string;
  description: string;
  library: string;
  enabled: boolean;
  timeoutMs: number;
  inputSchema: InputSchema;
  outputSchema: OutputSchema;
  run: (
    input: z.output<InputSchema>,
    context: CapabilityExecutionContext
  ) => Promise<z.output<OutputSchema>> | z.output<OutputSchema>;
};

export type CapabilityRegistration = {
  disabledCapabilityIds?: string[];
};

